"""Deterministic scoring (F11/F12).

คะแนนรวมคำนวณที่นี่ ไม่ให้ GPT คำนวณ -> คงเส้นคงวา ทำซ้ำได้ วิเคราะห์ trend ได้
Weighted average: Critical x4, Important x3, Optional x1  (rubric v6, 2026-07-17)

Calibration (v7, 2026-07-17): raw weighted-average composite underestimates
เทียบ expert anchor (Boss ให้ VendorX 7-8 / VendorY 6.5-7.5 / CSI 6-7 — engine raw
ให้ 5.96 / 5.60 / 5.33; gap คงที่ ~1.3-1.5) → บวก CALIBRATION_OFFSET ที่ overall
จุดเดียว (ranking + section scores ดิบไม่แตะ — Boss เห็นด้วยกับ LLM ระดับ section).
ปรับค่า offset ที่ constant นี้จุดเดียว.
"""
from __future__ import annotations

from .models import ScoreDetail

TIER_WEIGHT = {"Critical": 4, "Important": 3, "Optional": 1}
CALIBRATION_OFFSET = 1.5   # ยกคะแนน overall ให้ตรง expert anchor; clamp เพดาน 10


def compute_overall_score(details: list[ScoreDetail]) -> float:
    """Weighted average ของ per-section score + calibration offset, clamp 0-10."""
    if not details:
        return 0.0
    weighted_sum = sum(d.score_1_10 * TIER_WEIGHT[d.tier] for d in details)
    weight_total = sum(TIER_WEIGHT[d.tier] for d in details)
    raw = weighted_sum / weight_total
    return min(10.0, round(raw + CALIBRATION_OFFSET, 2))


def map_verdict(overall: float) -> str:
    """คะแนน -> verdict label (v4 threshold — อ่อนลงจาก v1 8/6/4)."""
    if overall >= 7:
        return "Strong"
    if overall >= 5:
        return "Adequate"
    if overall >= 3.5:
        return "Weak"
    return "Critical"
