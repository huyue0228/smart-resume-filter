"""领域模型，对应《数据库设计》。所有数据同处一个池，按时间标签筛选，不分批次。"""
from django.db import models


class Department(models.Model):
    """部门（树形：一层 / 二层）。"""

    name = models.CharField(max_length=128)
    level = models.PositiveSmallIntegerField(default=2, help_text="1=一层, 2=二层")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    entity = models.CharField(max_length=64, blank=True, help_text="招聘主体")

    class Meta:
        unique_together = ("name", "parent")

    def __str__(self):
        return self.name


class Contact(models.Model):
    """部门接口人。"""

    name = models.CharField(max_length=64)
    employee_no = models.CharField(max_length=32, unique=True, help_text="工号")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="contacts"
    )

    def __str__(self):
        return f"{self.name}({self.employee_no})"


class School(models.Model):
    """院校清单。"""

    name = models.CharField(max_length=128, unique=True, help_text="学校")
    platform = models.CharField(max_length=64, blank=True, help_text="平台标签")
    region = models.CharField(max_length=16, blank=True, help_text="南/北（户籍缺失兜底）")

    def __str__(self):
        return self.name


class Job(models.Model):
    """岗位需求（即校招岗位分类及专业要求 / 结构化需求表）。"""

    entity = models.CharField(max_length=64, blank=True, help_text="主体")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    category = models.CharField(max_length=64, blank=True, help_text="岗位类别")
    public_name = models.CharField(max_length=128, blank=True, help_text="对外发布名称")
    is_public = models.BooleanField(default=True, help_text="是否对外发布")
    position_name = models.CharField(max_length=128, blank=True, help_text="职位名称")
    job_family = models.CharField(max_length=64, blank=True, help_text="岗位族")
    location = models.CharField(max_length=64, blank=True, help_text="工作地点")
    education = models.CharField(max_length=32, blank=True, help_text="学历要求")
    headcount = models.PositiveIntegerField(default=0, help_text="需求数量(HC)")

    def __str__(self):
        return self.public_name or self.position_name or f"Job#{self.pk}"


class JobMajor(models.Model):
    """岗位需求专业（多值）。"""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="majors")
    major = models.CharField(max_length=64)

    def __str__(self):
        return self.major


class Candidate(models.Model):
    """同学 / 人。以 identity_hash(规范化姓名+手机号) 全局唯一标识。"""

    identity_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    phone = models.CharField(max_length=32, blank=True)
    gender = models.CharField(max_length=8, blank=True)
    household_province = models.CharField(max_length=32, blank=True, help_text="户口所在地")
    first_degree_school = models.CharField(max_length=128, blank=True)
    highest_degree_school = models.CharField(max_length=128, blank=True)
    highest_major = models.CharField(max_length=128, blank=True)
    # Step3 院校分类结果
    first_degree_platform = models.CharField(max_length=64, blank=True)
    highest_degree_platform = models.CharField(max_length=64, blank=True)
    is_target_school = models.BooleanField(default=False)

    imported_at = models.DateTimeField(auto_now_add=True, help_text="导入时间（时间标签）")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Resume(models.Model):
    """投递 / 应聘记录。以应聘ID 全局唯一。"""

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="resumes")
    apply_id = models.CharField(max_length=64, unique=True, help_text="应聘ID")
    resume_file = models.CharField(max_length=256, blank=True, help_text="简历包文件名")
    entity = models.CharField(max_length=64, blank=True, help_text="招聘主体")
    org = models.CharField(max_length=128, blank=True, help_text="所属机构")
    position_name = models.CharField(max_length=128, blank=True, help_text="对外职位名称")
    status = models.CharField(max_length=32, blank=True, default="待处理", help_text="应聘状态")
    apply_date = models.DateField(null=True, blank=True, help_text="应聘日期")
    # Step1 查重与志愿排序
    volunteer_rank = models.PositiveSmallIntegerField(null=True, blank=True, help_text="志愿次序 1-4")
    assigned_entity = models.CharField(max_length=16, blank=True, help_text="分配主体 GW/YLS")
    # Step2 岗位分类
    job = models.ForeignKey(
        Job, null=True, blank=True, on_delete=models.SET_NULL, related_name="resumes"
    )
    job_category = models.CharField(max_length=64, blank=True, help_text="岗位类别标签")
    category_mode = models.CharField(max_length=8, blank=True, help_text="rule/ai")
    category_reason = models.TextField(blank=True, help_text="AI 模式可解释理由")

    imported_at = models.DateTimeField(auto_now_add=True, help_text="导入时间（时间标签）")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.candidate.name}-{self.position_name}"


class Allocation(models.Model):
    """Step5 分配结果。"""

    STATUS_PENDING = "待下发"
    STATUS_DISPATCHED = "已下发"
    STATUS_CLAIMED = "已领取"

    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, related_name="allocations")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL)
    contact = models.ForeignKey(Contact, null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.CharField(max_length=64, blank=True, help_text="分配理由")
    match_mode = models.CharField(max_length=8, blank=True, help_text="rule/ai")
    status = models.CharField(max_length=16, default=STATUS_PENDING)
    claimed_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Allocation#{self.pk} {self.status}"


class ProcessingRun(models.Model):
    """流水线处理任务记录（Celery 跟踪）。"""

    scope = models.JSONField(default=dict, blank=True, help_text="处理范围/筛选条件")
    step = models.CharField(max_length=16)
    mode = models.CharField(max_length=8, default="rule")
    status = models.CharField(max_length=16, default="pending")
    celery_task_id = models.CharField(max_length=64, blank=True)
    params = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class Config(models.Model):
    """键值配置（如分配倍数）。"""

    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(default=dict)

    def __str__(self):
        return self.key


class ProvinceRegion(models.Model):
    """省份南北字典。"""

    province = models.CharField(max_length=32, primary_key=True)
    region = models.CharField(max_length=8, help_text="南/北")

    def __str__(self):
        return f"{self.province}-{self.region}"
