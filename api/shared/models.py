"""Pydantic models — LLM JSON contract + API DTOs (F10).

The LLM (Azure OpenAI) is forced to return JSON matching EvaluationLLMOutput.
Weighted overall_score is NOT trusted from the LLM — it is recomputed in
scoring.py for determinism (F11).
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

Tier = Literal["Critical", "Important", "Optional"]
Verdict = Literal["Strong", "Adequate", "Weak", "Critical"]


class ScoreDetail(BaseModel):
    slide_section: str = Field(..., description="เช่น '4. Pain Statement'")
    tier: Tier
    # ไม่ผูก ge/le ที่นี่ตั้งใจ -> LLM ส่งค่านอกช่วง (เช่น 11) ไม่ทำให้ parse fail/retry
    # การ clamp 0-10 ทำที่ _normalize_to_rubric จุดเดียว (single enforcement point)
    score_1_10: int = Field(..., description="0-10; ค่านอกช่วงจะถูก clamp ตอน normalize")
    coverage: str = Field("", description="submitted proposal cover section นี้แค่ไหน")


class Recommendation(BaseModel):
    priority: Tier
    rec_text: str
    slide_ref: str = ""


class EvaluationLLMOutput(BaseModel):
    """Exact JSON contract that Azure OpenAI must return."""
    score_details: list[ScoreDetail]
    recommendations: list[Recommendation]
    skeleton_md: str = Field(..., description="Skeleton structure ที่แนะนำ (markdown)")
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    """What the API returns to the frontend."""
    eval_id: str
    submission_id: str
    overall_score: float
    verdict: Verdict
    score_details: list[ScoreDetail]
    recommendations: list[Recommendation]
    skeleton_md: str
    strengths: list[str]
    gaps: list[str]


class DetectedMeta(BaseModel):
    """ผล LLM detect ชื่อลูกค้า+โปรเจคจาก proposal (F20)."""
    client_name: str = ""
    project_name: str = ""


class GateResult(BaseModel):
    """ผล improvement-gate (F25) — เทียบว่าแก้ตามคำแนะนำก่อนหน้าไหม."""
    addressed_count: int = Field(..., description="จำนวนคำแนะนำที่ถูกแก้ในเวอร์ชันใหม่")
    addressed: list[str] = Field(default_factory=list, description="รายการคำแนะนำที่ถูกแก้")
    note: str = ""


class Milestone(BaseModel):
    name: str = ""
    timeframe: str = Field("", description="เช่น 'Month 3', 'Q2 2026', 'W1-W6'")


class ManpowerRow(BaseModel):
    role: str = ""
    count: int | None = None
    man_days: float | None = None


class ProjectContentLLM(BaseModel):
    """ผล extract project content จาก proposal (F30) — null/ว่าง = ไม่พบในไฟล์ ห้ามเดา.

    confidence ต่อ field: high|medium|low — ใช้ตัดสิน needs_manual ฝั่ง UI.
    """
    price_amount: float | None = None
    price_currency: str | None = None
    cost_amount: float | None = None
    cost_currency: str | None = None
    duration_months: float | None = None
    milestones: list[Milestone] = Field(default_factory=list)
    manpower: list[ManpowerRow] = Field(default_factory=list)
    solution_type: str = ""
    industry: str = ""
    confidence: dict[str, str] = Field(default_factory=dict)
