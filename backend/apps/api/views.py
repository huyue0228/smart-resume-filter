import io
import os
import zipfile

from django.conf import settings
from django.http import HttpResponse
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import models as m
from apps.ingestion import snapshot
from apps.ingestion.sources import RESUME_SUBDIR, import_files
from apps.pipeline import runner
from apps.pipeline.services import allocate as allocate_service

from . import serializers


class ImportView(APIView):
    """数据导入：multipart 上传 4 张表 + 简历包。"""

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
        return Response(
            {
                "detail": "导入完成",
                "counts": counts,
                "undo_available": takes_resume,
            }
        )


class ImportUndoView(APIView):
    """单级撤销最近一次简历上传（含其处理结果）。"""

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


class ResumeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = serializers.ResumeListSerializer

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

    @action(detail=True, methods=["post"], url_path="manual-assign")
    def manual_assign(self, request, pk=None):
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
            attempt = allocate_service.manual_assign(
                resume,
                contact,
                user=request.user,
                manual_reason=request.data.get("manual_reason", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializers.AssignmentAttemptSerializer(attempt).data)


class CandidateViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.CandidateSerializer

    def get_queryset(self):
        qs = (
            m.Candidate.objects.prefetch_related(
                "resumes",
                "workflow__attempts__resume",
                "workflow__attempts__contact",
                "workflow__attempts__sub_contact",
                "workflow__attempts__department",
                "workflow__attempts__sub_department",
            )
            .select_related("workflow__current_resume")
            .order_by("-updated_at")
        )
        p = self.request.query_params
        search = p.get("search")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(resumes__apply_id__icontains=search)
                | Q(resumes__position_name__icontains=search)
            )
        status_filter = p.get("status")
        if status_filter:
            if status_filter == m.CandidateWorkflow.STATUS_PENDING:
                qs = qs.filter(
                    Q(workflow__status=m.CandidateWorkflow.STATUS_PENDING)
                    | Q(workflow__isnull=True)
                )
            else:
                qs = qs.filter(workflow__status=status_filter)
        if p.get("imported_after"):
            qs = qs.filter(imported_at__date__gte=p["imported_after"])
        if p.get("imported_before"):
            qs = qs.filter(imported_at__date__lte=p["imported_before"])
        return qs.distinct()


class JobViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.JobSerializer

    def get_queryset(self):
        qs = m.Job.objects.select_related("department").all().order_by("id")
        p = self.request.query_params
        if p.get("public_name"):
            qs = qs.filter(public_name__icontains=p["public_name"])
        if p.get("category"):
            qs = qs.filter(category__icontains=p["category"])
        return qs


class SchoolViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SchoolSerializer

    def get_queryset(self):
        qs = m.School.objects.all().order_by("name")
        p = self.request.query_params
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        if p.get("platform"):
            qs = qs.filter(platform__icontains=p["platform"])
        return qs


class DepartmentViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.DepartmentSerializer

    def get_queryset(self):
        qs = m.Department.objects.all().order_by("id")
        p = self.request.query_params
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        return qs


class ContactViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.ContactSerializer

    def get_queryset(self):
        qs = m.Contact.objects.select_related("department").order_by("id")
        p = self.request.query_params
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"])
        if p.get("employee_no"):
            qs = qs.filter(employee_no__icontains=p["employee_no"])
        if p.get("department_name"):
            qs = qs.filter(department__name__icontains=p["department_name"])
        if p.get("contact_level"):
            qs = qs.filter(contact_level=p["contact_level"])
        if p.get("department"):
            qs = qs.filter(department_id=p["department"])
        if p.get("parent_department"):
            qs = qs.filter(department__parent_id=p["parent_department"])
        if p.get("is_active") in ["true", "false"]:
            qs = qs.filter(is_active=p["is_active"] == "true")
        return qs


class SchoolTagRuleViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SchoolTagRuleSerializer

    def get_queryset(self):
        qs = m.SchoolTagRule.objects.all().order_by("priority", "id")
        p = self.request.query_params
        if p.get("is_active") in ["true", "false"]:
            qs = qs.filter(is_active=p["is_active"] == "true")
        return qs


class CandidateWorkflowViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = serializers.CandidateWorkflowSerializer

    def get_queryset(self):
        qs = m.CandidateWorkflow.objects.select_related(
            "candidate", "current_resume", "passed_attempt"
        ).order_by("-updated_at")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("search"):
            qs = qs.filter(candidate__name__icontains=p["search"]) | qs.filter(
                candidate__phone__icontains=p["search"]
            )
        return qs.distinct()


class AssignmentAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = serializers.AssignmentAttemptSerializer

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
        if p.get("demo_role") == "secondary_contact":
            contact = (
                m.Contact.objects.filter(
                    contact_level=m.Contact.LEVEL_SECONDARY, is_active=True
                )
                .order_by("id")
                .first()
            )
            qs = qs.filter(contact=contact) if contact else qs.none()
        if p.get("demo_role") == "tertiary_contact":
            contact = (
                m.Contact.objects.filter(
                    contact_level=m.Contact.LEVEL_TERTIARY, is_active=True
                )
                .order_by("id")
                .first()
            )
            qs = qs.filter(sub_contact=contact) if contact else qs.none()
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

        resume_dir = os.path.join(settings.MEDIA_ROOT, RESUME_SUBDIR)
        buf = io.BytesIO()
        added, missing = 0, []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for attempt in qs.select_related("resume__candidate"):
                resume = attempt.resume
                fname = resume.resume_file
                path = os.path.join(resume_dir, fname) if fname else ""
                if path and os.path.exists(path):
                    zf.write(path, arcname=fname)
                    added += 1
                else:
                    missing.append(f"{resume.candidate.name}（{resume.apply_id}）")
            if missing:
                zf.writestr(
                    "缺失简历文件清单.txt",
                    "以下候选人暂无简历文件（未上传简历包或未匹配）：\n"
                    + "\n".join(missing),
                )

        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = 'attachment; filename="resumes_export.zip"'
        resp["X-Export-Count"] = str(added)
        resp["X-Export-Missing"] = str(len(missing))
        return resp


class AgentDispatchDecisionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = serializers.AgentDispatchDecisionSerializer

    def get_queryset(self):
        qs = m.AgentDispatchDecision.objects.select_related(
            "workflow__candidate",
            "resume",
            "recommended_department",
            "recommended_contact",
        ).order_by("-created_at")
        p = self.request.query_params
        if p.get("recommendation"):
            qs = qs.filter(recommendation=p["recommendation"])
        if p.get("workflow"):
            qs = qs.filter(workflow_id=p["workflow"])
        return qs


class ProcessingRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = m.ProcessingRun.objects.all()
    serializer_class = serializers.ProcessingRunSerializer


class PipelineRunView(APIView):
    """触发流水线：单步或一键全流程（demo 同步执行）。"""

    def post(self, request):
        step = request.data.get("step", "all")
        mode = request.data.get("mode", "rule")
        run = runner.run_step(step, mode=mode)
        return Response(
            {
                "id": run.id,
                "step": run.step,
                "mode": run.mode,
                "status": run.status,
                "message": run.message,
            }
        )
