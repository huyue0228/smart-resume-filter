"""筛选/匹配策略：规则 与 AI 走统一接口，可切换、互不耦合。"""

from apps.core import models as m


class RuleStrategy:
    """规则模式：按岗位名称命中岗位需求，并执行确定性专业校验。

    Rule 策略仍然不做 AI 语义扩展，但会使用 HR 可维护的专业大类词表做
    第一层确定性归类：候选人最高学历专业和岗位需求专业映射到同一启用
    大类时放行；词表不能证明通过时，再退回专业名双向包含兜底。返回的
    reason 会进入 Resume.category_reason，并被分配尝试的 match_reason
    复用，方便 HR 追溯为什么命中某个岗位。
    """

    mode = "rule"
    WILDCARD_MAJORS = {"专业不限", "不限", "不限专业"}

    def __init__(self):
        self._major_alias_cache = None

    def _normalized(self, value):
        """统一文本比较口径：忽略大小写和空白，但保留原始语义。"""
        return "".join((value or "").lower().split())

    def _is_wildcard_major(self, value):
        """判断岗位需求专业是否表达“专业不限”。

        “相关专业”不属于这里的通配词，它只会作为可维护别名参与词表匹配；
        默认停用的 OTHER_GENERAL 不会让它自动放行。
        """
        return self._normalized(value) in {
            self._normalized(item) for item in self.WILDCARD_MAJORS
        }

    def _major_categories_for_text(self, value):
        """把一个专业文本解析为启用的专业大类列表。

        匹配过程只读取启用别名和启用大类：
        - exact：规范化文本完全一致。
        - contains：别名与输入专业允许双向包含，兼容“计算机类”和
          “计算机科学与技术”这类粒度不同的表达。

        这里故意不把未命中的文本归到“其他”，因为“其他/相关专业”过宽，
        一旦默认参与分配就会造成误放行。
        """
        normalized_value = self._normalized(value)
        if not normalized_value:
            return []
        if self._major_alias_cache is None:
            self._major_alias_cache = list(
                m.MajorAlias.objects.select_related("category")
                .filter(is_active=True, category__is_active=True)
                .order_by("category__sort_order", "category__code", "id")
            )
        categories = []
        seen = set()
        for alias in self._major_alias_cache:
            alias_name = alias.normalized_name or self._normalized(alias.name)
            if not alias_name:
                continue
            if alias.match_type == m.MajorAlias.MATCH_EXACT:
                matched = alias_name == normalized_value
            else:
                matched = alias_name in normalized_value or normalized_value in alias_name
            if matched and alias.category_id not in seen:
                seen.add(alias.category_id)
                categories.append(alias.category)
        return categories

    def _major_category_match_reason(self, candidate_major, required_major):
        """返回专业大类命中原因；未命中时返回空字符串。

        候选人专业和岗位需求专业都必须能映射到启用大类，且大类存在交集，
        才能用词表直接判定通过。若任一侧没映射、或映射后没有交集，调用方
        会继续执行专业名包含兜底。
        """
        candidate_categories = self._major_categories_for_text(candidate_major)
        required_categories = self._major_categories_for_text(required_major)
        required_ids = {category.id for category in required_categories}
        matched_categories = [
            category for category in candidate_categories if category.id in required_ids
        ]
        if not matched_categories:
            return ""
        names = "、".join(category.name for category in matched_categories)
        return f"专业大类匹配：{candidate_major} 与 {required_major} 同属 {names}"

    def _major_match_reason(self, resume, job):
        """校验候选人最高学历专业是否满足岗位需求专业。

        判断顺序与设计文档一致：
        1. 岗位没有维护需求专业时放行，避免历史岗位需求数据被误拦截。
        2. 需求专业是“专业不限 / 不限 / 不限专业”时放行。
        3. 有非通配需求专业时，候选人最高学历专业缺失不自动放行。
        4. 先用启用专业词表匹配大类；大类能证明同类时放行。
        5. 词表无交集或任一侧未映射时，保留原专业名双向包含兜底。
        """
        required_majors = [major.major for major in job.majors.all() if major.major]
        if not required_majors:
            return True, "岗位未配置需求专业，放行"
        if any(self._is_wildcard_major(major) for major in required_majors):
            return True, "岗位需求专业为不限，放行"

        candidate_major_text = resume.candidate.highest_major or ""
        candidate_major = self._normalized(candidate_major_text)
        if not candidate_major:
            return False, "候选人最高学历专业缺失，未命中岗位需求专业"
        for required_major in required_majors:
            category_reason = self._major_category_match_reason(
                candidate_major_text, required_major
            )
            if category_reason:
                return True, category_reason

            normalized_required = self._normalized(required_major)
            if normalized_required and (
                normalized_required in candidate_major
                or candidate_major in normalized_required
            ):
                return (
                    True,
                    f"专业匹配（名称兜底）：{candidate_major_text} 命中 {required_major}",
                )
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

    def match_current_volunteer_job(self, resume, jobs):
        """从已按当前志愿定向查询的岗位中稳定选择唯一岗位，不校验专业。"""
        pos = (resume.position_name or "").strip()
        if not pos:
            return None
        candidates = self._candidate_jobs(resume, jobs, pos)
        return candidates[0][1] if candidates else None

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


def get_rule_strategy():
    return RuleStrategy()
