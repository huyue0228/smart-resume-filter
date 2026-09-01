"""OpenAI 结构化输出 schema；所有字段均由服务端再次校验。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExperienceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    period: str
    description: str
    evidence: str


class EducationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school_name: str = ""
    degree: str = ""
    major: str = ""
    period: str = ""
    evidence: str = ""


class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    major_match: float = Field(ge=0, le=1)
    skills_match: float = Field(ge=0, le=1)
    experience_evidence: float = Field(ge=0, le=1)
    job_requirement: float = Field(ge=0, le=1)
    resume_quality: float = Field(ge=0, le=1)


class ResumeProfileOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    major_direction: str
    educations: list[EducationItem] = Field(default_factory=list)
    projects: list[ExperienceItem]
    internships: list[ExperienceItem]
    skills: list[str]
    certificates: list[str]
    summary: str
    risk_flags: list[str]


class DispatchRecommendationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: Literal["dispatch", "review", "archive"]
    score_breakdown: ScoreBreakdown
    summary: str
    reason: str
    evidence: list[str]
    risks: list[str]
    ai_specialist_match: bool = False
    ai_specialist_confidence: float = Field(default=0, ge=0, le=1)
    ai_specialist_evidence: list[str] = Field(default_factory=list)


class ResumeScreeningOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ResumeProfileOutput
    decision: DispatchRecommendationOutput


class SchoolProvinceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    province: str = Field(default="", max_length=32)


class SchoolProvinceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schools: list[SchoolProvinceItem] = Field(max_length=50)
