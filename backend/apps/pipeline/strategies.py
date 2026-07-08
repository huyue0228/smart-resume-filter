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

    def _entity_matched(self, resume, job):
        resume_entity = self._normalized(resume.entity)
        job_entity = self._normalized(job.entity)
        return not resume_entity or not job_entity or resume_entity == job_entity

    def _entity_rank(self, resume, job):
        resume_entity = self._normalized(resume.entity)
        job_entity = self._normalized(job.entity)
        if resume_entity and job_entity and resume_entity == job_entity:
            return 0
        return 1

    def _job_name_matches(self, pos, job):
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
        matched, reason = self._major_match_reason(resume, job)
        if not matched:
            return None
        return job, job.category or "未分类", f"{name_reason}；{reason}"

    def classify(self, resume, jobs):
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
