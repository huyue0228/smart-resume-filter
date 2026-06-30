from django.contrib import admin

from . import models

for model in (
    models.Department,
    models.Contact,
    models.School,
    models.Job,
    models.JobMajor,
    models.Candidate,
    models.Resume,
    models.ResumeProfile,
    models.SchoolTagRule,
    models.CandidateWorkflow,
    models.AssignmentAttempt,
    models.AssignmentHandoff,
    models.AgentDispatchDecision,
    models.ProcessingRun,
    models.Config,
    models.ProvinceRegion,
    models.ImportSnapshot,
):
    admin.site.register(model)
