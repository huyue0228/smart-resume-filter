import io
import os
import zipfile

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import models as m
from apps.ingestion.sources import RESUME_SUBDIR, import_files
from apps.pipeline import runner

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
        try:
            counts = import_files(files, mode=mode)
        except Exception as exc:  # noqa: BLE001
            return Response(
                {"detail": f"导入失败: {exc}"}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response({"detail": "导入完成", "counts": counts})


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


class CandidateViewSet(viewsets.ModelViewSet):
    queryset = m.Candidate.objects.all().order_by("-imported_at")
    serializer_class = serializers.CandidateSerializer


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


class AllocationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = serializers.AllocationSerializer

    def get_queryset(self):
        qs = m.Allocation.objects.select_related(
            "resume__candidate", "department", "contact"
        ).order_by("-created_at")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("department"):
            qs = qs.filter(department_id=p["department"])
        return qs

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_welink(self, request, pk=None):
        alloc = self.get_object()
        alloc.status = m.Allocation.STATUS_DISPATCHED
        alloc.notified_at = timezone.now()
        alloc.save(update_fields=["status", "notified_at"])
        return Response({"detail": "已通过 WeLink 下发", "status": alloc.status})

    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        alloc = self.get_object()
        alloc.status = m.Allocation.STATUS_CLAIMED
        alloc.claimed_at = timezone.now()
        alloc.save(update_fields=["status", "claimed_at"])
        return Response({"detail": "已领取", "status": alloc.status})

    @action(detail=False, methods=["get"], url_path="export")
    def export_resumes(self, request):
        """打包导出候选人简历文件为 zip。

        ?ids=1,2,3 导出指定分配项；不传则导出当前筛选（含 status）下全部。
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
            for alloc in qs.select_related("resume__candidate"):
                resume = alloc.resume
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
