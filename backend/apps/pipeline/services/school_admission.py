"""院校标签准入判断。

Rule 和 AI 分配共用同一套硬规则：存在启用规则时，候选人的第一学历
标签和最高学历标签必须同时命中同一条规则；没有启用规则时，该条件通过。
"""
from dataclasses import dataclass
from typing import Optional

from apps.core import models as m


@dataclass(frozen=True)
class SchoolAdmissionResult:
    passed: bool
    matched_rule: Optional[m.SchoolTagRule]
    has_active_rules: bool


def active_rules():
    return list(
        m.SchoolTagRule.objects.filter(is_active=True)
        .prefetch_related("tag_links__school_tag")
        .order_by("priority", "id")
    )


def rule_matches_candidate(candidate, rule):
    first_tag_ids = set()
    highest_tag_ids = set()
    for link in rule.tag_links.all():
        if link.degree_type == m.SchoolTagRuleTag.DEGREE_FIRST:
            first_tag_ids.add(link.school_tag_id)
        elif link.degree_type == m.SchoolTagRuleTag.DEGREE_HIGHEST:
            highest_tag_ids.add(link.school_tag_id)
    return (
        candidate.first_degree_tag_id in first_tag_ids
        and candidate.highest_degree_tag_id in highest_tag_ids
    )


def evaluate(candidate, rules=None):
    rules = active_rules() if rules is None else list(rules)
    if not rules:
        return SchoolAdmissionResult(
            passed=True,
            matched_rule=None,
            has_active_rules=False,
        )
    for rule in rules:
        if rule_matches_candidate(candidate, rule):
            return SchoolAdmissionResult(
                passed=True,
                matched_rule=rule,
                has_active_rules=True,
            )
    return SchoolAdmissionResult(
        passed=False,
        matched_rule=None,
        has_active_rules=True,
    )
