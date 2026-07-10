"""OpenAI 结构化输出 schema；所有字段均由服务端再次校验。"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class EducationItem(BaseModel):
    school: str
    degree: str
    major: str
    period: str


class ExperienceItem(BaseModel):
    name: str
    role: str
    period: str
    description: str
    evidence: str


class ScoreBreakdown(BaseModel):
    major_match: float = Field(ge=0, le=1)
    skills_match: float = Field(ge=0, le=1)
    experience_evidence: float = Field(ge=0, le=1)
    job_requirement: float = Field(ge=0, le=1)
    department_certainty: float = Field(ge=0, le=1)
    resume_quality: float = Field(ge=0, le=1)


class ResumeProfileOutput(BaseModel):
    education: list[EducationItem]
    major_direction: str
    projects: list[ExperienceItem]
    internships: list[ExperienceItem]
    skills: list[str]
    certificates: list[str]
    summary: str
    risk_flags: list[str]


class DispatchRecommendationOutput(BaseModel):
    recommendation: Literal["dispatch", "review", "archive"]
    job_id: Optional[int]
    department_id: Optional[int]
    contact_id: Optional[int]
    score_breakdown: ScoreBreakdown
    summary: str
    reason: str
    evidence: list[str]
    risks: list[str]


class ResumeScreeningOutput(BaseModel):
    profile: ResumeProfileOutput
    decision: DispatchRecommendationOutput
