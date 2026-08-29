"""Project content extraction (F30) — ดึง Price/Cost/Schedule/Manpower จาก proposal text.

เรียกหลังประเมินเสร็จ (fire-safe: ล้มเหลวไม่กระทบผลประเมิน — คืน None ให้กรอกมือ).
ใช้ Azure OpenAI deployment เดิม JSON mode เหมือน evaluation.py.
"""
from __future__ import annotations

import logging
import time

from . import llm
from .models import ProjectContentLLM

_MAX_RETRIES = 1
_TEMPERATURE = 0.0  # extraction เป็น fact-finding ไม่ต้องการ variance
_MAX_TOKENS = 2000  # G02 — price/cost/duration + milestones + manpower + confidence

_SYSTEM = (
    "You extract commercial/project data from a B2B proposal. Return JSON only:\n"
    "{\n"
    '  "price_amount": <number|null — total proposed price/contract value>,\n'
    '  "price_currency": "<THB|USD|MYR|...|null>",\n'
    '  "cost_amount": <number|null — internal cost/budget if explicitly stated>,\n'
    '  "cost_currency": "<currency|null>",\n'
    '  "duration_months": <number|null — total project duration in months>,\n'
    '  "milestones": [{"name": "<milestone>", "timeframe": "<e.g. Month 3, Q2>"}],\n'
    '  "manpower": [{"role": "<role>", "count": <int|null>, "man_days": <number|null>}],\n'
    '  "solution_type": "<short category e.g. ERP Implementation, AI/ML, Infrastructure, \'\' if unclear>",\n'
    '  "industry": "<client industry e.g. Automotive, Manufacturing, Banking, \'\' if unclear>",\n'
    '  "confidence": {"price": "high|medium|low", "cost": "...", "duration": "...", '
    '"milestones": "...", "manpower": "...", "solution_type": "...", "industry": "..."}\n'
    "}\n"
    "STRICT RULES: Never guess or infer numbers that are not stated in the text — use null. "
    "Convert duration to months (e.g. '24 weeks' -> 5.5). Amounts as plain numbers, no separators. "
    "If a price appears in multiple options/phases, use the total of the recommended option and set confidence medium."
)


def extract_project_content(text: str) -> ProjectContentLLM | None:
    """F30 — คืน None เมื่อ extract ไม่สำเร็จ (caller เก็บ record ว่างให้กรอกมือ)."""
    client, model = llm.client_and_model()
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = llm.chat(
                client,
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    # 24K chars ~ ครอบคลุมส่วน commercial/plan ของ proposal ส่วนใหญ่โดยไม่ชน TPM
                    {"role": "user", "content": text[:24000]},
                ],
                temperature=_TEMPERATURE,
                max_tokens=_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            return ProjectContentLLM.model_validate_json(
                llm.json_text(resp.choices[0].message.content or "{}"))
        except Exception as err:  # noqa: BLE001
            last_err = err
            if attempt < _MAX_RETRIES:
                is_rate = "429" in str(err) or "rate" in str(err).lower()
                time.sleep(8 if is_rate else 2)
    logging.warning("project content extraction failed: %s", last_err)
    return None
