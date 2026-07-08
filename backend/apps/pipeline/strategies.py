"""筛选/匹配策略：规则 与 AI 走统一接口，可切换、互不耦合。"""


class RuleStrategy:
    """规则模式：按职位名称与岗位表精确 / 包含匹配，再校验需求专业。"""

    mode = "rule"

    def _normalized(self, value):
        return "".join((value or "").lower().split())

    def _major_match_reason(self, resume, job):
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

    def _classify_if_major_matched(self, resume, job):
        matched, reason = self._major_match_reason(resume, job)
        if not matched:
            return None
        return job, job.category or "未分类", reason

    def classify(self, resume, jobs):
        pos = (resume.position_name or "").strip()
        if pos:
            for job in jobs:
                if pos in (job.public_name, job.position_name):
                    result = self._classify_if_major_matched(resume, job)
                    if result:
                        return result
            for job in jobs:
                name = job.public_name or job.position_name
                if name and (name in pos or pos in name):
                    result = self._classify_if_major_matched(resume, job)
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
