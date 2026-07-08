"""筛选/匹配策略：规则 与 AI 走统一接口，可切换、互不耦合。"""


class RuleStrategy:
    """规则模式：按岗位名称命中岗位需求，并执行轻量专业校验。

    这里保持 Rule 策略的可审计性：不做 AI 语义扩展，也不引入专业大类
    映射；只使用投递主体、岗位名称和最高学历专业这些结构化字段做确定性
    判断。返回的 reason 会进入 Resume.category_reason，并被分配尝试的
    match_reason 复用，方便 HR 追溯为什么命中某个岗位。
    """

    mode = "rule"

    def _normalized(self, value):
        """统一文本比较口径：忽略大小写和空白，但保留原始语义。"""
        return "".join((value or "").lower().split())

    def _major_match_reason(self, resume, job):
        """校验候选人最高学历专业是否满足岗位需求专业。

        当前规则只做轻量包含匹配：
        - 岗位没有维护需求专业时放行，避免历史岗位需求数据被误拦截。
        - 岗位维护了需求专业时，候选人最高学历专业必须与任一需求专业
          双向包含命中，例如“计算机科学与技术”可命中“计算机”。
        - 不在这里做“专业大类/相近专业”扩展，后续如要增强应另建映射表。
        """
        required_majors = [major.major for major in job.majors.all() if major.major]
        if not required_majors:
            return True, "岗位未配置需求专业，放行"
        candidate_major = self._normalized(resume.candidate.highest_major)
        if not candidate_major:
            return False, "候选人最高学历专业缺失，未命中岗位需求专业"
        for required_major in required_majors:
            normalized_required = self._normalized(required_major)
            if normalized_required and (
                normalized_required in candidate_major
                or candidate_major in normalized_required
            ):
                return True, f"专业匹配：{resume.candidate.highest_major} 命中 {required_major}"
        return False, "候选人最高学历专业未命中岗位需求专业"

    def _entity_matched(self, resume, job):
        """招聘主体硬约束。

        只有投递主体和岗位主体双方都有值时才强制一致；任一侧为空时放行，
        兼容历史样例数据和未维护主体的岗位需求。
        """
        resume_entity = self._normalized(resume.entity)
        job_entity = self._normalized(job.entity)
        return not resume_entity or not job_entity or resume_entity == job_entity

    def _entity_rank(self, resume, job):
        """多岗位命中时，同主体岗位优先于主体缺失岗位。"""
        resume_entity = self._normalized(resume.entity)
        job_entity = self._normalized(job.entity)
        if resume_entity and job_entity and resume_entity == job_entity:
            return 0
        return 1

    def _job_name_matches(self, pos, job):
        """返回岗位名命中的优先级和可展示原因。

        优先级从强到弱：
        1. 投递岗位精确命中岗位需求的对外发布名称。
        2. 投递岗位精确命中岗位需求的职位名称。
        3. 与对外发布名称存在包含关系。
        4. 与职位名称存在包含关系。
        这样可以避免多个岗位同时命中时依赖数据库自然顺序。
        """
        normalized_pos = self._normalized(pos)
        public_name = self._normalized(job.public_name)
        position_name = self._normalized(job.position_name)
        if public_name and normalized_pos == public_name:
            return 0, f"岗位名精确命中对外发布名称：{job.public_name}"
        if position_name and normalized_pos == position_name:
            return 1, f"岗位名精确命中职位名称：{job.position_name}"
        if public_name and (
            public_name in normalized_pos or normalized_pos in public_name
        ):
            return 2, f"岗位名包含命中对外发布名称：{job.public_name}"
        if position_name and (
            position_name in normalized_pos or normalized_pos in position_name
        ):
            return 3, f"岗位名包含命中职位名称：{job.position_name}"
        return None

    def _candidate_jobs(self, resume, jobs, pos):
        """收集并排序当前投递可尝试的岗位需求。

        排序键为 `(主体优先级, 岗位名命中优先级, job.id)`，最后用 job.id
        兜底，确保同一批数据重复运行时结果稳定。
        """
        candidates = []
        for job in jobs:
            if not self._entity_matched(resume, job):
                continue
            name_match = self._job_name_matches(pos, job)
            if not name_match:
                continue
            name_rank, name_reason = name_match
            candidates.append(
                (
                    (self._entity_rank(resume, job), name_rank, job.id or 0),
                    job,
                    name_reason,
                )
            )
        return sorted(candidates, key=lambda item: item[0])

    def _classify_if_major_matched(self, resume, job, name_reason):
        """岗位名命中后再校验专业，不通过则继续尝试下一个岗位。"""
        matched, reason = self._major_match_reason(resume, job)
        if not matched:
            return None
        return job, job.category or "未分类", f"{name_reason}；{reason}"

    def classify(self, resume, jobs):
        """为单条投递选择一个岗位需求。

        只返回第一条“主体/岗位名/专业”全部通过的岗位；如果某个岗位名命中
        但专业不匹配，会继续尝试下一条候选岗位，而不是立即判定投递失败。
        """
        pos = (resume.position_name or "").strip()
        if pos:
            for _rank, job, name_reason in self._candidate_jobs(resume, jobs, pos):
                result = self._classify_if_major_matched(resume, job, name_reason)
                if result:
                    return result
        return None, "未匹配", ""


class AIStrategy:
    """AI 模式（demo 占位）：当前回退规则结果并附说明；后续接 OpenAI 语义分类。"""

    mode = "ai"

    def __init__(self):
        self._rule = RuleStrategy()

    def classify(self, resume, jobs):
        job, category, _ = self._rule.classify(resume, jobs)
        reason = "AI(demo)：基于职位名称语义判断（当前回退规则匹配结果）"
        return job, category, reason


def get_strategy(mode):
    return AIStrategy() if mode == "ai" else RuleStrategy()
