"""Canonical scoring rubric — single source of truth (F08/F11).

Section list + tier ถูก FIX ไว้ตายตัว เพื่อให้ weighted-score denominator คงที่
ทุกครั้งที่ประเมิน -> คะแนนรวมทำซ้ำได้ วิเคราะห์ trend ได้ (deterministic).

Tier (ระดับความสำคัญของ section):
  Critical  = must-have — ขาดแล้วแพ้ (weight 3)
  Important = strong-have — ขาดแล้วเสีย parity (weight 2)
  Optional  = nice-to-have — มีก็ดี (weight 1)

Rubric v6 (2026-07-17) — tuned จาก back-test 3 proposal ดีล Acme Malaysia.
Critical เน้น "ความสามารถส่งมอบจริง": Pain, Hero Moat, และกลุ่ม implementation
(Solution Architecture + Delivery Narrative + Master Schedule).
Governance Fit + Post Go-Live Support (MA) = Important (long-term partnership
fit สไตล์ Japanese OEM). De-emphasize sales-narrative (The Ask, Differentiation).
  ประวัติ: v1 = ตัวหาร 36 (Critical: 4,5,6,10,12) → v4 = 34 → v5 = 35 →
  v6 = ตัวหาร 48 (tier v5 เดิม + weight 3/2/1 → 4/3/1 ใน scoring.TIER_WEIGHT).
  Critical: 4,6,7,8,9. scoring.map_verdict = 7/5/3.5 (ตั้งแต่ v4).

proposal_master_system.md ต้องอ้างอิงชุด section เดียวกันนี้ทุกประการ.
evaluation.py ใช้ normalize ผล LLM ให้ครบทุก section (section ที่ขาด = missing = 0).
"""
from __future__ import annotations

# (slide_section, tier) — ลำดับ + label + tier ต้องตรงกับ prompt เป๊ะ  (v5)
CANONICAL_SECTIONS: list[tuple[str, str]] = [
    ("1. Hero Cover", "Important"),
    ("2. Agenda", "Optional"),
    ("3. Client Context", "Important"),
    ("4. Pain Statement", "Critical"),
    ("5. Cost of Inaction", "Important"),
    ("6. Hero Moat (Track Record)", "Critical"),
    ("7. Solution Architecture", "Critical"),
    ("8. Delivery Narrative (3-Wave)", "Critical"),
    ("9. Master Schedule", "Critical"),
    ("10. Commercial Summary & TCO", "Important"),
    ("11. Differentiation Grid", "Optional"),
    ("12. The Ask & Next 30 Days", "Optional"),
    ("13. Named Team & Organization", "Optional"),
    ("14. Governance Fit", "Important"),
    ("15. Quality Management & Risk", "Important"),
    ("16. Post Go-Live Support (MA)", "Important"),
    ("17. Reference Case", "Important"),
]

SECTION_TIER: dict[str, str] = {name: tier for name, tier in CANONICAL_SECTIONS}
SECTION_ORDER: dict[str, int] = {name: i for i, (name, _) in enumerate(CANONICAL_SECTIONS)}
