"""Presentation Coach (R4) — สร้าง guideline การนำเสนอ proposal ตามกลุ่มผู้ฟัง.

รับ proposal text + audience role -> LLM สรุป guideline (markdown ไทย) ว่าควรโฟกัสอะไร
เน้นอะไร เลี่ยงอะไร ตามระดับผู้ฟัง โดยอ้างอิงเนื้อหา proposal จริง.
ใช้ LLM provider เดียวกับ audit (llm.client_and_model).
"""
from __future__ import annotations

import time

from . import llm

# audience role -> คำอธิบายบริบทให้ LLM ปรับคำแนะนำ
AUDIENCE = {
    "c_level": "ผู้บริหารระดับสูง (C-Level / executives) — สนใจคุณค่าเชิงธุรกิจ, ROI, ความเสี่ยง, "
               "timeline ภาพรวม, ผลกระทบเชิงกลยุทธ์ ไม่ลงลึกรายละเอียดเทคนิค เวลาจำกัด",
    "users": "ผู้ใช้งานจริง (end users) — สนใจว่าระบบช่วยงานประจำวันยังไง ใช้ง่ายไหม "
             "เปลี่ยนวิธีทำงานเดิมแค่ไหน มีการอบรม/ช่วยเหลือยังไง กังวลเรื่อง workload ช่วงเปลี่ยนผ่าน",
    "it": "ฝ่าย IT ขององค์กรลูกค้า — สนใจการดูแลระบบระยะยาว, การเชื่อมต่อกับระบบเดิม (integration), "
          "security/compliance, โครงสร้างพื้นฐานที่ต้องเตรียม, ภาระ support หลัง go-live",
    "purchase": "ฝ่ายจัดซื้อ (procurement) — สนใจความคุ้มค่า ราคาเทียบตลาด, เงื่อนไขสัญญา/การจ่ายเงิน, "
                "SLA และ penalty, ความน่าเชื่อถือของ vendor, ความเสี่ยงด้านสัญญาและการส่งมอบ",
    "technical": "ทีมเทคนิค (engineers / architects) — สนใจสถาปัตยกรรม, การเชื่อมต่อระบบ (integration), "
                 "ความเป็นไปได้เชิงเทคนิค, security, ความน่าเชื่อถือของ solution",
    "non_technical": "ผู้ฟังทั่วไปที่ไม่ใช่สายเทคนิค (business users / operations) — สนใจประโยชน์ใช้งานจริง, "
                     "ความง่ายในการใช้, ผลลัพธ์ที่จับต้องได้ ต้องใช้ภาษาเข้าใจง่าย เลี่ยงศัพท์เทคนิค",
}

_TEMPERATURE = 0.3  # ให้มีความสร้างสรรค์เล็กน้อยแต่ยังยึดเนื้อหา
_MAX_TOKENS = 3000  # G02 — 4 หัวข้อ markdown; ไม่ตั้งแล้วอาจถูกตัดกลางประโยค
_MAX_RETRIES = 1    # G03 — ให้เท่ากับ project_content/evaluation (เดิมไม่มี retry เลย)

# ภาษาของ guideline ต้องตามภาษาที่เลือกไว้ตอนประเมิน (คอลัมน์ lang ของ submission)
# เดิม prompt ตรึงภาษาไทยไว้ตายตัว -> เลือก English ตอนประเมินก็ยังได้ guideline ไทย
# หมายเหตุ: คำอธิบายผู้ฟัง (AUDIENCE) คงเป็นไทยได้ — เป็นบริบทให้โมเดล ไม่ใช่ผลลัพธ์
_PROMPT = {
    "th": {
        "intro": (
            "คุณเป็นโค้ชการนำเสนอ (presentation coach) มืออาชีพสำหรับงานขาย B2B enterprise. "
            "อ่าน proposal ที่ให้ แล้วสรุปเป็น guideline การนำเสนอที่เจาะจงกลุ่มผู้ฟัง โดยยึดจากเนื้อหา proposal จริง. "
            "ตอบเป็น**ภาษาไทย**ทั้งหมด รูปแบบ markdown มีหัวข้อตามนี้:\n"
        ),
        "sections": (
            "## โฟกัสหลัก\n(3-4 ข้อ ว่าการพรีเซนต์ต่อผู้ฟังกลุ่มนี้ควรเน้นภาพรวมเรื่องอะไร)\n"
            "## ประเด็นที่ควรชู\n(ดึงจุดแข็ง/เนื้อหาจริงใน proposal ที่โดนใจผู้ฟังกลุ่มนี้ อ้างส่วนที่เกี่ยวข้อง)\n"
            "## สิ่งที่ควรเลี่ยงหรือระวัง\n(สิ่งที่ผู้ฟังกลุ่มนี้ไม่สนใจ หรือจุดอ่อนใน proposal ที่ต้องเตรียมรับมือ)\n"
            "## คำถามที่อาจโดนถาม + แนวตอบ\n(2-3 คำถามที่ผู้ฟังกลุ่มนี้มักถาม พร้อมแนวทางตอบ)\n\n"
        ),
        "rule": "ห้ามแนะนำลอยๆ — ต้องอ้างอิงเนื้อหาที่มีจริงใน proposal เสมอ.",
        "audience_label": "กลุ่มผู้ฟัง",
    },
    "en": {
        "intro": (
            "You are a professional presentation coach for B2B enterprise sales. "
            "Read the proposal provided and produce a presentation guideline tailored to the given "
            "audience, grounded in the actual proposal content. "
            "Write your entire answer in **English**, as markdown with exactly these headings:\n"
        ),
        "sections": (
            "## Main Focus\n(3-4 points on what this audience's presentation should emphasise overall)\n"
            "## Points to Highlight\n(pull real strengths/content from the proposal that resonate with "
            "this audience; cite the relevant parts)\n"
            "## What to Avoid or Watch Out For\n(what this audience does not care about, or weaknesses "
            "in the proposal you must be ready to handle)\n"
            "## Likely Questions + How to Answer\n(2-3 questions this audience typically asks, with "
            "suggested answers)\n\n"
        ),
        "rule": "Never give generic advice — always ground every point in content that actually exists "
                "in the proposal.",
        "audience_label": "Audience",
    },
}


def coach_cache_key(text: str, lang: str | None) -> str:
    """กุญแจ reuse ของ Presentation Coach = hash ของ (เนื้อหา + ภาษา).

    ต้องรวมภาษาด้วย ไม่งั้น proposal เดิมที่ประเมินใหม่เป็นอีกภาษาจะได้ guideline
    ภาษาเดิมจาก cache. ยังยาว 64 อักขระ พอดีคอลัมน์ CoachJobs.content_hash
    """
    from .evaluation import content_hash  # lazy: เลี่ยงวงจร import ตอนโหลดโมดูล

    return content_hash(f"{text}\n<<coach-lang={(lang or 'th').strip().lower()}>>")


def coach_guideline(proposal_text: str, audience_desc: str, lang: str = "th") -> str:
    """คืน guideline การนำเสนอ (markdown) ในภาษา `lang` ('th'|'en').

    audience_desc = คำอธิบายผู้ฟัง (จาก AUDIENCE map หรือ custom text ที่ผู้ใช้พิมพ์เอง).
    lang ควรมาจาก submission ที่ประเมินล่าสุดของ thread — ไม่ใช่ค่าคงที่.
    """
    p = _PROMPT.get((lang or "").strip().lower(), _PROMPT["th"])
    client, model = llm.client_and_model()
    system = p["intro"] + p["sections"] + p["rule"]
    user = (
        f"{p['audience_label']}: {audience_desc}\n\n"
        f"=== PROPOSAL TEXT ===\n{proposal_text[:24000]}\n=== END ==="
    )
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = llm.chat(
                client,
                model=model, temperature=_TEMPERATURE, max_tokens=_MAX_TOKENS,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            out = resp.choices[0].message.content or ""
            if out.strip():
                return out
            last_err = RuntimeError("LLM คืนค่าว่าง")
        except Exception as err:  # noqa: BLE001 — G03: retry เท่ากับจุดอื่น
            last_err = err
        if attempt < _MAX_RETRIES:
            # 429 rate-limit reset ต่อนาที -> รอนานขึ้น (เทียบกับ project_content.py)
            is_rate = "429" in str(last_err) or "rate" in str(last_err).lower()
            time.sleep(8 if is_rate else 2)
    raise RuntimeError(f"สร้าง guideline ไม่สำเร็จ: {last_err}")
