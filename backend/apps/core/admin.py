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
    models.Allocation,
    models.ProcessingRun,
    models.Config,
    models.ProvinceRegion,
):
    admin.site.register(model)
