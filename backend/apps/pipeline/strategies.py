"""筛选/匹配策略：规则 与 AI 走统一接口，可切换、互不耦合。"""


class RuleStrategy:
    """规则模式：按职位名称与岗位表精确 / 包含匹配。"""

    mode = "rule"

    def classify(self, resume, jobs):
        pos = (resume.position_name or "").strip()
        if pos:
            for job in jobs:
                if pos in (job.public_name, job.position_name):
                    return job, job.category or "未分类", ""
            for job in jobs:
                name = job.public_name or job.position_name
                if name and (name in pos or pos in name):
                    return job, job.category or "未分类", ""
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
