"""Evaluation engine (F08/F09/F10) — port proposal-master -> Azure OpenAI.

- F08: ประกอบ system prompt (proposal-master Evaluation Mode) + proposal text
- F09: เรียก Azure OpenAI ใน JSON mode + retry
- F10: parse -> validate ด้วย Pydantic (EvaluationLLMOutput)

หมายเหตุ: overall_score คำนวณใน scoring.py ไม่ใช่ที่นี่ (deterministic).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from . import llm
from .models import DetectedMeta, EvaluationLLMOutput, GateResult, ScoreDetail
from .rubric import CANONICAL_SECTIONS, SECTION_ORDER

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "proposal_master_system.md"
_MAX_RETRIES = 2
_TEMPERATURE = 0.2  # ต่ำ -> ลด variance ให้ประเมิน consistent

# G02 — เพดาน output ต่อชนิดงาน. ไม่ตั้ง = ใช้ default ของ deployment ซึ่งอาจตัด JSON
# กลางประโยค -> parse fail -> retry ครบ 3 รอบโดยเปล่าประโยชน์ (เผาโทเคน + ช้า)
_MAX_TOKENS_EVAL = 12000   # 17 section + recommendations + skeleton markdown
_MAX_TOKENS_DETECT = 200   # {"client_name","project_name"} เท่านั้น
_MAX_TOKENS_GATE = 1000    # addressed_count + รายการที่ถูกแก้ + note สั้น


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def content_hash(text: str) -> str:
    """SHA-256 ของ normalized text (F24) — lower + collapse whitespace เพื่อกัน OCR noise เล็กน้อย."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _chat_json(system: str, user: str, force_azure: bool = False, max_tokens: int = _MAX_TOKENS_GATE) -> str:
    """เรียก LLM JSON mode 1 ครั้ง คืน raw JSON string.
    force_azure=True -> ใช้ Azure เสมอ (งานเบา sync ที่ต้องเร็ว เช่น detect ตอน prepare)."""
    client, model = llm.azure_client_and_model() if force_azure else llm.client_and_model()
    resp = llm.chat(
        client,
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=_TEMPERATURE,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or "{}"


_DETECT_SYSTEM = (
    "You extract metadata from a B2B proposal. Return JSON only: "
    '{"client_name": "<the customer/client company the proposal is FOR, "" if unknown>", '
    '"project_name": "<the project/engagement name, "" if unknown>"}. '
    # ⚠️ ต้องเป็น single-quoted: เขียน "…use "" when…" ใน double quote จะกลายเป็นการต่อสตริง
    # 3 ชิ้นโดยมีสตริงว่างตรงกลาง -> โทเคน "" หายจาก prompt (โมเดลไม่รู้ว่าให้ตอบอะไรเมื่อไม่ชัด)
    'Do not guess wildly; use "" when not clearly stated.'
)


def detect_metadata(text: str) -> DetectedMeta:
    """F20 — detect ชื่อลูกค้า+โปรเจคจากเนื้อหา proposal. ล้มเหลว -> คืนค่าว่าง (popup ให้กรอกเอง)."""
    try:
        return DetectedMeta.model_validate_json(llm.json_text(
            _chat_json(_DETECT_SYSTEM, text[:6000], force_azure=True, max_tokens=_MAX_TOKENS_DETECT)
        ))
    except Exception:  # noqa: BLE001
        return DetectedMeta()


_GATE_SYSTEM = (
    "You compare an OLD proposal version against a NEW one to decide whether the previously "
    "raised recommendations were addressed. Return JSON only: "
    '{"addressed_count": <int>, "addressed": ["<recommendation text that was addressed>"], '
    '"note": "<one short sentence>"}. '
    "Count a recommendation as addressed only if the NEW text shows a concrete, relevant change. "
    "If the NEW text is essentially the same w.r.t. the recommendations, addressed_count = 0."
)


def improvement_gate(prior_recommendations: list[str], old_text: str, new_text: str) -> GateResult:
    """F25 — เทียบว่าแก้ตามคำแนะนำก่อนหน้าไหม. ล้มเหลว/ไม่ชัด -> default re-eval (addressed_count=-1)."""
    recs = "\n".join(f"- {r}" for r in prior_recommendations) or "(none)"
    user = (
        f"PRIOR RECOMMENDATIONS:\n{recs}\n\n"
        f"=== OLD VERSION ===\n{old_text[:6000]}\n\n"
        f"=== NEW VERSION ===\n{new_text[:6000]}"
    )
    try:
        return GateResult.model_validate_json(llm.json_text(_chat_json(_GATE_SYSTEM, user)))
    except Exception as err:  # noqa: BLE001
        # ไม่ชัด -> ให้ re-evaluate (ปลอดภัยกว่า) ด้วย sentinel addressed_count = -1
        return GateResult(addressed_count=-1, addressed=[], note=f"gate error, default re-eval: {err}")


_LANG_NAME = {"th": "Thai (ภาษาไทย)", "en": "English"}


def _lang_directive(lang: str) -> str:
    name = _LANG_NAME.get(lang, "English")
    return (
        f"LANGUAGE: Write every human-readable text value — coverage, recommendations "
        f"rec_text, gaps, strengths, and skeleton_md — in {name}. "
        f"Keep slide_section labels, tier values, priority values, and all JSON keys "
        f"exactly as specified (English). "
    )


def _build_user_message(proposal_text: str, context: dict | None, lang: str) -> str:
    ctx = ""
    if context:
        ctx = "Project context provided by submitter:\n" + json.dumps(
            context, ensure_ascii=False, indent=2
        ) + "\n\n"
    return (
        f"{_lang_directive(lang)}\n\n{ctx}Evaluate the following submitted proposal against the "
        f"proposal-master skeleton. Return JSON only.\n\n"
        f"=== PROPOSAL TEXT START ===\n{proposal_text}\n=== PROPOSAL TEXT END ==="
    )


def _normalize_to_rubric(llm: EvaluationLLMOutput) -> EvaluationLLMOutput:
    """บังคับ score_details ให้ครบ 17 canonical section เสมอ (F11 determinism).

    - section ที่ LLM ส่งมา -> ใช้ score นั้น แต่ override tier ตาม rubric (กัน LLM เปลี่ยน tier)
    - section ที่ LLM ขาด -> เติมเป็น score 0 (missing) เพื่อให้ denominator คงที่
    - section แปลกปลอมที่ไม่อยู่ใน rubric -> ตัดทิ้ง
    ผลลัพธ์: weighted denominator เท่ากันทุกครั้ง -> คะแนนรวมทำซ้ำได้
    """
    by_name: dict[str, ScoreDetail] = {d.slide_section: d for d in llm.score_details}
    normalized: list[ScoreDetail] = []
    for name, tier in CANONICAL_SECTIONS:
        found = by_name.get(name)
        if found is not None:
            normalized.append(
                ScoreDetail(
                    slide_section=name,
                    tier=tier,  # override -> single source of truth
                    score_1_10=max(0, min(10, found.score_1_10)),
                    coverage=found.coverage,
                )
            )
        else:
            normalized.append(
                ScoreDetail(slide_section=name, tier=tier, score_1_10=0, coverage="missing")
            )
    normalized.sort(key=lambda d: SECTION_ORDER[d.slide_section])
    return llm.model_copy(update={"score_details": normalized})


def evaluate_proposal(proposal_text: str, context: dict | None = None, lang: str = "en") -> EvaluationLLMOutput:
    """เรียก LLM (provider ตาม settings) แล้วคืน validated + rubric-normalized output (F09/F10). lang = 'th'|'en'."""
    client, deployment = llm.client_and_model()
    messages = [
        {"role": "system", "content": _load_system_prompt()},
        {"role": "user", "content": _build_user_message(proposal_text, context, lang)},
    ]

    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = llm.chat(
                client,
                model=deployment,
                messages=messages,
                temperature=_TEMPERATURE,
                max_tokens=_MAX_TOKENS_EVAL,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            parsed = EvaluationLLMOutput.model_validate_json(llm.json_text(raw))
            return _normalize_to_rubric(parsed)
        except Exception as err:  # noqa: BLE001 — retry ทุก error (network/parse/validation)
            last_err = err
            if attempt < _MAX_RETRIES:
                # 429 rate-limit reset ต่อนาที -> backoff นานขึ้น (8s, 16s) ไม่ยิงรัวในนาทีเดียว
                is_rate = "429" in str(err) or "rate" in str(err).lower()
                time.sleep((8 if is_rate else 2) * (attempt + 1))
    raise RuntimeError(f"Evaluation failed after {_MAX_RETRIES + 1} attempts: {last_err}")
