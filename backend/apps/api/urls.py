from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("resumes", views.ResumeViewSet, basename="resume")
router.register("candidates", views.CandidateViewSet, basename="candidate")
router.register("jobs", views.JobViewSet, basename="job")
router.register("schools", views.SchoolViewSet, basename="school")
router.register("departments", views.DepartmentViewSet, basename="department")
router.register("contacts", views.ContactViewSet, basename="contact")
router.register("school-tag-rules", views.SchoolTagRuleViewSet, basename="schooltagrule")
router.register("workflows", views.CandidateWorkflowViewSet, basename="workflow")
router.register(
    "workflow-attempts", views.AssignmentAttemptViewSet, basename="workflowattempt"
)
router.register(
    "agent-decisions", views.AgentDispatchDecisionViewSet, basename="agentdecision"
)
router.register("pipeline/runs", views.ProcessingRunViewSet, basename="processingrun")

urlpatterns = [
    path("import/", views.ImportView.as_view()),
    path("import/undo/", views.ImportUndoView.as_view()),
    path("pipeline/run/", views.PipelineRunView.as_view()),
    path("", include(router.urls)),
]
