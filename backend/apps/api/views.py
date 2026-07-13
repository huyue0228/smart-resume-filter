import io
import mimetypes
import os
import zipfile
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.db.models import Q
from rest_framework.authtoken.models import Token
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import (
    HasPermissionCode,
    PERMISSION_TREE,
    has_permission_code,
    user_permission_codes,
)
from apps.core import models as m
from apps.core import system_status
from apps.ingestion import snapshot
from apps.ingestion.sources import (
    RESUME_SUBDIR,
    import_files,
)
from apps.pipeline.ai_config import PUBLIC_AI_CONFIG_REGISTRY
from apps.pipeline import ai_config, cancellation, runner
from apps.pipeline.tasks import execute_runs_sequence_task
from apps.pipeline.services import allocate as allocate_service
from apps.pipeline.ai import service as ai_service

from . import serializers


CONFIG_REGISTRY = {
    **PUBLIC_AI_CONFIG_REGISTRY,
    "welink_enabled": {
        "label": "WeLink 下发开关",
        "description": "关闭时仅记录下发状态，不调用真实 WeLink。",
        "value_type": "boolean",
        "default": False,
    },
}


def bool_query_value(value):
    if value in ["true", "false"]:
        return value == "true"
    return None


def submit_processing_runs(runs):
    """提交一组已创建运行，并为上传与手动处理统一回填 Celery 审计标识。"""
    if not runs:
        return runs
    task = execute_runs_sequence_task.delay([run.id for run in runs])
    task_id = getattr(task, "id", "") or ""
    for run in runs:
        run.refresh_from_db()
        if not run.celery_task_id:
            run.celery_task_id = task_id
            run.save(update_fields=["celery_task_id"])
    return runs


def _clear_user_references(users):
    user_ids = [user.id for user in users if user and user.id]
    if not user_ids:
        return
    m.AssignmentAttempt.objects.filter(created_by_id__in=user_ids).update(
        created_by=None
    )
    m.AssignmentHandoff.objects.filter(created_by_id__in=user_ids).update(
        created_by=None
    )


def _delete_users(users):
    users = [user for user in users if user and user.id]
    if not users:
        return
    _clear_user_references(users)
    user_ids = [user.id for user in users]
    Token.objects.filter(user_id__in=user_ids).delete()
    for user in users:
        user.groups.clear()
        user.user_permissions.clear()
        user.delete()


def _clear_contact_references(contact):
    if not contact or not contact.id:
        return
    m.AssignmentAttempt.objects.filter(contact=contact).update(contact=None)
    m.AssignmentAttempt.objects.filter(sub_contact=contact).update(sub_contact=None)
    m.AssignmentHandoff.objects.filter(from_contact=contact).update(from_contact=None)
    m.AssignmentHandoff.objects.filter(to_contact=contact).update(to_contact=None)
    m.AgentDispatchDecision.objects.filter(recommended_contact=contact).update(
        recommended_contact=None
    )


def delete_contact_and_bound_users(contact):
    with transaction.atomic():
        locked_contact = m.Contact.objects.select_for_update().get(pk=contact.pk)
        users = list(User.objects.select_for_update().filter(contact=locked_contact))
        _clear_contact_references(locked_contact)
        User.objects.filter(contact=locked_contact).update(contact=None)
        _delete_users(users)
        locked_contact.delete()


def delete_user_and_bound_contact(user):
    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        contact = locked_user.contact
        if contact:
            delete_contact_and_bound_users(contact)
            return
        _delete_users([locked_user])


def _resume_file_info(resume):
    fname = os.path.basename(resume.resume_file or "")
    path = os.path.join(settings.MEDIA_ROOT, RESUME_SUBDIR, fname) if fname else ""
    if path and os.path.exists(path):
        return fname, path
    return "", ""


def _attachment_response(path, filename):
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(path, "rb") as file_obj:
        response = HttpResponse(file_obj.read(), content_type=content_type)
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
    response["X-Resume-Filename"] = quote(filename)
    return response


def resume_export_response(resumes):
    available, missing = [], []
    for resume in resumes:
        fname, path = _resume_file_info(resume)
        if path:
            available.append((resume, fname, path))
        else:
            missing.append(f"{resume.candidate.name}（{resume.apply_id}）")

    if len(available) == 1 and not missing:
        _, fname, path = available[0]
        response = _attachment_response(path, fname)
        response["X-Export-Count"] = "1"
        response["X-Export-Missing"] = "0"
        return response

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, fname, path in available:
            zf.write(path, arcname=fname)
        if missing:
            zf.writestr(
                "缺失简历文件清单.txt",
                "以下候选人暂无简历文件（未上传简历包或未匹配）：\n"
                + "\n".join(missing),
            )

    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = 'attachment; filename="resumes_export.zip"'
    resp["X-Export-Count"] = str(len(available))
    resp["X-Export-Missing"] = str(len(missing))
    return resp


def resume_zip_response(resumes):
    return resume_export_response(resumes)


def resume_preview_response(resume):
    if not resume.resume_file:
        return Response({"detail": "该投递暂无简历文件"}, status=status.HTTP_404_NOT_FOUND)
    fname = os.path.basename(resume.resume_file)
    path = os.path.join(settings.MEDIA_ROOT, RESUME_SUBDIR, fname)
    if not os.path.exists(path):
        return Response({"detail": "简历文件不存在"}, status=status.HTTP_404_NOT_FOUND)
    content_type = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    with open(path, "rb") as file_obj:
        response = HttpResponse(file_obj.read(), content_type=content_type)
    response["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(fname)}"
    response["X-Resume-Filename"] = quote(fname)
    return response


class PermissionedModelViewSet(viewsets.ModelViewSet):
    permission_classes = [HasPermissionCode]


class PermissionedReadOnlyModelViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [HasPermissionCode]


class AuthLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username", "")
        password = request.data.get("password", "")
        user = authenticate(request, username=username, password=password)
        if not user or not user.is_active:
            return Response(
                {"detail": "用户名或密码错误"}, status=status.HTTP_400_BAD_REQUEST
            )
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user": serializers.CurrentUserSerializer(user).data,
            }
        )


class AuthLogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({"detail": "已退出登录"})


class MeView(APIView):
    def get(self, request):
        return Response(serializers.CurrentUserSerializer(request.user).data)


class AIAvailabilityView(APIView):
    permission_classes = [HasPermissionCode]
    permission_code = "pipeline.run"

    def get(self, request):
        return Response({"enabled": ai_config.is_ai_enabled()})


class ImportView(APIView):
    """数据导入：multipart 上传 4 张表 + 简历包。"""

    permission_classes = [HasPermissionCode]
    permission_code = "resume.import"
    parser_classes = [MultiPartParser, FormParser]

    FIELD_KEYS = ["resume_list", "jobs", "schools", "contacts", "resume_package"]

    def post(self, request):
        files = {key: request.FILES.get(key) for key in self.FIELD_KEYS}
        if not any(files.values()):
            return Response(
                {"detail": "未上传任何文件"}, status=status.HTTP_400_BAD_REQUEST
            )
        mode = request.data.get("mode", "incremental")
        # 含简历数据的上传：先存撤销快照（上传前状态），再导入
        takes_resume = bool(files.get("resume_list") or files.get("resume_package"))
        if takes_resume:
            snapshot.take_snapshot(label="上传简历前")
        try:
            counts = import_files(files, mode=mode)
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"导入失败: {exc}"}, status=status.HTTP_400_BAD_REQUEST
            )
        candidate_ids = counts.pop("_candidate_ids", [])
        processing_runs = []
        if takes_resume and candidate_ids:
            modes = ["rule"]
            if ai_config.is_ai_enabled():
                modes.append("ai")
            processing_runs = runner.create_runs(
                "resume_process",
                modes=modes,
                scope={"candidate_ids": candidate_ids, "source": "resume_import"},
                created_by=request.user,
            )
            # 同一批候选人的 Rule 与 AI 结果按顺序生成，避免流程锁和重跑清理互相干扰。
            submit_processing_runs(processing_runs)
        return Response(
            {
                "detail": "导入完成",
                "counts": counts,
                "undo_available": takes_resume,
                "processing_runs": serializers.ProcessingRunSerializer(
                    processing_runs, many=True
                ).data,
            },
            status=(
                status.HTTP_202_ACCEPTED
                if any(run.status in ["pending", "running"] for run in processing_runs)
                else status.HTTP_200_OK
            ),
        )


class ImportUndoView(APIView):
    """单级撤销最近一次简历上传（含其处理结果）。"""

    permission_classes = [HasPermissionCode]
    permission_code = "resume.import"

    def get(self, request):
        snap = snapshot.latest_snapshot()
        return Response(
            {
                "available": snap is not None,
                "label": snap.label if snap else "",
                "created_at": snap.created_at if snap else None,
            }
        )

    def post(self, request):
        ok = snapshot.restore_latest()
        return Response(
            {"detail": "已撤销上次上传" if ok else "无可撤销的上传", "ok": ok}
        )


class ResumeViewSet(PermissionedReadOnlyModelViewSet):
    serializer_class = serializers.ResumeListSerializer
    permission_code = "resume.view"

    def get_queryset(self):
        qs = m.Resume.objects.select_related("candidate", "job").order_by("-imported_at")
        p = self.request.query_params
        search = p.get("search")
        if search:
            qs = qs.filter(candidate__name__icontains=search) | qs.filter(
                candidate__phone__icontains=search
            ) | qs.filter(position_name__icontains=search)
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("imported_after"):
            qs = qs.filter(imported_at__date__gte=p["imported_after"])
        if p.get("imported_before"):
            qs = qs.filter(imported_at__date__lte=p["imported_before"])
        return qs.distinct()

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, pk=None):
        resume = self.get_object()
        return resume_preview_response(resume)

    @action(detail=True, methods=["post"], url_path="manual-assign")
    def manual_assign(self, request, pk=None):
        if not has_permission_code(request.user, "resume.manual_assign"):
            return Response({"detail": "无手动分配权限"}, status=status.HTTP_403_FORBIDDEN)
        resume = self.get_object()
        contact_id = request.data.get("contact_id") or request.data.get("contact")
        if not contact_id:
            return Response(
                {"detail": "contact_id 为必填项"}, status=status.HTTP_400_BAD_REQUEST
            )
        contact = m.Contact.objects.filter(pk=contact_id).first()
        if not contact:
            return Response(
                {"detail": "目标接口人不存在"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            secondary_contact = None
            secondary_contact_id = request.data.get("secondary_contact_id")
            if secondary_contact_id:
                secondary_contact = m.Contact.objects.filter(pk=secondary_contact_id).first()
                if not secondary_contact:
                    return Response(
                        {"detail": "指定二级接口人不存在"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            attempt = allocate_service.manual_assign(
                resume,
                contact,
                user=request.user,
                manual_reason=request.data.get("manual_reason", ""),
                secondary_contact=secondary_contact,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.AssignmentAttemptSerializer(attempt).data)


class CandidateViewSet(PermissionedModelViewSet):
    serializer_class = serializers.CandidateSerializer
    permission_codes_by_action = {
        "list": "resume.view",
        "retrieve": "resume.view",
        "create": "resume.import",
        "update": "resume.import",
        "partial_update": "resume.import",
        "destroy": "resume.import",
        "export_resumes": "resume.view",
        "filter_options": "resume.view",
    }

    def _base_queryset(self):
        return (
            m.Candidate.objects.prefetch_related(
                "resumes",
                "resumes__job__department__parent",
                "workflow__attempts__resume",
                "workflow__attempts__contact",
                "workflow__attempts__sub_contact",
                "workflow__attempts__department",
                "workflow__attempts__sub_department",
            )
            .select_related(
                "first_degree_tag",
                "highest_degree_tag",
                "workflow__current_resume",
                "workflow__current_resume__job",
                "workflow__current_resume__job__department",
                "workflow__current_resume__job__department__parent",
            )
            .order_by("-updated_at")
        )

    def get_queryset(self):
        return system_status.apply_candidate_filters(
            self._base_queryset(), self.request.query_params
        )

    @action(detail=False, methods=["get"], url_path="filter-options")
    def filter_options(self, request):
        """返回简历库表头选择器的当前可选值。"""
        return Response(system_status.candidate_filter_options(self._base_queryset()))

    @action(detail=False, methods=["get"], url_path="export")
    def export_resumes(self, request):
        ids = request.query_params.get("ids")
        qs = self.get_queryset()
        if ids:
            id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
            qs = qs.filter(id__in=id_list)
        resumes = (
            m.Resume.objects.select_related("candidate")
            .filter(candidate__in=qs)
            .order_by("candidate_id", "volunteer_rank", "id")
        )
        return resume_zip_response(resumes)


class JobViewSet(PermissionedModelViewSet):
    serializer_class = serializers.JobSerializer
    permission_codes_by_action = {
        "list": "job.view",
        "retrieve": "job.view",
        "create": "job.manage",
        "update": "job.manage",
        "partial_update": "job.manage",
        "destroy": "job.manage",
    }

    def get_queryset(self):
        qs = m.Job.objects.select_related("department").all().order_by("id")
        p = self.request.query_params
        is_active = bool_query_value(p.get("is_active"))
        if is_active is None:
            qs = qs.filter(is_active=True)
        else:
            qs = qs.filter(is_active=is_active)
        if p.get("entity"):
            qs = qs.filter(entity__icontains=p["entity"])
        if p.get("public_name"):
            qs = qs.filter(public_name__icontains=p["public_name"])
        if p.get("position_name"):
            qs = qs.filter(position_name__icontains=p["position_name"])
        if p.get("category"):
            qs = qs.filter(category__icontains=p["category"])
        if p.get("job_family"):
            qs = qs.filter(job_family__icontains=p["job_family"])
        if p.get("department_name"):
            qs = qs.filter(department__name__icontains=p["department_name"])
        if p.get("location"):
            qs = qs.filter(location__icontains=p["location"])
        if p.get("education"):
            qs = qs.filter(education__icontains=p["education"])
        if p.get("headcount"):
            qs = qs.filter(headcount=p["headcount"])
        is_public = bool_query_value(p.get("is_public"))
        if is_public is not None:
            qs = qs.filter(is_public=is_public)
        return qs

    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        job.is_active = False
        job.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class SchoolViewSet(PermissionedModelViewSet):
    serializer_class = serializers.SchoolSerializer
    permission_codes_by_action = {
        "list": "school.view",
        "retrieve": "school.view",
        "create": "school.manage",
        "update": "school.manage",
        "partial_update": "school.manage",
        "destroy": "school.manage",
    }

    def get_queryset(self):
        qs = m.School.objects.select_related("school_tag").order_by("name")
        p = self.request.query_params
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        if p.get("platform"):
            qs = qs.filter(
                Q(platform__icontains=p["platform"])
                | Q(school_tag__name__icontains=p["platform"])
                | Q(school_tag__code__icontains=p["platform"])
            )
        if p.get("province"):
            qs = qs.filter(province__icontains=p["province"])
        return qs


class SchoolTagViewSet(PermissionedModelViewSet):
    serializer_class = serializers.SchoolTagSerializer
    permission_code = "settings.manage_config"

    def get_queryset(self):
        qs = m.SchoolTag.objects.all().order_by("code", "id")
        p = self.request.query_params
        if p.get("code"):
            qs = qs.filter(code__icontains=p["code"])
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        is_active = bool_query_value(p.get("is_active"))
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs


class MajorCategoryViewSet(PermissionedModelViewSet):
    serializer_class = serializers.MajorCategorySerializer
    permission_code = "settings.manage_config"

    def get_queryset(self):
        qs = m.MajorCategory.objects.annotate(alias_count=Count("aliases")).order_by(
            "sort_order", "code", "id"
        )
        p = self.request.query_params
        if p.get("code"):
            qs = qs.filter(code__icontains=p["code"])
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        is_active = bool_query_value(p.get("is_active"))
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        try:
            self.perform_destroy(category)
        except ProtectedError:
            return Response(
                {"detail": "该专业大类仍有关联别名，需先删除或迁移别名后再删除。"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MajorAliasViewSet(PermissionedModelViewSet):
    serializer_class = serializers.MajorAliasSerializer
    permission_code = "settings.manage_config"

    def get_queryset(self):
        qs = m.MajorAlias.objects.select_related("category").order_by(
            "category__sort_order", "category__code", "name", "id"
        )
        p = self.request.query_params
        if p.get("category"):
            qs = qs.filter(category_id=p["category"])
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        if p.get("normalized_name"):
            qs = qs.filter(normalized_name__icontains=p["normalized_name"])
        if p.get("source"):
            qs = qs.filter(source=p["source"])
        if p.get("match_type"):
            qs = qs.filter(match_type=p["match_type"])
        is_active = bool_query_value(p.get("is_active"))
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs


class DepartmentViewSet(PermissionedModelViewSet):
    serializer_class = serializers.DepartmentSerializer
    permission_codes_by_action = {
        "list": "department.view",
        "retrieve": "department.view",
        "create": "department.manage",
        "update": "department.manage",
        "partial_update": "department.manage",
        "destroy": "department.manage",
    }

    def get_queryset(self):
        qs = m.Department.objects.all().order_by("id")
        p = self.request.query_params
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        return qs


class ContactViewSet(PermissionedModelViewSet):
    serializer_class = serializers.ContactSerializer
    permission_codes_by_action = {
        "list": "department.view",
        "retrieve": "department.view",
        "create": "department.manage",
        "update": "department.manage",
        "partial_update": "department.manage",
        "destroy": "department.manage",
    }

    def get_queryset(self):
        qs = m.Contact.objects.select_related("department").order_by("id")
        p = self.request.query_params
        is_active = bool_query_value(p.get("is_active"))
        if is_active is None:
            qs = qs.filter(is_active=True)
        else:
            qs = qs.filter(is_active=is_active)
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        if p.get("employee_no"):
            qs = qs.filter(employee_no__icontains=p["employee_no"])
        if p.get("department_name"):
            qs = qs.filter(department__name__icontains=p["department_name"])
        if p.get("department_level"):
            qs = qs.filter(department__level=p["department_level"])
        if p.get("contact_level"):
            qs = qs.filter(contact_level=p["contact_level"])
        if p.get("department"):
            qs = qs.filter(department_id=p["department"])
        if p.get("parent_department"):
            qs = qs.filter(department__parent_id=p["parent_department"])
        can_delegate = bool_query_value(p.get("can_delegate"))
        if can_delegate is not None:
            qs = qs.filter(can_delegate=can_delegate)
        if p.get("entity"):
            qs = qs.filter(department__entity__icontains=p["entity"])
        return qs

    def destroy(self, request, *args, **kwargs):
        contact = self.get_object()
        delete_contact_and_bound_users(contact)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SchoolTagRuleViewSet(PermissionedModelViewSet):
    serializer_class = serializers.SchoolTagRuleSerializer
    permission_code = "settings.manage_config"

    def get_queryset(self):
        qs = m.SchoolTagRule.objects.prefetch_related(
            "tag_links__school_tag"
        ).order_by("priority", "id")
        p = self.request.query_params
        if p.get("is_active") in ["true", "false"]:
            qs = qs.filter(is_active=p["is_active"] == "true")
        return qs


class CandidateWorkflowViewSet(PermissionedReadOnlyModelViewSet):
    serializer_class = serializers.CandidateWorkflowSerializer
    permission_code = "attempt.view_all"

    def get_queryset(self):
        qs = m.CandidateWorkflow.objects.select_related(
            "candidate", "current_resume", "passed_attempt__resume"
        ).order_by("-updated_at")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("search"):
            qs = qs.filter(
                Q(candidate__name__icontains=p["search"])
                | Q(candidate__phone__icontains=p["search"])
            )
        if p.get("current_position_name"):
            qs = qs.filter(current_resume__position_name__icontains=p["current_position_name"])
        if p.get("archive_reason"):
            qs = qs.filter(
                Q(archive_reason__icontains=p["archive_reason"])
                | Q(archive_detail__icontains=p["archive_reason"])
            )
        return qs.distinct()


class AssignmentAttemptViewSet(PermissionedReadOnlyModelViewSet):
    serializer_class = serializers.AssignmentAttemptSerializer
    permission_codes_by_action = {
        "list": None,
        "retrieve": None,
        "dispatch_welink": "attempt.dispatch",
        "bulk_dispatch": "attempt.dispatch",
        "assign_sub_contact": "attempt.assign_sub_contact",
        "confirm_review": "attempt.dispatch",
        "cancel_attempt": "attempt.dispatch",
        "cancel_review": "attempt.dispatch",
        "transfer_to_manual": "resume.manual_assign",
        "feedback": "attempt.feedback",
        "export_resumes": "attempt.export",
        "resume_preview": "attempt.export",
    }

    def get_queryset(self):
        qs = m.AssignmentAttempt.objects.select_related(
            "workflow__candidate",
            "resume__candidate",
            "department",
            "contact",
            "sub_department",
            "sub_contact",
            "matched_rule",
            "agent_decision",
        ).order_by("-created_at")
        permissions = user_permission_codes(self.request.user)
        contact_id = getattr(self.request.user, "contact_id", None)
        if "attempt.view_all" not in permissions:
            scope = Q(pk__in=[])
            if contact_id and "attempt.view_received" in permissions:
                scope |= Q(
                    contact_id=contact_id,
                    status__in=[
                        m.AssignmentAttempt.STATUS_DISPATCHED_L2,
                        m.AssignmentAttempt.STATUS_ASSIGNED_L3,
                        m.AssignmentAttempt.STATUS_PASSED,
                        m.AssignmentAttempt.STATUS_REJECTED,
                    ],
                )
            if contact_id and "attempt.view_assigned" in permissions:
                scope |= Q(sub_contact_id=contact_id)
            qs = qs.filter(scope)
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("source"):
            qs = qs.filter(source=p["source"])
        if p.get("contact"):
            qs = qs.filter(contact_id=p["contact"])
        if p.get("sub_contact"):
            qs = qs.filter(sub_contact_id=p["sub_contact"])
        if p.get("department"):
            qs = qs.filter(department_id=p["department"])
        return qs

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_welink(self, request, pk=None):
        attempt = self.get_object()
        try:
            attempt = allocate_service.dispatch_attempt(attempt, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "detail": "已通过 WeLink 下发",
                "attempt": serializers.AssignmentAttemptSerializer(attempt).data,
            }
        )

    @action(detail=False, methods=["post"], url_path="bulk-dispatch")
    def bulk_dispatch(self, request):
        """批量下发待下发尝试。

        body.ids 有值时只处理指定 ID；否则按当前筛选条件处理全部。
        只会下发 pending_dispatch，其他状态跳过。
        """
        ids = request.data.get("ids") or []
        if isinstance(ids, str):
            ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
        qs = self.get_queryset()
        if ids:
            qs = qs.filter(id__in=ids)
        total = qs.count()
        pending_qs = qs.filter(status=m.AssignmentAttempt.STATUS_PENDING_DISPATCH)
        dispatched = 0
        errors = []
        for attempt in pending_qs:
            try:
                allocate_service.dispatch_attempt(attempt, user=request.user)
                dispatched += 1
            except ValueError as exc:
                errors.append({"id": attempt.id, "detail": str(exc)})
        skipped = total - dispatched
        return Response(
            {
                "detail": f"已下发 {dispatched} 条，跳过 {skipped} 条",
                "total": total,
                "dispatched": dispatched,
                "skipped": skipped,
                "errors": errors,
            }
        )

    @action(detail=True, methods=["post"], url_path="assign-sub-contact")
    def assign_sub_contact(self, request, pk=None):
        attempt = self.get_object()
        sub_contact_id = (
            request.data.get("sub_contact_id")
            or request.data.get("sub_contact")
            or request.data.get("contact_id")
        )
        if not sub_contact_id:
            return Response(
                {"detail": "sub_contact_id 为必填项"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        sub_contact = m.Contact.objects.filter(pk=sub_contact_id).first()
        if not sub_contact:
            return Response(
                {"detail": "三级接口人不存在"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            attempt = allocate_service.assign_sub_contact(
                attempt,
                sub_contact,
                user=request.user,
                note=request.data.get("note", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.AssignmentAttemptSerializer(attempt).data)

    @action(detail=True, methods=["post"], url_path="confirm-review")
    def confirm_review(self, request, pk=None):
        attempt = self.get_object()
        try:
            attempt = allocate_service.confirm_review(attempt)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.AssignmentAttemptSerializer(attempt).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_attempt(self, request, pk=None):
        attempt = self.get_object()
        if attempt.status != m.AssignmentAttempt.STATUS_PENDING_DISPATCH:
            return Response(
                {"detail": "仅待下发尝试可以通过该接口取消"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            attempt = allocate_service.cancel_attempt(
                attempt, request.data.get("reason") or "hr_cancelled"
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.AssignmentAttemptSerializer(attempt).data)

    @action(detail=True, methods=["post"], url_path="cancel-review")
    def cancel_review(self, request, pk=None):
        attempt = self.get_object()
        if attempt.status != m.AssignmentAttempt.STATUS_PENDING_REVIEW:
            return Response(
                {"detail": "仅待复核 AI 尝试可以取消复核"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            attempt = allocate_service.cancel_attempt(
                attempt, request.data.get("reason") or "hr_cancelled_review"
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.AssignmentAttemptSerializer(attempt).data)

    @action(detail=True, methods=["post"], url_path="transfer-to-manual")
    def transfer_to_manual(self, request, pk=None):
        attempt = self.get_object()
        contact_id = request.data.get("contact_id")
        contact = m.Contact.objects.filter(pk=contact_id, is_active=True).first()
        if not contact:
            return Response({"detail": "目标接口人不存在或未启用"}, status=status.HTTP_400_BAD_REQUEST)
        secondary_contact = None
        if request.data.get("secondary_contact_id"):
            secondary_contact = m.Contact.objects.filter(
                pk=request.data["secondary_contact_id"], is_active=True
            ).first()
        try:
            manual_attempt = allocate_service.manual_assign(
                attempt.resume,
                contact,
                user=request.user,
                manual_reason=request.data.get("manual_reason") or "AI 复核转人工分配",
                secondary_contact=secondary_contact,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.AssignmentAttemptSerializer(manual_attempt).data)

    @action(detail=True, methods=["post"], url_path="feedback")
    def feedback(self, request, pk=None):
        attempt = self.get_object()
        result = request.data.get("result") or request.data.get("feedback_result")
        note = request.data.get("note") or request.data.get("feedback_note") or ""
        try:
            attempt = allocate_service.submit_feedback(attempt, result, note)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.AssignmentAttemptSerializer(attempt).data)

    @action(detail=False, methods=["get"], url_path="export")
    def export_resumes(self, request):
        """打包导出候选人简历文件为 zip。

        ?ids=1,2,3 导出指定分配尝试；不传则导出当前筛选（含 status）下全部。
        无简历文件的候选人记入 zip 内的「缺失简历文件清单.txt」。
        """
        qs = self.get_queryset()
        ids = request.query_params.get("ids")
        if ids:
            id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
            qs = qs.filter(id__in=id_list)

        resumes = [
            attempt.resume for attempt in qs.select_related("resume__candidate")
        ]
        return resume_zip_response(resumes)

    @action(detail=True, methods=["get"], url_path="resume-preview")
    def resume_preview(self, request, pk=None):
        attempt = self.get_object()
        return resume_preview_response(attempt.resume)


class AgentDispatchDecisionViewSet(PermissionedReadOnlyModelViewSet):
    serializer_class = serializers.AgentDispatchDecisionSerializer
    permission_codes_by_action = {
        "list": "attempt.view_all",
        "retrieve": "attempt.view_all",
        "retry": "attempt.dispatch",
    }

    def get_queryset(self):
        qs = m.AgentDispatchDecision.objects.select_related(
            "workflow__candidate",
            "resume",
            "processing_run",
            "evaluated_job",
            "recommended_job",
            "recommended_department",
            "recommended_contact",
        ).order_by("-created_at")
        p = self.request.query_params
        if p.get("recommendation"):
            qs = qs.filter(recommendation=p["recommendation"])
        if p.get("workflow"):
            qs = qs.filter(workflow_id=p["workflow"])
        return qs

    @action(detail=True, methods=["post"], url_path="retry")
    def retry(self, request, pk=None):
        decision = self.get_object()
        try:
            new_decision, attempt = allocate_service.retry_agent_decision(decision)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "detail": "已重新发起 AI 处理",
                "decision": serializers.AgentDispatchDecisionSerializer(new_decision).data,
                "attempt": (
                    serializers.AssignmentAttemptSerializer(attempt).data
                    if attempt
                    else None
                ),
            }
        )


class ProcessingRunViewSet(PermissionedReadOnlyModelViewSet):
    serializer_class = serializers.ProcessingRunSerializer
    permission_code = "pipeline.view"

    def get_queryset(self):
        qs = m.ProcessingRun.objects.select_related("created_by", "undone_by").prefetch_related("stages")
        if self.request.query_params.get("active") == "true":
            qs = qs.filter(status__in=["pending", "running", "waiting_conflict", "cancelling"])
        return qs

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        if not has_permission_code(request.user, "pipeline.run"):
            return Response({"detail": "无取消处理任务权限"}, status=status.HTTP_403_FORBIDDEN)
        try:
            run = cancellation.request_cancellation(pk, request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(serializers.ProcessingRunSerializer(run).data)


class PipelineRunView(APIView):
    """创建 ProcessingRun 并交给 Celery；eager 本地模式仍会立即完成。"""

    permission_classes = [HasPermissionCode]
    permission_code = "pipeline.run"

    def post(self, request):
        step = request.data.get("step", "all")
        modes = request.data.get("modes")
        if not isinstance(modes, list):
            return Response({"detail": "modes 必须是数组"}, status=status.HTTP_400_BAD_REQUEST)
        if not modes:
            return Response({"detail": "至少选择一种分配方式"}, status=status.HTTP_400_BAD_REQUEST)
        scope = request.data.get("scope") or {}
        try:
            runs = runner.create_runs(step, modes=modes, scope=scope, created_by=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        submit_processing_runs(runs)
        return Response(
            {"processing_runs": serializers.ProcessingRunSerializer(runs, many=True).data},
            status=(
                status.HTTP_202_ACCEPTED
                if any(run.status in ["pending", "running"] for run in runs)
                else status.HTTP_200_OK
            ),
        )


class UserViewSet(PermissionedModelViewSet):
    serializer_class = serializers.UserSerializer
    permission_code = "settings.manage_permissions"

    def get_queryset(self):
        qs = User.objects.select_related("contact").prefetch_related("groups").order_by("id")
        p = self.request.query_params
        if p.get("username"):
            qs = qs.filter(username__icontains=p["username"])
        if p.get("role"):
            qs = qs.filter(role=p["role"])
        if p.get("is_active") in ["true", "false"]:
            qs = qs.filter(is_active=p["is_active"] == "true")
        return qs

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        delete_user_and_bound_contact(user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleViewSet(PermissionedModelViewSet):
    queryset = Group.objects.prefetch_related("permissions").order_by("id")
    serializer_class = serializers.RoleSerializer
    permission_code = "settings.manage_permissions"


class PermissionTreeView(APIView):
    permission_classes = [HasPermissionCode]
    permission_code = "settings.manage_permissions"

    def get(self, request):
        return Response(PERMISSION_TREE)


class ConfigViewSet(viewsets.ViewSet):
    permission_classes = [HasPermissionCode]
    permission_code = "settings.manage_config"

    def _item_data(self, key):
        meta = CONFIG_REGISTRY[key]
        config = m.Config.objects.filter(key=key).first()
        value = config.value if config else meta["default"]
        return {"key": key, "value": value, **meta}

    def list(self, request):
        return Response([self._item_data(key) for key in CONFIG_REGISTRY])

    def retrieve(self, request, pk=None):
        if pk not in CONFIG_REGISTRY:
            return Response({"detail": "未知配置项"}, status=status.HTTP_404_NOT_FOUND)
        return Response(self._item_data(pk))

    def partial_update(self, request, pk=None):
        return self._save(request, pk)

    def update(self, request, pk=None):
        return self._save(request, pk)

    def _save(self, request, pk):
        if pk not in CONFIG_REGISTRY:
            return Response({"detail": "未知配置项"}, status=status.HTTP_404_NOT_FOUND)
        serializer = serializers.ConfigSerializer(
            data={**self._item_data(pk), "value": request.data.get("value")}
        )
        serializer.is_valid(raise_exception=True)
        value = serializer.validated_data["value"]
        meta = CONFIG_REGISTRY[pk]
        if meta.get("value_type") in ["number", "integer"]:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return Response({"detail": "配置值类型不正确"}, status=status.HTTP_400_BAD_REQUEST)
            if meta.get("value_type") == "integer" and not isinstance(value, int):
                return Response({"detail": "配置值必须是整数"}, status=status.HTTP_400_BAD_REQUEST)
            if (
                "min" in meta
                and value < meta["min"]
                or "max" in meta
                and value > meta["max"]
            ):
                return Response(
                    {"detail": f"配置值必须在 {meta.get('min')} 到 {meta.get('max')} 之间"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if pk == "ai_review_threshold":
            dispatch = ai_config._config_float("ai_dispatch_threshold")
            if float(value) > dispatch:
                return Response({"detail": "人工复核阈值不能高于自动下发阈值"}, status=status.HTTP_400_BAD_REQUEST)
        if pk == "ai_dispatch_threshold":
            review = ai_config._config_float("ai_review_threshold")
            if float(value) < review:
                return Response({"detail": "自动下发阈值不能低于人工复核阈值"}, status=status.HTTP_400_BAD_REQUEST)
        m.Config.objects.update_or_create(
            key=pk, defaults={"value": value}
        )
        return Response(self._item_data(pk))


class AIConnectionConfigView(APIView):
    """仅管理员可维护的模型连接配置；API Key 永不回传。"""

    permission_classes = [HasPermissionCode]
    permission_code = "settings.manage_permissions"

    def get(self, request):
        try:
            return Response(ai_config.get_ai_connection_status())
        except (RuntimeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        try:
            current = ai_config.get_ai_connection_status()
            payload = {
                "profile": request.data.get("profile", current["profile"]),
                "api_style": request.data.get("api_style", current["api_style"]),
                "model_name": request.data.get("model_name", current["model_name"]),
                "base_url": request.data.get("base_url", current["base_url"]),
                "api_key": request.data.get("api_key", ""),
                "clear_api_key": bool(request.data.get("clear_api_key", False)),
            }
            ai_config.save_ai_connection_config(payload)
            return Response(ai_config.get_ai_connection_status())
        except (RuntimeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class AIConnectionTestView(APIView):
    permission_classes = [HasPermissionCode]
    permission_code = "settings.manage_permissions"

    def post(self, request):
        try:
            result = ai_service.test_model_connection()
        except ai_service.AIServiceError as exc:
            return Response({"ok": False, "code": exc.code, "detail": exc.message})
        except (RuntimeError, ValueError) as exc:
            return Response({"ok": False, "code": "ai_not_configured", "detail": str(exc)})
        return Response({"ok": True, "detail": "模型连接测试成功", **result})
