"""LLM provider factory (R2) — เลือก Azure OpenAI หรือ Local LLM.

Provider สลับได้ global ผ่านหน้า Settings (คีย์ `llm_provider` ใน dbo.AppSettings):
- "azure" (default) -> Azure OpenAI จาก env (AZURE_OPENAI_*)
- "local"           -> OpenAI-compatible endpoint จาก env (LOCAL_LLM_BASE_URL/API_KEY/MODEL)

Settings เก็บแค่ "ตัวเลือก provider"; endpoint/token/model ของ local ฝังใน env (Function App
App Settings) ไม่เก็บใน DB -> ไม่มี secret ใน DB และไม่ leak ผ่าน settings API.

client ที่คืนเป็น openai SDK เหมือนกันทั้งคู่ (chat.completions + JSON mode).

หมายเหตุ latency: local LLM ทดสอบแล้ว 20-30s/call -> timeout ตั้งสูง (600s) แต่ Azure
Functions HTTP ยังมีเพดาน ~230s เอง (เป็น risk แยก ดู memory proposal-evaluator-project).
"""
from __future__ import annotations

import os

# คีย์ LLM ที่ให้ admin แก้ผ่าน Settings (whitelist ของ settings_put)
# provider = azure|local; local_llm_model = model ที่เลือกจาก UI (endpoint/token ฝัง env)
LLM_SETTING_KEYS = ("llm_provider", "local_llm_model")

_LOCAL_TIMEOUT = 600  # local LLM ช้า -> เผื่อเวลา (Functions HTTP เพดาน ~230s เอง)


def local_env_ready() -> bool:
    """endpoint local พร้อมไหม (base_url env ตั้งไว้) — model เลือกจาก UI แยกต่างหาก."""
    return bool(os.environ.get("LOCAL_LLM_BASE_URL"))


def list_models() -> list[str]:
    """ดึงรายชื่อ model จาก local server (GET /v1/models) ให้ UI เลือก.

    env ไม่ครบ หรือต่อไม่ได้ -> [] (UI แสดงว่ายังเลือกไม่ได้).
    """
    base_url = os.environ.get("LOCAL_LLM_BASE_URL", "").strip()
    if not base_url:
        return []
    from openai import OpenAI

    api_key = os.environ.get("LOCAL_LLM_API_KEY", "").strip() or "not-needed"
    try:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=30)
        ids = [m.id for m in client.models.list().data]
        # เหลือเฉพาะ chat model — ตัด embedding/OCR (bge / ocr / embed) ที่ประเมิน proposal ไม่ได้
        return sorted(m for m in ids if not any(k in m.lower() for k in ("bge", "ocr", "embed")))
    except Exception:  # noqa: BLE001 — ต่อ server ไม่ได้ -> UI แสดงว่าง
        return []


def local_info() -> dict:
    """ข้อมูล local LLM สำหรับ admin — endpoint พร้อมไหม + model ที่เลือกไว้ (จาก settings)."""
    from . import db  # lazy

    ready = local_env_ready()
    model = (db.get_settings().get("local_llm_model") or "").strip()
    return {"ready": ready, "model": model}


def current_model() -> str:
    """ชื่อ model ที่จะใช้จริงตาม provider ปัจจุบัน (สำหรับบันทึกลง eval + แสดงใน UI)."""
    from . import db  # lazy

    s = db.get_settings()
    if (s.get("llm_provider") or "azure").strip().lower() == "local":
        return (s.get("local_llm_model") or os.environ.get("LOCAL_LLM_MODEL", "")).strip() or "local"
    return os.environ.get("AZURE_OPENAI_DEPLOYMENT", "azure")


def get_provider() -> str:
    """provider ปัจจุบัน ('azure'|'local'). อ่านล้มเหลว -> azure (ปลอดภัย, ของเดิม)."""
    from . import db  # lazy: กัน import chain ดึง pyodbc ตอน offline eval

    try:
        return (db.get_settings().get("llm_provider") or "azure").strip().lower()
    except Exception:  # noqa: BLE001 — DB มีปัญหา -> fallback Azure
        return "azure"


def client_and_model() -> tuple[object, str]:
    """คืน (openai client, model/deployment name) ตาม provider ที่ตั้งไว้.

    local ตั้งค่าไม่ครบ (ขาด base_url หรือ model) -> RuntimeError ให้ caller retry/แจ้ง.
    """
    from . import db  # lazy: กัน import chain ดึง pyodbc ตอน offline eval

    settings = db.get_settings()
    provider = (settings.get("llm_provider") or "azure").strip().lower()

    if provider == "local":
        from openai import OpenAI

        base_url = os.environ.get("LOCAL_LLM_BASE_URL", "").strip()
        if not base_url:
            raise RuntimeError("Local LLM endpoint ไม่พร้อม — ตั้ง env LOCAL_LLM_BASE_URL บน Function App")
        # model เลือกจาก UI (settings); fallback env LOCAL_LLM_MODEL เผื่อยังไม่ได้เลือก
        model = (settings.get("local_llm_model") or os.environ.get("LOCAL_LLM_MODEL", "")).strip()
        if not model:
            raise RuntimeError("ยังไม่ได้เลือก Local LLM model ใน Settings")
        api_key = os.environ.get("LOCAL_LLM_API_KEY", "").strip() or "not-needed"
        return OpenAI(base_url=base_url, api_key=api_key, timeout=_LOCAL_TIMEOUT), model

    # default: Azure OpenAI (env เดิม)
    return azure_client_and_model()


# --------------------------------------------------------------------------
# ตัวกลางเรียก chat.completions — ทนความต่างของพารามิเตอร์ระหว่างรุ่น model
# --------------------------------------------------------------------------
# ปัญหาที่แก้: model รุ่นใหม่ (ตระกูล gpt-5.x / o-series) เลิกรับ `max_tokens`
# ต้องส่ง `max_completion_tokens` แทน และบางรุ่นรับ temperature ได้แค่ค่า default
# ขณะที่รุ่นเก่ากับ local server หลายตัวรู้จักแต่ `max_tokens`
#
# จะ hardcode รายชื่อ model ไม่ได้ เพราะ provider สลับได้จากหน้า Settings และ
# local server เสิร์ฟ model อะไรก็ได้ -> จึง "ลองแล้วปรับตามที่ server บอก"
# แล้วจำไว้ต่อ process (คงอยู่ตลอดอายุ instance) ครั้งถัดไปยิงถูกทันที
_TOKEN_PARAM: dict[str, str] = {}     # model -> "max_tokens" | "max_completion_tokens"
_NO_TEMPERATURE: set[str] = set()     # model ที่รับ temperature ได้แค่ค่า default


def _rejects(msg: str, param: str) -> bool:
    """ข้อความ error บอกว่า `param` ใช้กับ model นี้ไม่ได้ใช่ไหม."""
    low = msg.lower()
    return f"'{param}'" in msg and ("unsupported" in low or "not supported" in low)


def chat(client: object, *, model: str, messages: list, max_tokens: int | None = None,
         temperature: float | None = None, **kw):
    """เรียก client.chat.completions.create โดยเลือกชื่อพารามิเตอร์ให้ถูกกับ model.

    ปรับได้ 2 อย่างตามที่ server ปฏิเสธ: ชื่อพารามิเตอร์จำนวนโทเคน และการตัด temperature ออก
    error อื่น (429 / network / เนื้อหา) โยนต่อทันที — ให้ retry loop ของ caller จัดการ
    เหมือนเดิม เพื่อไม่ให้ backoff ซ้อนกันสองชั้น
    """
    token_key = _TOKEN_PARAM.get(model, "max_tokens")
    send_temp = temperature is not None and model not in _NO_TEMPERATURE

    for _ in range(3):  # ปรับได้มากสุด 2 ครั้ง (token param + temperature) แล้วต้องได้ผล
        args = dict(kw, model=model, messages=messages)
        if max_tokens is not None:
            args[token_key] = max_tokens
        if send_temp:
            args["temperature"] = temperature
        try:
            return client.chat.completions.create(**args)  # type: ignore[attr-defined]
        except Exception as err:  # noqa: BLE001 — คัดเฉพาะ error เรื่องพารามิเตอร์
            msg = str(err)
            # เช็ค max_tokens ก่อน เพราะข้อความของ OpenAI มีคำว่า max_completion_tokens ปนอยู่
            if token_key == "max_tokens" and _rejects(msg, "max_tokens"):
                token_key = _TOKEN_PARAM[model] = "max_completion_tokens"
                continue
            if token_key == "max_completion_tokens" and _rejects(msg, "max_completion_tokens"):
                token_key = _TOKEN_PARAM[model] = "max_tokens"
                continue
            if send_temp and _rejects(msg, "temperature"):
                _NO_TEMPERATURE.add(model)
                send_temp = False
                continue
            raise
    raise RuntimeError(f"model '{model}' ปฏิเสธพารามิเตอร์ซ้ำหลายรอบ — ตรวจว่า model รองรับ chat completions")


def json_text(raw: str) -> str:
    """ตัดสิ่งที่ไม่ใช่ JSON ออกจากคำตอบ LLM ก่อนส่งให้ pydantic parse.

    ทำไมต้องมี: model บางรุ่นไม่เคารพ response_format={"type":"json_object"} แล้วห่อคำตอบไว้
    พบจริงจากการทดสอบ:
      - gemma4:26b ใส่ `---` (แบบ YAML front matter) นำหน้า -> parse พังทันที 3/3 รอบ
      - หลายรุ่นห่อด้วย ```json ... ``` หรือมีข้อความอธิบายนำ/ตาม

    ตัดแบบอนุรักษ์นิยม: เอาเฉพาะช่วงตั้งแต่ '{' ตัวแรกถึง '}' ตัวสุดท้าย
    ไม่พบวงเล็บปีกกา -> คืนค่าเดิม ให้ error เดิมเกิดตามปกติ (ไม่กลืนปัญหา)

    ไม่ต้องจัดการ ``` แยกต่างหาก — การตัดช่วงปีกกาข้าม fence หัวท้ายให้เองอยู่แล้ว
    (เคยมีบล็อกตัด fence ด้วย s.split("\\n",1) ซึ่งกลับทำให้ทรง '```json {' บรรทัดเดียว
    พังทั้งที่กู้ได้ — ตัดออกแล้ว ดู eval/test_review_fixes.py)
    """
    if not raw:
        return raw
    s = raw.strip()
    start, end = s.find("{"), s.rfind("}")
    return s[start:end + 1] if 0 <= start < end else raw


def azure_client_and_model() -> tuple[object, str]:
    """Azure OpenAI เสมอ (ไม่สน provider) — ใช้กับงานเบา sync ที่ต้องเร็ว เช่น detect metadata
    ตอน prepare (ไม่งั้น provider=local จะทำ prepare hang ชน HTTP timeout)."""
    from openai import AzureOpenAI

    return (
        AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],
        ),
        os.environ["AZURE_OPENAI_DEPLOYMENT"],
    )
