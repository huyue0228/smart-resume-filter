from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import models as m
from apps.ingestion.sources import import_files
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
    queryset = m.Job.objects.select_related("department").all()
    serializer_class = serializers.JobSerializer


class SchoolViewSet(viewsets.ModelViewSet):
    queryset = m.School.objects.all()
    serializer_class = serializers.SchoolSerializer


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = m.Department.objects.all()
    serializer_class = serializers.DepartmentSerializer


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
