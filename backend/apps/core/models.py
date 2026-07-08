"""领域模型，对应《数据库设计》。所有数据同处一个池，按时间标签筛选，不分批次。"""
from django.conf import settings
from django.db import models


class Department(models.Model):
    """部门（树形：一层 / 二层 / 三级）。"""

    name = models.CharField(max_length=128)
    level = models.PositiveSmallIntegerField(default=2, help_text="1=一层, 2=二层, 3=三级")
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

    LEVEL_SECONDARY = "secondary"
    LEVEL_TERTIARY = "tertiary"
    LEVEL_CHOICES = [
        (LEVEL_SECONDARY, "二级接口人"),
        (LEVEL_TERTIARY, "三级接口人"),
    ]

    name = models.CharField(max_length=64)
    employee_no = models.CharField(max_length=32, unique=True, help_text="工号")
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="contacts"
    )
    contact_level = models.CharField(
        max_length=16, choices=LEVEL_CHOICES, default=LEVEL_SECONDARY
    )
    can_delegate = models.BooleanField(default=True, help_text="二级接口人是否可转派")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name}({self.employee_no})"


class SchoolTag(models.Model):
    """院校标签字典。"""

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code", "id"]
        indexes = [
            models.Index(fields=["code", "is_active"]),
            models.Index(fields=["is_default"]),
        ]

    def __str__(self):
        return self.name


class School(models.Model):
    """院校清单。"""

    name = models.CharField(max_length=128, unique=True, help_text="学校")
    platform = models.CharField(max_length=64, blank=True, help_text="平台标签")
    region = models.CharField(max_length=16, blank=True, help_text="南/北（户籍缺失兜底）")
    province = models.CharField(max_length=32, blank=True)
    school_tag = models.ForeignKey(
        SchoolTag,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="schools",
    )

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
    first_degree_tag = models.ForeignKey(
        SchoolTag,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="first_degree_candidates",
    )
    highest_degree_tag = models.ForeignKey(
        SchoolTag,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="highest_degree_candidates",
    )

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


class ResumeProfile(models.Model):
    """AI 策略读取简历后的结构化画像（demo 版可由元数据生成）。"""

    resume = models.OneToOneField(Resume, on_delete=models.CASCADE, related_name="profile")
    parsed_text = models.TextField(blank=True)
    projects = models.JSONField(default=list, blank=True)
    internships = models.JSONField(default=list, blank=True)
    skills = models.JSONField(default=list, blank=True)
    certificates = models.JSONField(default=list, blank=True)
    major_direction = models.CharField(max_length=128, blank=True)
    parse_status = models.CharField(max_length=32, default="pending")
    parse_error = models.TextField(blank=True)
    parsed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SchoolTagRule(models.Model):
    """院校标签准入规则。"""

    name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "id"]
        indexes = [
            models.Index(fields=["is_active", "priority"]),
        ]

    def __str__(self):
        return self.name


class SchoolTagRuleTag(models.Model):
    """院校准入规则标签明细。"""

    DEGREE_FIRST = "first"
    DEGREE_HIGHEST = "highest"
    DEGREE_CHOICES = [
        (DEGREE_FIRST, "第一学历"),
        (DEGREE_HIGHEST, "最高学历"),
    ]

    rule = models.ForeignKey(
        SchoolTagRule, on_delete=models.CASCADE, related_name="tag_links"
    )
    school_tag = models.ForeignKey(
        SchoolTag, on_delete=models.PROTECT, related_name="rule_links"
    )
    degree_type = models.CharField(max_length=16, choices=DEGREE_CHOICES)

    class Meta:
        unique_together = ("rule", "school_tag", "degree_type")
        indexes = [
            models.Index(fields=["rule", "degree_type"]),
            models.Index(fields=["school_tag", "degree_type"]),
        ]

    def __str__(self):
        return f"{self.rule}-{self.school_tag}-{self.degree_type}"


class CandidateWorkflow(models.Model):
    """候选人级分配流程。"""

    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_PASSED = "passed"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待分配"),
        (STATUS_IN_PROGRESS, "进行中"),
        (STATUS_PASSED, "已通过"),
        (STATUS_ARCHIVED, "已归档"),
    ]

    ARCHIVE_NO_ACTIVE_SCHOOL_RULE = "no_active_school_rule"
    ARCHIVE_SCHOOL_RULE_NOT_MATCHED = "school_rule_not_matched"
    ARCHIVE_NO_NEXT_RESUME = "no_next_resume"
    ARCHIVE_JOB_NOT_MATCHED = "job_not_matched"
    ARCHIVE_DEPARTMENT_NOT_FOUND = "department_not_found"
    ARCHIVE_CONTACT_NOT_FOUND = "contact_not_found"
    ARCHIVE_SUB_CONTACT_NOT_FOUND = "sub_contact_not_found"
    ARCHIVE_AGENT_NO_RECOMMENDATION = "agent_no_recommendation"
    ARCHIVE_ALL_REJECTED = "all_rejected"
    ARCHIVE_RERUN_PRESERVED = "rerun_preserved"
    ARCHIVE_REASON_CHOICES = [
        (ARCHIVE_NO_ACTIVE_SCHOOL_RULE, "没有启用院校标签准入规则"),
        (ARCHIVE_SCHOOL_RULE_NOT_MATCHED, "院校标签未命中规则"),
        (ARCHIVE_NO_NEXT_RESUME, "没有下一条可尝试志愿"),
        (ARCHIVE_JOB_NOT_MATCHED, "未匹配岗位"),
        (ARCHIVE_DEPARTMENT_NOT_FOUND, "无有效二层部门"),
        (ARCHIVE_CONTACT_NOT_FOUND, "无可用接口人"),
        (ARCHIVE_SUB_CONTACT_NOT_FOUND, "二级部门下没有可用三级接口人"),
        (ARCHIVE_AGENT_NO_RECOMMENDATION, "AI 无有效建议"),
        (ARCHIVE_ALL_REJECTED, "全部志愿未通过"),
        (ARCHIVE_RERUN_PRESERVED, "重跑时保留归档"),
    ]

    candidate = models.OneToOneField(
        Candidate, on_delete=models.CASCADE, related_name="workflow"
    )
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    current_resume = models.ForeignKey(
        Resume,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_workflows",
    )
    current_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    dispatch_strategy = models.CharField(max_length=16, default="rule")
    archive_reason = models.CharField(
        max_length=64, choices=ARCHIVE_REASON_CHOICES, blank=True
    )
    archive_detail = models.TextField(blank=True)
    passed_attempt = models.ForeignKey(
        "AssignmentAttempt",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="passed_workflows",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["updated_at"]),
        ]

    def __str__(self):
        return f"{self.candidate.name}-{self.status}"


class AssignmentAttempt(models.Model):
    """候选人分配流程中的一次分配尝试。"""

    SOURCE_RULE = "rule"
    SOURCE_AI = "ai"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_RULE, "规则分配"),
        (SOURCE_AI, "AI 分配"),
        (SOURCE_MANUAL, "手动强制分配"),
    ]

    STATUS_PENDING_DISPATCH = "pending_dispatch"
    STATUS_PENDING_REVIEW = "pending_review"
    STATUS_DISPATCHED_L2 = "dispatched_l2"
    STATUS_ASSIGNED_L3 = "assigned_l3"
    STATUS_PASSED = "passed"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING_DISPATCH, "待下发"),
        (STATUS_PENDING_REVIEW, "待 HR 复核"),
        (STATUS_DISPATCHED_L2, "已下发二级"),
        (STATUS_ASSIGNED_L3, "已转派三级"),
        (STATUS_PASSED, "已通过"),
        (STATUS_REJECTED, "未通过"),
        (STATUS_CANCELLED, "已取消"),
    ]

    FEEDBACK_PASSED = "passed"
    FEEDBACK_REJECTED = "rejected"
    FEEDBACK_CHOICES = [
        (FEEDBACK_PASSED, "通过"),
        (FEEDBACK_REJECTED, "未通过"),
    ]

    CANCEL_RERUN = "rerun"
    CANCEL_WORKFLOW_PASSED = "workflow_passed"
    CANCEL_MANUAL_REPLACED = "manual_replaced"

    workflow = models.ForeignKey(
        CandidateWorkflow, on_delete=models.CASCADE, related_name="attempts"
    )
    resume = models.ForeignKey(
        Resume, on_delete=models.PROTECT, related_name="assignment_attempts"
    )
    attempt_no = models.PositiveIntegerField()
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_RULE)
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING_DISPATCH
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assignment_attempts",
    )
    contact = models.ForeignKey(
        Contact, on_delete=models.PROTECT, related_name="assignment_attempts"
    )
    sub_department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sub_assignment_attempts",
    )
    sub_contact = models.ForeignKey(
        Contact,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sub_assignment_attempts",
    )
    matched_rule = models.ForeignKey(
        SchoolTagRule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assignment_attempts",
    )
    agent_decision = models.ForeignKey(
        "AgentDispatchDecision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assignment_attempts",
    )
    confidence_score = models.FloatField(null=True, blank=True)
    review_required = models.BooleanField(default=False)
    match_mode = models.CharField(max_length=8, blank=True, help_text="rule/ai")
    match_reason = models.TextField(blank=True)
    welink_message_id = models.CharField(max_length=128, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    assigned_to_sub_at = models.DateTimeField(null=True, blank=True)
    feedback_result = models.CharField(
        max_length=16, choices=FEEDBACK_CHOICES, blank=True
    )
    feedback_note = models.TextField(blank=True)
    feedback_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=64, blank=True)
    manual_reason = models.TextField(blank=True)
    department_name_snapshot = models.CharField(max_length=128, blank=True)
    contact_name_snapshot = models.CharField(max_length=64, blank=True)
    contact_employee_no_snapshot = models.CharField(max_length=32, blank=True)
    sub_department_name_snapshot = models.CharField(max_length=128, blank=True)
    sub_contact_name_snapshot = models.CharField(max_length=64, blank=True)
    sub_contact_employee_no_snapshot = models.CharField(max_length=32, blank=True)
    resume_apply_id_snapshot = models.CharField(max_length=64, blank=True)
    position_name_snapshot = models.CharField(max_length=128, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assignment_attempts_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("workflow", "attempt_no")
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["contact", "status"]),
            models.Index(fields=["sub_contact", "status"]),
            models.Index(fields=["workflow", "status"]),
            models.Index(fields=["source", "status"]),
        ]

    def __str__(self):
        return f"Attempt#{self.pk} {self.status}"


class AssignmentHandoff(models.Model):
    """分配下发/转派审计记录，当前状态仍以 AssignmentAttempt 字段为准。"""

    ACTION_HR_DISPATCH = "hr_dispatch"
    ACTION_SUB_ASSIGN = "sub_assign"
    ACTION_SUB_REASSIGN = "sub_reassign"
    ACTION_CHOICES = [
        (ACTION_HR_DISPATCH, "HR 下发二级"),
        (ACTION_SUB_ASSIGN, "二级转派三级"),
        (ACTION_SUB_REASSIGN, "二级改派三级"),
    ]

    attempt = models.ForeignKey(
        AssignmentAttempt, on_delete=models.CASCADE, related_name="handoffs"
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    from_contact = models.ForeignKey(
        Contact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="handoffs_from",
    )
    to_department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="handoffs_to",
    )
    to_contact = models.ForeignKey(
        Contact, on_delete=models.PROTECT, related_name="handoffs_to"
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assignment_handoffs_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["attempt", "created_at"])]


class AgentDispatchDecision(models.Model):
    """AI Agent 对某候选人某个志愿尝试的分流建议。"""

    RECOMMEND_DISPATCH = "dispatch"
    RECOMMEND_REVIEW = "review"
    RECOMMEND_ARCHIVE = "archive"
    RECOMMEND_CHOICES = [
        (RECOMMEND_DISPATCH, "建议下发"),
        (RECOMMEND_REVIEW, "人工复核"),
        (RECOMMEND_ARCHIVE, "建议归档"),
    ]

    workflow = models.ForeignKey(
        CandidateWorkflow, on_delete=models.CASCADE, related_name="agent_decisions"
    )
    resume = models.ForeignKey(
        Resume, on_delete=models.CASCADE, related_name="agent_decisions"
    )
    profile = models.ForeignKey(
        ResumeProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_decisions",
    )
    processing_run = models.ForeignKey(
        "ProcessingRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_decisions",
    )
    recommendation = models.CharField(
        max_length=16, choices=RECOMMEND_CHOICES, null=True, blank=True
    )
    evaluated_job = models.ForeignKey(
        Job,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_evaluations",
    )
    recommended_job = models.ForeignKey(
        Job,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_recommendations",
    )
    matched_job_category = models.CharField(max_length=64, blank=True)
    recommended_department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_decisions",
    )
    recommended_contact = models.ForeignKey(
        Contact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_decisions",
    )
    confidence_score = models.FloatField(null=True, blank=True)
    score_breakdown = models.JSONField(default=dict, blank=True)
    summary = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    evidence = models.JSONField(default=list, blank=True)
    risks = models.JSONField(default=list, blank=True)
    risk_flags = models.JSONField(default=list, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    model_name = models.CharField(max_length=64, blank=True)
    prompt_version = models.CharField(max_length=32, blank=True)
    decision_version = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["workflow", "created_at"]),
            models.Index(fields=["recommendation", "confidence_score"]),
        ]


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
    """键值配置。"""

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


class ImportSnapshot(models.Model):
    """单级撤销快照：每次上传简历前，序列化候选、投递和分配工作流。

    仅保留最近一份（单级撤销）。
    """

    created_at = models.DateTimeField(auto_now_add=True)
    label = models.CharField(max_length=128, blank=True)
    payload = models.TextField(help_text="django serialize 的 json")

    class Meta:
        ordering = ["-created_at"]
