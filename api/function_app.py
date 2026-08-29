"""Azure Functions (Python v2 model) — HTTP API.

Flow (2-phase upload):
  POST /api/prepare             F03/F04/F06/F07/F20/F22 — upload -> store -> extract -> detect meta -> lookup
  POST /api/evaluate            F11/F12/F24/F25 — confirm -> cache/gate -> evaluate/reuse -> persist
  POST /api/comments            F26 — add user comment
  GET  /api/threads/{id}/history F17/F27 — versions + comments
  GET  /api/health              liveness

Auth (F01/F02): `auth_level=ANONYMOUS` โดยตั้งใจ — Static Web Apps เป็นด่าน "ยืนยันตัวตน"
(authentication). ห้าม deploy standalone.

⚠️ แยกให้ชัด 2 เรื่องที่คนละชั้นกัน (สำคัญ — เข้าใจผิดแล้วเปิดช่องยึดระบบ)
  1. "ผู้ใช้ต้องต่อ VPN ก่อนเปิดเว็บ" — ไม่จำเป็น ถอดได้ ผู้ใช้เข้าผ่าน URL ของ SWA
     ซึ่งบังคับ SSO อยู่แล้ว. ถ้าต้องการจำกัดตามเครือข่าย ใช้สวิตช์ในหน้า Settings
     (shared.guard S02 — ค่าเริ่มต้นปิด)
  2. "Function App ต้องเรียกได้จาก SWA เท่านั้น" — ⛔ ห้ามถอด. header
     `x-ms-client-principal` ไม่มีลายเซ็นให้ตรวจ ปลอมได้ทันที -> ถ้า Function App
     เปิดตรงสู่อินเทอร์เน็ต ใครก็เป็น admin ได้ และชั้นสิทธิ์ทั้งหมดไร้ผล
     (ดูรายละเอียดใน shared/auth.py)

⚠️ Wave 1: ด่าน "สิทธิ์" (authorization) เป็นหน้าที่ของ shared.guard ไม่ใช่ของ SWA.
ทุก HTTP handler ต้องเริ่มด้วย guard.gate(req, "<ชื่อฟังก์ชัน>") และประกาศสิทธิ์ตัวเอง
ใน guard.ROUTE_PERMS. endpoint ที่ลืมประกาศจะถูกปฏิเสธ 403 โดยปริยาย (fail-closed).

⛔ ห้ามเรียกอะไรที่แตะ `app` (เช่น app.get_functions()) ที่ระดับโมดูล — ทำให้ Azure
index ได้ 0 function = แอปล่ม (ดูหมายเหตุท้ายไฟล์). ตรวจความครบถ้วนแบบ static ตอน dev แทน.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlparse

import azure.functions as func
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, ContentSettings, generate_blob_sas

from shared import audit, auth, db, guard, llm, presentation, scoring
from shared.evaluation import (
    content_hash,
    detect_metadata,
    evaluate_proposal,
    improvement_gate,
)
from shared import extraction
from shared.extraction import extract_text
from shared.project_content import extract_project_content

app = func.FunctionApp()

# PDF-only ตั้งแต่ 2026-08-19 (ดูเหตุผลใน shared/extraction.py) — .pptx ถูกปฏิเสธที่ด่านนี้
# octet-stream/ว่าง ยอมให้ผ่านได้ เพราะบางเบราว์เซอร์ส่ง content_type แบบนั้นมากับ .pdf จริง
# นามสกุลไฟล์คือด่านชี้ขาด ไม่ใช่ content_type (ปลอมง่ายกว่า)
_ALLOWED_TYPES = {"application/pdf", "application/octet-stream", ""}
_MAX_BYTES = 25 * 1024 * 1024

# R9 — SAS URL ข้ามการตรวจสิทธิ์ทั้งหมด (ใครถือลิงก์ก็เปิดไฟล์ได้ ไม่ต้อง login)
# ลดอายุจาก 4 ชม. เป็น 15 นาที เพื่อจำกัดหน้าต่างความเสี่ยง — พอสำหรับกดเปิดไฟล์ทันที
# (ทางแก้ถาวรคือ proxy ไฟล์ผ่าน API พร้อมตรวจสิทธิ์ — อยู่นอกขอบเขต Wave 1)
_SAS_TTL_HOURS = 0.25


def _json(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False, default=str), status_code=status, mimetype="application/json"
    )


def _upload_blob(data: bytes, filename: str, prefix: str) -> str:
    svc = BlobServiceClient.from_connection_string(os.environ["BLOB_CONNECTION_STRING"])
    container = os.environ.get("BLOB_CONTAINER", "proposals")
    client = svc.get_blob_client(container=container, blob=f"{prefix}/{filename}")
    client.upload_blob(data, overwrite=True)
    return client.url


def _sas_url(blob_url: str, hours: float = _SAS_TTL_HOURS) -> str:
    """สร้าง read-only SAS URL ให้เปิดไฟล์ต้นฉบับได้ (container เป็น private).

    อายุสั้น (_SAS_TTL_HOURS) โดยเจตนา — ลิงก์นี้เป็น bearer credential ที่ข้ามสิทธิ์ทั้งหมด.
    """
    if not blob_url:
        return ""
    try:
        svc = BlobServiceClient.from_connection_string(os.environ["BLOB_CONNECTION_STRING"])
        path = unquote(urlparse(blob_url).path).lstrip("/")
        container, _, blob_name = path.partition("/")
        sas = generate_blob_sas(
            account_name=svc.account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=svc.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=hours),
        )
        return f"{blob_url}?{sas}"
    except Exception:  # noqa: BLE001
        logging.exception("SAS generation failed")
        return ""


# ---------------------------------------------------------------------------
# Playbook (คู่มือการใช้งานสำหรับทีม) — เก็บใน Blob container เดียวกับ proposal
# แต่แยก prefix "playbook/" ออกจากไฟล์ลูกค้าอย่างชัดเจน
#
# ทำไมไม่ฝังไฟล์ไปกับ frontend: PDF+PPTX รวม ~36 MB -> bundle บวมทุก deploy และ
# ขัดกับ .gitignore ที่กัน `docs/*.pdf` ไว้ตั้งใจ. เก็บใน Blob ทำให้ admin
# เปลี่ยนไฟล์ใหม่ได้จากหน้า Settings โดยไม่ต้อง redeploy
# ---------------------------------------------------------------------------
_PLAYBOOK_PREFIX = "playbook"
_PLAYBOOK_MAX_BYTES = 30 * 1024 * 1024      # PPTX ฉบับปัจจุบัน ~19.7 MB -> เผื่อไว้
# อายุ SAS ของ playbook ยาวกว่าไฟล์ proposal (15 นาที) โดยเจตนา: เอกสารนี้เป็น
# คู่มือภายในไม่มีข้อมูลลูกค้า และไฟล์ใหญ่ 16-20 MB ผู้ใช้อาจเปิดค้างไว้ก่อนกดโหลด
_PLAYBOOK_SAS_TTL_HOURS = 1.0
_PLAYBOOK_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown; charset=utf-8",
}


def _playbook_container():
    svc = BlobServiceClient.from_connection_string(os.environ["BLOB_CONNECTION_STRING"])
    return svc.get_container_client(os.environ.get("BLOB_CONTAINER", "proposals"))


def _safe_playbook_name(raw: str) -> str:
    """ชื่อไฟล์ที่ปลอดภัยพอจะต่อท้าย prefix ได้ — "" ถ้าไม่ผ่าน.

    กัน path traversal (../, \\, /) ไม่ให้เขียน/ลบ blob นอก prefix "playbook/".
    """
    name = os.path.basename((raw or "").replace("\\", "/")).strip()
    if not name or name.startswith(".") or len(name) > 120 or "/" in name:
        return ""
    if os.path.splitext(name)[1].lower() not in _PLAYBOOK_TYPES:
        return ""
    return name


def _playbook_items() -> list[dict]:
    """รายการไฟล์ playbook ทั้งหมด + ลิงก์ SAS (อายุสั้น) สำหรับเปิด/ดาวน์โหลด."""
    cc = _playbook_container()
    items: list[dict] = []
    for b in cc.list_blobs(name_starts_with=f"{_PLAYBOOK_PREFIX}/"):
        name = b.name.split("/", 1)[1] if "/" in b.name else ""
        if not name:
            continue
        cs = getattr(b, "content_settings", None)
        items.append({
            "name": name,
            "size": int(b.size or 0),
            "content_type": (getattr(cs, "content_type", "") or ""),
            "updated_at": str(b.last_modified) if b.last_modified else "",
            "url": _sas_url(f"{cc.url}/{quote(b.name)}", hours=_PLAYBOOK_SAS_TTL_HOURS),
        })
    items.sort(key=lambda x: x["name"].lower())
    return items


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Liveness probe — ประกาศเป็น PUBLIC ใน guard.ROUTE_PERMS และตั้งใจ *ไม่* เรียก gate()
    เพื่อไม่ให้ probe แตะฐานข้อมูล (gate จะ resolve user/role จาก DB)."""
    return _json({"status": "ok"})


@app.route(route="prepare", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def prepare(req: func.HttpRequest) -> func.HttpResponse:
    """F03/F04/F06/F07/F20/F22 — upload + extract + detect + lookup (ยังไม่ประเมิน/ยังไม่สร้าง thread)."""
    try:
        me, deny = guard.gate(req, "prepare")  # A04 — กันคนที่ไม่มีสิทธิ์ evaluate เผาโทเคน OCR/LLM
        if deny:
            return deny
        file = req.files.get("file")
        if file is None:
            return _json({"error": "missing file"}, 400)
        filename = file.filename or "proposal"
        content_type = file.content_type or ""
        data = file.stream.read()

        if len(data) > _MAX_BYTES:
            return _json({"error": "file too large (max 25MB)"}, 413)
        if not filename.lower().endswith(".pdf") or content_type not in _ALLOWED_TYPES:
            if filename.lower().endswith(".pptx") or "presentation" in content_type:
                return _json({"error": extraction.PPTX_REJECTED}, 415)
            return _json({"error": "รองรับเฉพาะไฟล์ PDF เท่านั้น"}, 415)

        prefix = str(uuid.uuid4())
        blob_url = _upload_blob(data, filename, prefix)

        text = extract_text(data, content_type, filename)
        if not text.strip():
            return _json({"error": "no text extracted from file"}, 422)

        chash = content_hash(text)
        meta = detect_metadata(text)

        # preview existing: (1) ไฟล์เดียวกัน (content_hash) -> thread เดิมเสมอ แม้ detect ชื่อเพี้ยน
        #                    (2) fallback: match client+project ที่ detect ได้
        existing = None
        thread = db.find_thread_by_hash(chash)
        if not thread and meta.client_name and meta.project_name:
            thread = db.find_thread_by_client_project(meta.client_name, meta.project_name)
        # B02 — thread ที่ผู้ใช้คนนี้เข้าไม่ได้ ต้องไม่เปิดเผย ticket/คะแนนของโปรเจคคนอื่น
        # ปฏิบัติเหมือน "ไม่พบ" -> UI เสนอเป็นโปรเจคใหม่ (evaluate จะสร้าง thread ของเขาเอง)
        if thread and guard.thread_access(me, thread["thread_id"]) is not None:
            thread = None
        if thread:
            prior = db.latest_evaluated_submission(thread["thread_id"])
            scores = db.get_thread_scores(thread["thread_id"])
            latest = scores[-1] if scores else None
            existing = {
                "thread_id": thread["thread_id"],
                "ticket_no": thread["ticket_no"],
                # ใช้ชื่อจาก thread เดิมเป็นหลัก (คงชื่อโปรเจคเดิม ไม่ใช้ detect ที่อาจเพี้ยน)
                "client_name": thread.get("client_name") or meta.client_name,
                "project_name": thread.get("project_name") or meta.project_name,
                "latest_version": prior["version_no"] if prior else 0,
                "next_version": (prior["version_no"] + 1) if prior else 1,
                "latest_score": float(latest["overall_score"]) if latest and latest["overall_score"] is not None else None,
                "latest_verdict": latest["verdict"] if latest else None,
                "evaluated_at": str(latest["evaluated_at"]) if latest and latest.get("evaluated_at") else None,
            }

        return _json({
            "blob_url": blob_url,
            "filename": filename,
            "content_type": content_type,
            "file_size": len(data),
            "content_hash": chash,
            "text": text,
            "suggested_client": meta.client_name,
            "suggested_project": meta.project_name,
            "existing": existing,          # null = โปรเจคใหม่
        })
    except Exception as err:  # noqa: BLE001
        logging.exception("prepare failed")
        return _json({"error": str(err)}, 500)


@app.route(route="evaluate", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@app.queue_output(arg_name="msg", queue_name="eval-jobs", connection="AzureWebJobsStorage")
def evaluate(req: func.HttpRequest, msg: func.Out[str]) -> func.HttpResponse:
    """F11/F24/F25 — confirm. cache hit -> reuse ทันที (sync); ต้องเรียก LLM -> enqueue รัน async
    (frontend poll /api/submissions/{id}/status). endpoint นี้ไม่เรียก LLM เอง -> ไม่ชน HTTP timeout."""
    try:
        me, deny = guard.gate(req, "evaluate")  # A04
        if deny:
            return deny
        b = req.get_json()
        client_name = (b.get("client_name") or "").strip()
        project_name = (b.get("project_name") or "").strip()
        text = b.get("text") or ""
        if not client_name or not project_name:
            return _json({"error": "client_name และ project_name จำเป็น"}, 400)
        if not text.strip():
            return _json({"error": "missing text (เรียก /api/prepare ก่อน)"}, 400)

        lang = b.get("lang") if b.get("lang") in ("th", "en") else "en"
        chash = content_hash(text)

        # find/create thread + ticket (F21/F22) — set owner จาก user ที่ login (F44)
        override_tid = (b.get("thread_id") or "").strip()
        if override_tid:
            # R5 — user เลือกโปรเจคเจาะจงจากรายชื่อ -> ประเมินเป็น version ใหม่ของ thread นั้น
            # B02 — ต้องเป็นเจ้าของ (หรือมี view_all) ไม่ให้ผู้อื่นแนบ version เข้าโปรเจคคนอื่น
            deny = guard.thread_access(me, override_tid)
            if deny:
                return deny
            t = db.get_thread(override_tid)
            if not t:
                return _json({"error": "ไม่พบโปรเจคที่เลือก"}, 400)
            thread_id, ticket_no = override_tid, t["ticket_no"]
        elif b.get("force_new"):
            # user เลือก "โปรเจคใหม่" -> ออก ticket ใหม่เสมอ ไม่จับคู่ thread เดิมจากชื่อ client+project
            ticket_no = db.issue_ticket(datetime.now(timezone.utc).year)
            thread_id = db.create_thread(client_name, project_name, ticket_no, owner_id=me["user_id"])
        else:
            thread = db.find_thread_by_client_project(client_name, project_name)
            if thread:
                # B02 — จับคู่ชื่อได้ ไม่ได้แปลว่ามีสิทธิ์: ถ้าเป็น thread ของคนอื่นต้องถูกปฏิเสธ
                # (ไม่งั้นพิมพ์ชื่อ client/project ให้ตรงก็แนบ version เข้าโปรเจคคนอื่นได้)
                deny = guard.thread_access(me, thread["thread_id"])
                if deny:
                    return deny
                thread_id, ticket_no = thread["thread_id"], thread["ticket_no"]
            else:
                ticket_no = db.issue_ticket(datetime.now(timezone.utc).year)
                thread_id = db.create_thread(client_name, project_name, ticket_no, owner_id=me["user_id"])

        version_no = db.next_version_no(thread_id)
        submission_id = db.create_submission(
            thread_id, version_no, b.get("filename", "proposal"), b.get("content_type", ""),
            b.get("blob_url", ""), int(b.get("file_size", 0)), chash, text, lang,
        )

        # F24 — cache hit (เนื้อหา+ภาษาเดิมเป๊ะ) -> reuse ทันที ไม่ต้องเรียก LLM (sync เร็ว)
        cached_eval_id = db.find_eval_by_hash(thread_id, chash, lang)
        if cached_eval_id:
            eval_id = db.copy_evaluation(submission_id, cached_eval_id)
            try:
                _extract_and_store_content(thread_id, submission_id, chash, text)
            except Exception:  # noqa: BLE001
                logging.exception("project content extraction failed (non-fatal)")
            result = db.get_evaluation(eval_id)
            return _json({
                "status": "done",
                "thread_id": thread_id, "ticket_no": ticket_no, "version_no": version_no,
                "submission_id": submission_id, "score_source": "reused",
                "gate_note": "identical content + language (cache hit)", "lang": lang,
                "filename": b.get("filename", "proposal"), "file_url": _sas_url(b.get("blob_url", "")),
                **result,
                "history": db.get_thread_scores(thread_id),
                "comments": db.get_comments(thread_id),
            })

        # ต้องเรียก LLM (gate/eval) -> ส่งเข้า queue รันเบื้องหลัง -> คืน processing ให้ frontend poll
        msg.set(json.dumps({"submission_id": submission_id, "lang": lang}))
        return _json({
            "status": "processing", "thread_id": thread_id, "ticket_no": ticket_no,
            "version_no": version_no, "submission_id": submission_id, "lang": lang,
        })
    except Exception as err:  # noqa: BLE001
        logging.exception("evaluate failed")
        return _json({"error": str(err)}, 500)


def _safe_extract(thread_id: str, submission_id: str, chash: str, text: str) -> None:
    """F30 extract project content แบบ fire-safe (ล้มเหลวไม่กระทบผลประเมิน)."""
    try:
        _extract_and_store_content(thread_id, submission_id, chash, text)
    except Exception:  # noqa: BLE001
        logging.exception("project content extraction failed (non-fatal)")


@app.queue_trigger(arg_name="msg", queue_name="eval-jobs", connection="AzureWebJobsStorage")
def evaluate_worker(msg: func.QueueMessage) -> None:
    """Async worker — รัน gate/eval (LLM) เบื้องหลัง ไม่ชน HTTP timeout. เขียน status Evaluated/Failed."""
    data = json.loads(msg.get_body().decode("utf-8"))
    submission_id = data["submission_id"]
    lang = data.get("lang", "en")
    try:
        sub = db.get_submission(submission_id)
        if not sub:
            logging.error("evaluate_worker: submission %s not found", submission_id)
            return
        text = sub["text_content"]
        thread_id = sub["thread_id"]
        chash = content_hash(text)
        prior = db.latest_evaluated_submission(thread_id)  # submission ปัจจุบันยังไม่ evaluated

        # F25 gate — เนื้อหาเปลี่ยน + ภาษาเดิม + ไม่ได้แก้ตามคำแนะนำ -> reuse คะแนนเดิม
        if prior and prior["content_hash"] != chash and prior["lang"] == lang:
            recs = db.get_recommendation_texts(prior["eval_id"])
            gate = improvement_gate(recs, prior["text_content"], text)
            if gate.addressed_count == 0:
                db.copy_evaluation(submission_id, prior["eval_id"])
                _safe_extract(thread_id, submission_id, chash, text)
                return

        # full evaluation (first version / เนื้อหาหรือภาษาเปลี่ยน)
        # R6 — ถ้าเป็น version แก้ไข: ส่งผลประเมินเวอร์ชันก่อน (คะแนน+gaps+คำแนะนำ) เป็น context เพื่อ align
        context = None
        if prior:
            try:
                pe = db.get_evaluation(prior["eval_id"])
                context = {
                    "prior_version": {
                        "version_no": prior["version_no"],
                        "overall_score": pe.get("overall_score"),
                        "verdict": pe.get("verdict"),
                        "gaps": pe.get("gaps", []),
                        "prior_recommendations": [r["rec_text"] for r in pe.get("recommendations", [])],
                    },
                    "instruction": (
                        "นี่คือฉบับแก้ไขของ proposal เดิม — ประเมินให้สอดคล้องกับผลเวอร์ชันก่อน: "
                        "จุดที่เคยแนะนำแล้วถูกแก้ คะแนนส่วนนั้นควรดีขึ้น; ส่วนที่ยังเหมือนเดิมคะแนนไม่ควรเปลี่ยนมาก"
                    ),
                }
            except Exception:  # noqa: BLE001
                context = None
        llm_out = evaluate_proposal(text, context=context, lang=lang)
        overall = scoring.compute_overall_score(llm_out.score_details)
        db.save_evaluation(submission_id, overall, scoring.map_verdict(overall),
                           llm_out, llm_out.model_dump_json(), llm.current_model(), "evaluated")
        _safe_extract(thread_id, submission_id, chash, text)
    except Exception:  # noqa: BLE001
        logging.exception("evaluate_worker failed for %s", submission_id)
        db.set_submission_status(submission_id, "Failed")


@app.route(route="submissions/{sid}/status", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def submission_status(req: func.HttpRequest) -> func.HttpResponse:
    """Poll สถานะ async eval — Evaluating|Evaluated|Failed. frontend ดึง result (getThread) เมื่อ Evaluated."""
    try:
        u, deny = guard.gate(req, "submission_status")
        if deny:
            return deny
        sub = db.get_submission(req.route_params.get("sid"))
        if not sub:
            return _json({"error": "not found"}, 404)
        deny = guard.thread_access(u, sub["thread_id"])  # B02 — ไม่ให้สอดส่องสถานะงานคนอื่น
        if deny:
            return deny
        return _json({"status": sub["status"], "thread_id": sub["thread_id"]})
    except Exception as err:  # noqa: BLE001
        logging.exception("submission status failed")
        return _json({"error": str(err)}, 500)


@app.route(route="comments", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def comments(req: func.HttpRequest) -> func.HttpResponse:
    """F26 — add user comment. ชื่อผู้เขียนมาจาก principal ฝั่ง server เท่านั้น (D01)."""
    try:
        u, deny = guard.gate(req, "comments")
        if deny:
            return deny
        b = req.get_json()
        thread_id = b.get("thread_id")
        text = (b.get("comment_text") or "").strip()
        if not thread_id or not text:
            return _json({"error": "thread_id และ comment_text จำเป็น"}, 400)
        deny = guard.thread_access(u, thread_id)  # B02
        if deny:
            return deny
        # D01 — เมิน b["author"] ที่ client ส่งมาทิ้งทั้งหมด กันปลอมชื่อผู้คอมเมนต์
        author = u.get("email") or u.get("name") or "unknown"
        db.add_comment(thread_id, b.get("submission_id"), author, text)
        return _json({"thread_id": thread_id, "comments": db.get_comments(thread_id)})
    except Exception as err:  # noqa: BLE001 — G04: ให้สอดคล้องกับ handler อื่น
        logging.exception("add comment failed")
        return _json({"error": str(err)}, 500)


@app.route(route="proposals", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def proposals(req: func.HttpRequest) -> func.HttpResponse:
    """F18/F19 — รายการ proposal. permission view_all -> เห็นทั้งหมด, ไม่งั้นเฉพาะที่ตัวเอง submit.
    scope=mine -> บังคับเห็นเฉพาะของตัวเอง (ใช้กับ dropdown เลือกโปรเจคตอน upload version ใหม่)."""
    try:
        me, deny = guard.gate(req, "proposals")
        if deny:
            return deny
        if req.params.get("scope") == "mine":
            owner = me["user_id"]
        else:
            owner = None if auth.has_page(me["role"], "view_all") else me["user_id"]
        return _json(db.list_proposals(owner_id=owner))
    except Exception as err:  # noqa: BLE001
        logging.exception("proposals list failed")
        return _json({"error": str(err)}, 500)


@app.route(route="threads/{thread_id}", methods=["PATCH"], auth_level=func.AuthLevel.ANONYMOUS)
def thread_update(req: func.HttpRequest) -> func.HttpResponse:
    """R8 — แก้ชื่อ client/project ของโปรเจค (permission manage_proposals)."""
    try:
        thread_id = req.route_params.get("thread_id")
        u, deny = guard.gate_thread(req, "thread_update", thread_id)
        if deny:
            return deny
        b = req.get_json()
        cn = (b.get("client_name") or "").strip()
        pn = (b.get("project_name") or "").strip()
        if not cn or not pn:
            return _json({"error": "ต้องมีชื่อ client และ project"}, 400)
        before = db.get_thread(thread_id)
        db.update_thread(thread_id, cn, pn)
        audit.write(  # C03
            u, audit.THREAD_RENAME, "thread", thread_id,
            target_label=(before or {}).get("ticket_no"),
            before={"client_name": (before or {}).get("client_name"),
                    "project_name": (before or {}).get("project_name")},
            after={"client_name": cn, "project_name": pn},
        )
        return _json({"ok": True})
    except Exception as err:  # noqa: BLE001
        logging.exception("thread update failed")
        return _json({"error": str(err)}, 500)


@app.route(route="threads/{thread_id}", methods=["DELETE"], auth_level=func.AuthLevel.ANONYMOUS)
def thread_delete(req: func.HttpRequest) -> func.HttpResponse:
    """R8 — ลบโปรเจค + ข้อมูลทั้งหมด (permission manage_proposals)."""
    try:
        thread_id = req.route_params.get("thread_id")
        u, deny = guard.gate_thread(req, "thread_delete", thread_id)
        if deny:
            return deny
        before = db.get_thread(thread_id)  # เก็บ ticket/ชื่อไว้ก่อนลบ — audit ต้องอ่านรู้เรื่องภายหลัง
        db.delete_thread(thread_id)
        audit.write(  # C03
            u, audit.THREAD_DELETE, "thread", thread_id,
            target_label=(before or {}).get("ticket_no"), before=before, after=None,
        )
        return _json({"ok": True})
    except Exception as err:  # noqa: BLE001
        logging.exception("thread delete failed")
        return _json({"error": str(err)}, 500)


@app.route(route="threads/{thread_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def thread_detail(req: func.HttpRequest) -> func.HttpResponse:
    """F17 — ผลประเมินเต็มของ version ที่ประเมินแล้วล่าสุดใน thread (shape เดียวกับ /evaluate)."""
    try:
        thread_id = req.route_params.get("thread_id")
        _, deny = guard.gate_thread(req, "thread_detail", thread_id)  # B02 — ปิด IDOR
        if deny:
            return deny
        thread = db.get_thread(thread_id)
        if not thread:
            return _json({"error": "thread not found"}, 404)

        history_rows = db.get_thread_scores(thread_id)
        comments = db.get_comments(thread_id)
        prior = db.latest_evaluated_submission(thread_id)
        if not prior:
            # thread มีอยู่แต่ยังไม่มี version ที่ประเมินสำเร็จ
            return _json({
                "thread_id": thread_id, "ticket_no": thread["ticket_no"],
                "client_name": thread["client_name"], "project_name": thread["project_name"],
                "history": history_rows, "comments": comments, "evaluated": False,
            })

        # score_source ของ version ล่าสุดที่ประเมินแล้ว (จาก history)
        src = next((r.get("score_source") for r in history_rows
                    if r.get("version_no") == prior["version_no"]), None)

        result = db.get_evaluation(prior["eval_id"])
        return _json({
            "thread_id": thread_id, "ticket_no": thread["ticket_no"],
            "client_name": thread["client_name"], "project_name": thread["project_name"],
            "version_no": prior["version_no"], "lang": prior["lang"],
            "score_source": src or "evaluated", "gate_note": "",
            "filename": prior.get("filename", "proposal"), "file_url": _sas_url(prior.get("blob_url", "")),
            **result,
            "history": history_rows, "comments": comments,
        })
    except Exception as err:  # noqa: BLE001
        logging.exception("thread detail failed")
        return _json({"error": str(err)}, 500)


@app.route(route="threads/{thread_id}/history", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def history(req: func.HttpRequest) -> func.HttpResponse:
    """F17/F27 — versions + comments."""
    try:
        thread_id = req.route_params.get("thread_id")
        _, deny = guard.gate_thread(req, "history", thread_id)  # B02
        if deny:
            return deny
        return _json({
            "thread_id": thread_id,
            "versions": db.get_thread_scores(thread_id),
            "comments": db.get_comments(thread_id),
        })
    except Exception as err:  # noqa: BLE001
        logging.exception("thread history failed")
        return _json({"error": str(err)}, 500)


# ===================== Proposal Library (F30-F37) =====================

# field ที่บันทึกลง audit — whitelist โดยเจตนา
# ห้ามใส่ file_url (มี SAS token = credential) และ sharepoint_url ลง audit log
_AUDITED_CONTENT_FIELDS = (
    "price_amount", "price_currency", "cost_amount", "cost_currency", "duration_months",
    "milestones", "manpower", "solution_type", "industry", "deal_outcome",
    "verify_status", "verified_by",
)


def _content_snapshot(item: dict | None) -> dict | None:
    """ย่อ library item เหลือเฉพาะ field ที่ต้องเก็บใน audit (C03)."""
    if not item:
        return None
    return {k: item.get(k) for k in _AUDITED_CONTENT_FIELDS}


def _extract_and_store_content(thread_id: str, submission_id: str, chash: str, text: str) -> None:
    """F30 — extract แล้ว upsert ตามกติกา verify (ห้ามทับข้อมูลที่คนยืนยันแล้ว)."""
    llm = extract_project_content(text)
    db.upsert_extracted_content(
        thread_id, submission_id, chash, llm.model_dump() if llm else None
    )


@app.route(route="me", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def me(req: func.HttpRequest) -> func.HttpResponse:
    """F43 — ตัวตน + role + สิทธิ์เข้าหน้าของผู้ใช้ปัจจุบัน (ให้ frontend ซ่อน/แสดงเมนู).

    PUBLIC โดยเจตนา — ต้องตอบ authenticated:false ได้เพื่อให้ frontend เด้งไป /login
    (ถ้าตอบ 403 จะแยกไม่ออกระหว่าง 'ยังไม่ login' กับ 'login แล้วแต่ไม่มีสิทธิ์')
    """
    try:
        u, deny = guard.gate(req, "me")
        if deny:
            return deny
        return _json({**u, "access": auth.page_access(u["role"])})
    except Exception as err:  # noqa: BLE001
        logging.exception("me failed")
        return _json({"error": str(err)}, 500)


@app.route(route="dashboard", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def dashboard(req: func.HttpRequest) -> func.HttpResponse:
    """F42 — สรุปภาพรวม (management+ เท่านั้น)."""
    try:
        u, deny = guard.gate(req, "dashboard")
        if deny:
            return deny
        return _json(db.get_dashboard())
    except Exception as err:  # noqa: BLE001
        logging.exception("dashboard failed")
        return _json({"error": str(err)}, 500)


# ===================== Users / Settings (F43-F46) =====================

@app.route(route="users", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def users_list(req: func.HttpRequest) -> func.HttpResponse:
    """F44 — รายชื่อ user + role (admin เท่านั้น)."""
    try:
        u, deny = guard.gate(req, "users_list")
        if deny:
            return deny
        return _json(db.list_users())
    except Exception as err:  # noqa: BLE001
        logging.exception("users list failed")
        return _json({"error": str(err)}, 500)


@app.route(route="users", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def users_add(req: func.HttpRequest) -> func.HttpResponse:
    """F44 — pre-add user ด้วย email + role (admin). พอ login จริงได้ role นี้เลย."""
    try:
        u, deny = guard.gate(req, "users_add")
        if deny:
            return deny
        b = req.get_json()
        email = (b.get("email") or "").strip()
        role = (b.get("role") or "user").strip()
        if "@" not in email:
            return _json({"error": "email ไม่ถูกต้อง"}, 400)
        if not db.role_exists(role):
            return _json({"error": f"ไม่พบ role '{role}' ในระบบ"}, 400)
        db.add_user_by_email(email, role)
        return _json({"ok": True, "users": db.list_users()})
    except Exception as err:  # noqa: BLE001
        logging.exception("users add failed")
        return _json({"error": str(err)}, 500)


@app.route(route="users/{user_id}", methods=["PATCH"], auth_level=func.AuthLevel.ANONYMOUS)
def users_set_role(req: func.HttpRequest) -> func.HttpResponse:
    """F44 — เปลี่ยน role ของ user (admin เท่านั้น)."""
    try:
        u, deny = guard.gate(req, "users_set_role")
        if deny:
            return deny
        role = (req.get_json().get("role") or "").strip()
        if not db.role_exists(role):
            return _json({"error": f"ไม่พบ role '{role}' ในระบบ"}, 400)
        user_id = req.route_params.get("user_id")
        target = next((x for x in db.list_users() if str(x["user_id"]) == str(user_id)), None)
        ok = db.set_user_role(user_id, role)
        if ok:
            audit.write(  # C03
                u, audit.USER_ROLE, "user", user_id,
                target_label=(target or {}).get("email"),
                before={"role": (target or {}).get("role")}, after={"role": role},
            )
        return _json({"ok": ok, "users": db.list_users()})
    except Exception as err:  # noqa: BLE001
        logging.exception("set role failed")
        return _json({"error": str(err)}, 500)


@app.route(route="rbac-init", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def admin_init_rbac(req: func.HttpRequest) -> func.HttpResponse:
    """R3 — สร้าง Roles/RolePermissions + seed 4 role เดิม (idempotent, admin). เรียกครั้งเดียวตอน setup."""
    try:
        u, deny = guard.gate(req, "admin_init_rbac")
        if deny:
            return deny
        return _json(db.ensure_rbac_schema())
    except Exception as err:  # noqa: BLE001
        logging.exception("init rbac failed")
        return _json({"error": str(err)}, 500)


@app.route(route="db-migrate", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def db_migrate(req: func.HttpRequest) -> func.HttpResponse:
    """สร้างตารางที่ Wave 1/3 ต้องใช้ (AuditLog / CoachJobs) — idempotent, admin เท่านั้น.

    GET  = ตรวจว่าขาดตารางไหน (ไม่แก้อะไร)
    POST = สร้างตารางที่ขาด

    มีเพราะเครื่องที่ deploy มักไม่มี SQL client และ Azure SQL อยู่หลัง Managed Identity
    ใช้แนวเดียวกับ /api/rbac-init ที่มีอยู่เดิม. ถ้า Managed Identity ไม่มีสิทธิ์ CREATE TABLE
    จะคืน error พร้อมบอกให้รันไฟล์ .sql เองแทน
    """
    try:
        u, deny = guard.gate(req, "db_migrate")
        if deny:
            return deny
        missing = db.missing_tables()
        if req.method == "GET":
            return _json({"missing": missing, "ok": not missing})
        created = []
        if "AuditLog" in missing and db.ensure_audit_schema():
            created.append("AuditLog")
        if "CoachJobs" in missing and db.ensure_coach_schema():
            created.append("CoachJobs")
        still = db.missing_tables()
        if created:
            audit.write(u, audit.SETTINGS_NETWORK, "settings", "db-migrate",
                        target_label="schema", before={"missing": missing}, after={"created": created})
        return _json({"created": created, "missing": still, "ok": not still})
    except Exception as err:  # noqa: BLE001
        logging.exception("db migrate failed")
        return _json({
            "error": f"{err}",
            "hint": "ถ้าเป็นเรื่องสิทธิ์ CREATE TABLE ให้รัน sql/migration_audit_log.sql "
                    "และ sql/migration_coach_jobs.sql ด้วย Entra admin แทน",
        }, 500)


@app.route(route="roles", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def roles_list(req: func.HttpRequest) -> func.HttpResponse:
    """R3 — list roles + permission matrix + user count (admin)."""
    try:
        u, deny = guard.gate(req, "roles_list")
        if deny:
            return deny
        return _json({"roles": db.list_roles(), "pages": list(db.PAGES)})
    except Exception as err:  # noqa: BLE001
        logging.exception("roles list failed")
        return _json({"error": str(err)}, 500)


@app.route(route="roles", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def roles_create(req: func.HttpRequest) -> func.HttpResponse:
    """R3 — สร้าง role ใหม่ (admin) — permission ทุกหน้าเริ่มต้น = ปิด."""
    try:
        u, deny = guard.gate(req, "roles_create")
        if deny:
            return deny
        name = (req.get_json().get("name") or "").strip()
        if not name:
            return _json({"error": "ต้องระบุชื่อ role"}, 400)
        if db.role_exists(name):
            return _json({"error": f"role '{name}' มีอยู่แล้ว"}, 400)
        db.create_role(name)
        return _json({"roles": db.list_roles(), "pages": list(db.PAGES)})
    except Exception as err:  # noqa: BLE001
        logging.exception("role create failed")
        return _json({"error": str(err)}, 500)


@app.route(route="roles/{role_id}", methods=["DELETE"], auth_level=func.AuthLevel.ANONYMOUS)
def roles_delete(req: func.HttpRequest) -> func.HttpResponse:
    """R3 — ลบ role (admin). Guard: system role ห้ามลบ + role ที่มี user ใช้อยู่ห้ามลบ."""
    try:
        u, deny = guard.gate(req, "roles_delete")
        if deny:
            return deny
        role = db.get_role_by_id(req.route_params.get("role_id"))
        if not role:
            return _json({"error": "ไม่พบ role"}, 404)
        if role["is_system"]:
            return _json({"error": "ลบ system role (admin) ไม่ได้"}, 400)
        n = db.count_users_with_role(role["name"])
        if n > 0:
            return _json({"error": f"มี user {n} คนใช้ role นี้อยู่ — ย้าย role ก่อนลบ"}, 400)
        db.delete_role(role["role_id"])
        return _json({"roles": db.list_roles(), "pages": list(db.PAGES)})
    except Exception as err:  # noqa: BLE001
        logging.exception("role delete failed")
        return _json({"error": str(err)}, 500)


@app.route(route="roles/{role_id}/permissions", methods=["PUT"], auth_level=func.AuthLevel.ANONYMOUS)
def roles_set_permissions(req: func.HttpRequest) -> func.HttpResponse:
    """R3 — set permission matrix (admin). Guard กันล็อกตัวเองออกจาก Settings."""
    try:
        u, deny = guard.gate(req, "roles_set_permissions")
        if deny:
            return deny
        role = db.get_role_by_id(req.route_params.get("role_id"))
        if not role:
            return _json({"error": "ไม่พบ role"}, 404)
        perms = {k: bool(v) for k, v in (req.get_json().get("permissions") or {}).items() if k in db.PAGES}
        before_perms = db.get_role_permissions(role["name"])
        # guard 1: system role (admin) ต้องคงสิทธิ์ Settings เสมอ (กัน admin ล็อกตัวเอง)
        if role["is_system"] and not perms.get("settings", True):
            return _json({"error": "ถอนสิทธิ์ Settings จาก system role (admin) ไม่ได้"}, 400)
        # guard 2: ต้องเหลืออย่างน้อย 1 role ที่เข้า Settings ได้เสมอ
        if "settings" in perms and not perms["settings"]:
            cur = before_perms.get("settings", False)
            remaining = db.count_roles_with_page("settings") - (1 if cur else 0)
            if remaining < 1:
                return _json({"error": "ต้องเหลืออย่างน้อย 1 role ที่เข้า Settings ได้"}, 400)
        db.set_role_permissions(role["role_id"], perms)
        audit.write(  # C03 — การแก้สิทธิ์เป็นการกระทำที่กระทบความปลอดภัย ต้องมีร่องรอย
            u, audit.ROLE_PERMS, "role", role["role_id"],
            target_label=role["name"], before=before_perms, after=perms,
        )
        return _json({"roles": db.list_roles(), "pages": list(db.PAGES)})
    except Exception as err:  # noqa: BLE001
        logging.exception("role set permissions failed")
        return _json({"error": str(err)}, 500)


@app.route(route="presentation-coach", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@app.queue_output(arg_name="msg", queue_name="coach-jobs", connection="AzureWebJobsStorage")
def presentation_coach(req: func.HttpRequest, msg: func.Out[str]) -> func.HttpResponse:
    """R4/G01 — ตั้งงานสร้าง guideline การนำเสนอตามกลุ่มผู้ฟัง แล้วรันเบื้องหลัง.

    เดิมเรียก LLM ใน HTTP request ตรง ๆ -> provider=local (20-30s+) เสี่ยงชนเพดาน
    ~230 วินาทีของ Functions. ตอนนี้ enqueue แล้วให้ frontend poll
    GET /api/presentation-coach/{job_id} (แบบเดียวกับ /api/evaluate).

    ผลเดิมที่เนื้อหา+ผู้ฟังตรงกันเป๊ะ -> คืนทันที ไม่เรียก LLM ซ้ำ (คุมต้นทุนโทเคน).
    """
    try:
        b = req.get_json()
        thread_id = b.get("thread_id")
        if not thread_id:
            return _json({"error": "ต้องระบุ thread_id"}, 400)
        # B02 — ต้องมีสิทธิ์หน้า proposals *และ* เข้าถึง thread นี้ได้ (ไม่งั้นอ่านเนื้อ proposal
        # ของคนอื่นผ่าน LLM ได้ + เผาโทเคนแทนคนอื่น)
        u, deny = guard.gate_thread(req, "presentation_coach", thread_id)
        if deny:
            return deny
        audience = (b.get("audience") or "").strip()
        custom = (b.get("custom_audience") or "").strip()
        # audience จาก preset map หรือ custom text ที่ผู้ใช้พิมพ์เอง (อย่างใดอย่างหนึ่ง)
        if audience in presentation.AUDIENCE:
            desc = presentation.AUDIENCE[audience]
        elif custom:
            desc = custom[:500]  # จำกัดความยาว กัน prompt บวม
        else:
            return _json({"error": "ต้องระบุ audience (preset) หรือ custom_audience (พิมพ์เอง)"}, 400)
        sub = db.latest_evaluated_submission(thread_id)
        if not sub or not sub.get("text_content"):
            return _json({"error": "ไม่พบเนื้อหา proposal ของรายการนี้"}, 404)

        # ภาษาเป็นส่วนหนึ่งของกุญแจ reuse: เนื้อหาเดิมแต่คนละภาษา = คนละผลลัพธ์
        # ผูกไว้ใน hash แทนการเพิ่มคอลัมน์ -> ไม่ต้อง migrate ตาราง CoachJobs
        chash = presentation.coach_cache_key(sub["text_content"], sub.get("lang"))
        reused = db.find_reusable_coach(thread_id, desc, chash)
        if reused:
            return _json({"status": "done", "job_id": reused["job_id"],
                          "guideline": reused["guideline"], "reused": True})

        job_id = db.create_coach_job(thread_id, desc, chash, u.get("email"))
        msg.set(json.dumps({"job_id": job_id}))
        return _json({"status": "processing", "job_id": job_id})
    except Exception as err:  # noqa: BLE001
        logging.exception("presentation coach failed")
        return _json({"error": str(err)}, 500)


@app.queue_trigger(arg_name="msg", queue_name="coach-jobs", connection="AzureWebJobsStorage")
def coach_worker(msg: func.QueueMessage) -> None:
    """G01 — สร้าง guideline เบื้องหลัง. เขียนสถานะ Done/Failed ลง dbo.CoachJobs."""
    job_id = json.loads(msg.get_body().decode("utf-8"))["job_id"]
    try:
        job = db.get_coach_job(job_id)
        if not job:
            logging.error("coach_worker: job %s not found", job_id)
            return
        sub = db.latest_evaluated_submission(job["thread_id"])
        if not sub or not sub.get("text_content"):
            db.finish_coach_job(job_id, None, "ไม่พบเนื้อหา proposal ของรายการนี้")
            return
        # ภาษาตามผลประเมินล่าสุดของ thread (คอลัมน์ lang ของ submission) ไม่ใช่ค่าคงที่
        db.finish_coach_job(job_id, presentation.coach_guideline(
            sub["text_content"], job["audience_desc"], sub.get("lang") or "th"))
    except Exception as err:  # noqa: BLE001
        logging.exception("coach_worker failed for %s", job_id)
        db.finish_coach_job(job_id, None, str(err))


@app.route(route="presentation-coach/{job_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def presentation_coach_status(req: func.HttpRequest) -> func.HttpResponse:
    """G01 — poll สถานะงาน coach: Processing | Done (+guideline) | Failed (+error)."""
    try:
        job = db.get_coach_job(req.route_params.get("job_id"))
        if not job:
            return _json({"error": "ไม่พบงานนี้"}, 404)
        # ตรวจสิทธิ์กับ thread ของงาน — ไม่ให้เดา job_id แล้วอ่าน guideline ของคนอื่น
        _, deny = guard.gate_thread(req, "presentation_coach_status", job["thread_id"])
        if deny:
            return deny
        return _json({"status": job["status"], "guideline": job["guideline"] or "",
                      "error": job["error_message"] or ""})
    except Exception as err:  # noqa: BLE001
        logging.exception("presentation coach status failed")
        return _json({"error": str(err)}, 500)


@app.route(route="masterdata", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def masterdata_list(req: func.HttpRequest) -> func.HttpResponse:
    """F45 — รายการ Solution Type / Industry (ทุก role อ่านได้ — ใช้เป็น dropdown)."""
    try:
        _, deny = guard.gate(req, "masterdata_list")  # AUTH_ONLY — ไม่ sensitive แต่ต้อง login
        if deny:
            return deny
        cat = req.params.get("category")
        return _json(db.list_master_data(cat))
    except Exception as err:  # noqa: BLE001
        logging.exception("masterdata list failed")
        return _json({"error": str(err)}, 500)


@app.route(route="masterdata", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def masterdata_add(req: func.HttpRequest) -> func.HttpResponse:
    """F45 — เพิ่มค่า master data (admin)."""
    try:
        u, deny = guard.gate(req, "masterdata_add")
        if deny:
            return deny
        b = req.get_json()
        cat, val = (b.get("category") or "").strip(), (b.get("value") or "").strip()
        if cat not in ("solution_type", "industry") or not val:
            return _json({"error": "category (solution_type/industry) + value จำเป็น"}, 400)
        db.add_master_data(cat, val)
        return _json(db.list_master_data())
    except Exception as err:  # noqa: BLE001
        logging.exception("masterdata add failed")
        return _json({"error": str(err)}, 500)


@app.route(route="masterdata/{mid}", methods=["DELETE"], auth_level=func.AuthLevel.ANONYMOUS)
def masterdata_delete(req: func.HttpRequest) -> func.HttpResponse:
    """F45 — ลบค่า master data (admin)."""
    try:
        u, deny = guard.gate(req, "masterdata_delete")
        if deny:
            return deny
        return _json({"ok": db.delete_master_data(req.route_params.get("mid")), "items": db.list_master_data()})
    except Exception as err:  # noqa: BLE001
        logging.exception("masterdata delete failed")
        return _json({"error": str(err)}, 500)


def _settings_view(u: dict) -> dict:
    """shape settings สำหรับ frontend.

    - ทุก role: default_lang, default_currency, llm_provider (ค่าตั้งต้น submit + provider ปัจจุบัน)
    - admin เพิ่ม: local_llm_ready (env พร้อมไหม) + local_llm_model (จาก env, read-only)
    local config (endpoint/token) ฝัง env ไม่เก็บ DB -> ไม่ส่งกลับ frontend เลย
    """
    s = db.get_settings()
    out = {
        "default_lang": s.get("default_lang", "th"),
        "default_currency": s.get("default_currency", "THB"),
        "llm_provider": s.get("llm_provider", "azure"),
        "active_model": llm.current_model(),  # ชื่อ model ปัจจุบัน (ทุก role เห็น — ไม่ sensitive)
    }
    if auth.require(u, "settings"):
        info = llm.local_info()
        out["local_llm_ready"] = info["ready"]
        out["local_llm_model"] = info["model"]
        # S02 — การจำกัดตามเน็ตเวิร์ก (ค่าตั้งด้านความปลอดภัย -> admin เท่านั้น)
        out["ip_restriction_enabled"] = str(s.get(guard.SETTING_IP_ENABLED, "0")).strip() == "1"
        out["ip_allowlist"] = s.get(guard.SETTING_IP_ALLOWLIST) or ""
        out["ip_kill_switch"] = guard.ip_kill_switch_active()
    return out


def _validate_network_settings(req: func.HttpRequest, allowed: dict) -> str | None:
    """S02 — ตรวจ + normalize ค่าจำกัดเน็ตเวิร์กก่อนบันทึก. คืนข้อความ error / None ถ้าผ่าน.

    กัน 3 กรณีที่เจ็บ:
      1) CIDR พิมพ์ผิด -> บอกให้แก้ ไม่บันทึกค่าเสีย
      2) เปิดสวิตช์แต่ allowlist ว่าง -> ไร้ความหมาย
      3) เปิดสวิตช์แต่ IP ของตัวเองไม่อยู่ในรายการ -> ล็อกตัวเองออก (ปฏิเสธไว้ก่อน)
    """
    if not any(k in allowed for k in guard.NETWORK_SETTING_KEYS):
        return None
    stored = db.get_settings()

    if guard.SETTING_IP_ENABLED in allowed:
        raw = str(allowed[guard.SETTING_IP_ENABLED]).strip().lower()
        allowed[guard.SETTING_IP_ENABLED] = "1" if raw in ("1", "true", "on", "yes") else "0"
        enabled = allowed[guard.SETTING_IP_ENABLED] == "1"
    else:
        enabled = str(stored.get(guard.SETTING_IP_ENABLED, "0")).strip() == "1"

    raw_list = allowed.get(guard.SETTING_IP_ALLOWLIST, stored.get(guard.SETTING_IP_ALLOWLIST))
    nets, bad = guard.parse_allowlist(raw_list)
    if bad:
        return f"รายการ IP/CIDR ไม่ถูกต้อง: {', '.join(bad[:5])}"
    if guard.SETTING_IP_ALLOWLIST in allowed:
        # normalize ให้เก็บรูปแบบมาตรฐาน อ่านง่ายและเทียบได้แน่นอน
        allowed[guard.SETTING_IP_ALLOWLIST] = ", ".join(str(n) for n in nets)

    if enabled:
        if not nets:
            return "เปิดการจำกัด IP ต้องกรอกรายการ IP/CIDR ที่อนุญาตอย่างน้อย 1 รายการ"
        my_ip = auth.client_ip(req)
        if not guard.ip_kill_switch_active() and not guard.ip_allowed(my_ip, nets):
            return (
                f"IP ที่คุณกำลังเรียกอยู่ ({my_ip or 'ตรวจไม่พบ'}) ไม่อยู่ในรายการที่อนุญาต — "
                "เพิ่มเข้าไปก่อนเปิดสวิตช์ ไม่งั้นจะล็อกตัวเองออกจากระบบ"
            )
    return None


@app.route(route="settings", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def settings_get(req: func.HttpRequest) -> func.HttpResponse:
    """F46 — audit defaults + LLM provider (secret masked; LLM config เฉพาะ admin)."""
    try:
        u, deny = guard.gate(req, "settings_get")  # AUTH_ONLY — ทุก role อ่าน active_model ได้
        if deny:
            return deny
        return _json(_settings_view(u))
    except Exception as err:  # noqa: BLE001
        logging.exception("settings get failed")
        return _json({"error": str(err)}, 500)


@app.route(route="settings", methods=["PUT"], auth_level=func.AuthLevel.ANONYMOUS)
def settings_put(req: func.HttpRequest) -> func.HttpResponse:
    """F46/R2 — แก้ audit defaults + LLM provider config (admin)."""
    try:
        u, deny = guard.gate(req, "settings_put")
        if deny:
            return deny
        allowed_keys = (
            ("default_lang", "default_currency") + llm.LLM_SETTING_KEYS + guard.NETWORK_SETTING_KEYS
        )
        allowed = {k: v for k, v in req.get_json().items() if k in allowed_keys}

        # S02 — ตรวจค่าจำกัดเน็ตเวิร์กก่อนบันทึก + กัน admin ล็อกตัวเองออก
        net_err = _validate_network_settings(req, allowed)
        if net_err:
            return _json({"error": net_err}, 400)
        # สลับไป local ต้อง: endpoint env พร้อม + เลือก model แล้ว (จาก body หรือค่าเดิมใน DB)
        if str(allowed.get("llm_provider", "")).strip().lower() == "local":
            if not llm.local_env_ready():
                return _json({"error": "Local endpoint ไม่พร้อม — ตั้ง env LOCAL_LLM_BASE_URL บน Function App"}, 400)
            chosen = (allowed.get("local_llm_model") or db.get_settings().get("local_llm_model") or "").strip()
            if not chosen:
                return _json({"error": "กรุณาเลือก Local LLM model ก่อนสลับไป Local"}, 400)
            # กัน bug: สลับ local ทั้งที่ Azure ต่อ server ไม่ถึง -> upload/audit จะ hang เงียบ
            reachable = llm.list_models()
            if not reachable:
                return _json({"error": "Azure ต่อ Local server ไม่ได้ (ตรวจ firewall/network) — ยังสลับไป Local ไม่ได้"}, 400)
            if chosen not in reachable:
                return _json({"error": f"ไม่พบ model '{chosen}' บน server (มี: {', '.join(reachable)})"}, 400)

        # การเปลี่ยนค่าจำกัดเน็ตเวิร์กเป็นการกระทำด้านความปลอดภัย -> เก็บ audit
        net_changed = {k: v for k, v in allowed.items() if k in guard.NETWORK_SETTING_KEYS}
        before_net = (
            {k: db.get_settings().get(k) for k in net_changed} if net_changed else {}
        )
        db.put_settings(allowed)
        if net_changed:
            audit.write(
                u, audit.SETTINGS_NETWORK, "settings", "network",
                target_label="ip_restriction", before=before_net, after=net_changed,
            )
        return _json(_settings_view(u))
    except Exception as err:  # noqa: BLE001
        logging.exception("settings put failed")
        return _json({"error": str(err)}, 500)


@app.route(route="llm/models", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def llm_models(req: func.HttpRequest) -> func.HttpResponse:
    """R2 — รายชื่อ model จาก local server ให้ UI เลือก (admin). ต่อไม่ได้ -> models: []."""
    try:
        u, deny = guard.gate(req, "llm_models")
        if deny:
            return deny
        return _json({"ready": llm.local_env_ready(), "models": llm.list_models()})
    except Exception as err:  # noqa: BLE001
        logging.exception("llm models failed")
        return _json({"error": str(err)}, 500)


@app.route(route="library", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def library_list(req: func.HttpRequest) -> func.HttpResponse:
    """F31 — รายการ Proposal Library (manager+ เท่านั้น)."""
    try:
        u, deny = guard.gate(req, "library_list")
        if deny:
            return deny
        return _json(db.list_library())
    except Exception as err:  # noqa: BLE001
        logging.exception("library list failed")
        return _json({"error": str(err)}, 500)


@app.route(route="library/{thread_id}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def library_detail(req: func.HttpRequest) -> func.HttpResponse:
    """F32 — content เต็ม + SAS link ไฟล์ version ล่าสุด (สิทธิ์ library เท่านั้น).

    A03 — เดิม endpoint นี้ไม่ตรวจสิทธิ์เลย ทำให้ผู้ใช้ทุก role อ่าน "ต้นทุนภายใน" ของทุกดีลได้
    ไม่ใช้กฎความเป็นเจ้าของ (D1) เพราะจุดประสงค์ของ Library คือเทียบราคาข้ามดีล
    """
    try:
        _, deny = guard.gate(req, "library_detail")
        if deny:
            return deny
        thread_id = req.route_params.get("thread_id")
        item = db.get_library_item(thread_id)
        if item is None:
            return _json({"error": "thread not found"}, 404)
        prior = db.latest_evaluated_submission(thread_id)
        item["filename"] = prior.get("filename", "") if prior else ""
        item["file_url"] = _sas_url(prior.get("blob_url", "")) if prior else ""
        return _json(item)
    except Exception as err:  # noqa: BLE001
        logging.exception("library detail failed")
        return _json({"error": str(err)}, 500)


@app.route(route="library/{thread_id}", methods=["PATCH"], auth_level=func.AuthLevel.ANONYMOUS)
def library_update(req: func.HttpRequest) -> func.HttpResponse:
    """F33 — แก้/ยืนยัน project content (รวม Deal Outcome). สร้าง record ว่างให้ถ้ายังไม่มี.

    A03 — เดิมไม่ตรวจสิทธิ์เลย: ทุก role แก้ราคา/ต้นทุน และกด verify ของดีลใครก็ได้
    D02 — ชื่อผู้ยืนยัน (verified_by) มาจาก principal ฝั่ง server ไม่รับจาก body
    C03 — บันทึก audit ทุกครั้ง พร้อมค่าเดิม -> ค่าใหม่
    """
    try:
        u, deny = guard.gate(req, "library_update")
        if deny:
            return deny
        thread_id = req.route_params.get("thread_id")
        b = req.get_json()
        outcome = b.get("deal_outcome")
        if outcome is not None and outcome not in ("Won", "Lost", "Pending"):
            return _json({"error": "deal_outcome ต้องเป็น Won/Lost/Pending"}, 400)

        verify = bool(b.get("verify"))
        actor = u.get("email") or u.get("name") or "unknown"
        before = db.get_library_item(thread_id)
        if before is None:
            return _json({"error": "thread not found"}, 404)

        db.create_empty_content(thread_id)  # no-op ถ้ามีอยู่แล้ว
        db.update_library_item(thread_id, b, verify=verify, author=actor)
        after = db.get_library_item(thread_id)
        audit.write(
            u, audit.CONTENT_VERIFY if verify else audit.CONTENT_UPDATE,
            "thread", thread_id, target_label=(before or {}).get("ticket_no"),
            before=_content_snapshot(before), after=_content_snapshot(after),
        )
        return _json(after)
    except Exception as err:  # noqa: BLE001
        logging.exception("library update failed")
        return _json({"error": str(err)}, 500)


@app.route(route="library/backfill", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def library_backfill(req: func.HttpRequest) -> func.HttpResponse:
    """F37 (ส่วน extraction) — ไล่ extract thread เก่าที่ยังไม่มี content.

    ส่วน sync ไป SharePoint รอ M3 (admin consent). รันซ้ำได้ — ข้าม thread ที่มี content แล้ว.

    A05 — จำกัดสิทธิ์ settings (admin): endpoint นี้ปลุกงาน LLM ทุก thread ที่ยังไม่มี content
    ในคำขอเดียว เดิมใครก็เรียกได้ = เผาโทเคนได้ไม่จำกัด
    """
    try:
        _, deny = guard.gate(req, "library_backfill")
        if deny:
            return deny
        targets = db.threads_missing_content()
        done, failed = 0, []
        for t in targets:
            try:
                _extract_and_store_content(
                    t["thread_id"], t["submission_id"], t["content_hash"] or "", t["text_content"]
                )
                done += 1
            except Exception as err:  # noqa: BLE001
                failed.append({"thread_id": t["thread_id"], "error": str(err)})
        return _json({"total": len(targets), "done": done, "failed": failed})
    except Exception as err:  # noqa: BLE001
        logging.exception("library backfill failed")
        return _json({"error": str(err)}, 500)


# ===================== Audit trail (Wave 1 / C04) =====================

@app.route(route="audit", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def audit_list(req: func.HttpRequest) -> func.HttpResponse:
    """C04 — อ่านร่องรอยการตรวจสอบ (สิทธิ์ settings). กรองด้วย ?thread_id= หรือ ?actor= ได้.

    ยังไม่มีตาราง (ยังไม่รัน migration_audit_log.sql) -> คืน items ว่าง + ready:false
    ให้ UI แสดงสถานะได้ ไม่ใช่ 500.
    """
    try:
        _, deny = guard.gate(req, "audit_list")
        if deny:
            return deny
        try:
            rows = db.list_audit(
                thread_id=req.params.get("thread_id"),
                actor_email=req.params.get("actor"),
                limit=int(req.params.get("limit") or 200),
            )
        except Exception:  # noqa: BLE001 — ตารางยังไม่ถูกสร้าง
            logging.exception("audit table unavailable — รัน sql/migration_audit_log.sql แล้วหรือยัง")
            return _json({"ready": False, "items": []})
        return _json({"ready": True, "items": rows})
    except Exception as err:  # noqa: BLE001
        logging.exception("audit list failed")
        return _json({"error": str(err)}, 500)


# ===================== Playbook (คู่มือการใช้งาน — ทุก role อ่านได้) =====================

@app.route(route="playbook", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def playbook_list(req: func.HttpRequest) -> func.HttpResponse:
    """รายการไฟล์คู่มือ + ลิงก์เปิด/ดาวน์โหลด — ทุกคนที่ login เข้าได้ (AUTH_ONLY).

    ตั้งใจ *ไม่* ผูกกับ page permission ใด: คู่มือคือสิ่งที่ทุก role ต้องอ่านได้
    (คนที่เพิ่ง login ครั้งแรกได้ role `user` ก็ต้องหาวิธีใช้งานได้เอง).

    ยังไม่มีไฟล์ / ตั้ง BLOB_CONNECTION_STRING ไม่ครบ -> คืน items ว่าง + ready:false
    ให้ UI บอกสถานะได้ ไม่ใช่ 500 (แนวเดียวกับ audit_list)
    """
    try:
        _, deny = guard.gate(req, "playbook_list")
        if deny:
            return deny
        try:
            items = _playbook_items()
        except Exception:  # noqa: BLE001 — container/env ไม่พร้อม ไม่ควรทำหน้าจอพัง
            logging.exception("playbook list unavailable")
            return _json({"ready": False, "items": [],
                          # ข้อความนี้แสดงบนหน้า Playbook ซึ่งเป็นภาษาอังกฤษทั้งหน้า -> hint ต้องอังกฤษด้วย
                          "hint": "Cannot read the playbook store yet — check BLOB_CONNECTION_STRING on the Function App."})
        return _json({"ready": True, "items": items})
    except Exception as err:  # noqa: BLE001
        logging.exception("playbook list failed")
        return _json({"error": str(err)}, 500)


@app.route(route="playbook", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def playbook_upload(req: func.HttpRequest) -> func.HttpResponse:
    """อัปโหลด/แทนที่ไฟล์คู่มือ (สิทธิ์ settings) — ชื่อไฟล์เดิมซ้ำ = ทับของเก่า.

    set content_type ตอนอัปโหลด (ต่างจาก `_upload_blob` ของ proposal ที่ไม่ set)
    เพื่อให้ PDF เปิดอ่านในเบราว์เซอร์ได้เลย ไม่ถูกบังคับดาวน์โหลด
    """
    try:
        me, deny = guard.gate(req, "playbook_upload")
        if deny:
            return deny
        file = req.files.get("file")
        if file is None:
            return _json({"error": "missing file"}, 400)
        name = _safe_playbook_name(file.filename or "")
        if not name:
            return _json({"error": f"ชื่อ/ชนิดไฟล์ไม่รองรับ (รับ {', '.join(sorted(_PLAYBOOK_TYPES))})"}, 415)
        data = file.stream.read()
        if not data:
            return _json({"error": "ไฟล์ว่าง"}, 400)
        if len(data) > _PLAYBOOK_MAX_BYTES:
            return _json({"error": f"ไฟล์ใหญ่เกิน {_PLAYBOOK_MAX_BYTES // (1024 * 1024)}MB"}, 413)

        ext = os.path.splitext(name)[1].lower()
        ctype = _PLAYBOOK_TYPES[ext]
        settings = ContentSettings(
            content_type=ctype,
            # PDF/MD อ่านในเบราว์เซอร์ได้ -> inline; PPTX/DOCX เบราว์เซอร์เปิดไม่ได้ ปล่อยให้ดาวน์โหลด
            content_disposition="inline" if ext in (".pdf", ".md") else None,
        )
        blob = _playbook_container().get_blob_client(f"{_PLAYBOOK_PREFIX}/{name}")
        blob.upload_blob(data, overwrite=True, content_settings=settings)

        audit.write(me, audit.PLAYBOOK_UPLOAD, "playbook", name, name,
                    after={"size": len(data), "content_type": ctype})
        return _json({"ready": True, "items": _playbook_items()})
    except Exception as err:  # noqa: BLE001
        logging.exception("playbook upload failed")
        return _json({"error": str(err)}, 500)


@app.route(route="playbook/{name}", methods=["DELETE"], auth_level=func.AuthLevel.ANONYMOUS)
def playbook_delete(req: func.HttpRequest) -> func.HttpResponse:
    """ลบไฟล์คู่มือออกจากคลัง (สิทธิ์ settings)."""
    try:
        me, deny = guard.gate(req, "playbook_delete")
        if deny:
            return deny
        name = _safe_playbook_name(req.route_params.get("name") or "")
        if not name:
            return _json({"error": "ชื่อไฟล์ไม่ถูกต้อง"}, 400)
        blob = _playbook_container().get_blob_client(f"{_PLAYBOOK_PREFIX}/{name}")
        if not blob.exists():
            return _json({"error": "ไม่พบไฟล์นี้"}, 404)
        blob.delete_blob()
        audit.write(me, audit.PLAYBOOK_DELETE, "playbook", name, name)
        return _json({"ready": True, "items": _playbook_items()})
    except Exception as err:  # noqa: BLE001
        logging.exception("playbook delete failed")
        return _json({"error": str(err)}, 500)


# ===================== Startup self-check (Wave 1 / A02) =====================
# ⛔ ห้ามเรียก guard.audit_declarations(app) ที่ระดับโมดูล
#
# เดิมมีบรรทัด `_UNDECLARED = guard.audit_declarations(app)` ตรงนี้ ซึ่งเรียก
# app.get_functions() ตอน import. Azure Functions Python v2 ใช้ get_functions()
# เองตอน index -> การเรียกก่อนทำให้ deploy แล้ว "index ได้ 0 function" = แอปล่มทั้งระบบ
# (พบจริงตอน deploy 2026-08-02: az functionapp function list คืน 0 รายการ)
#
# การป้องกัน fail-closed ไม่ได้หายไป — guard.gate() ยังปฏิเสธ 403 ทันทีสำหรับ endpoint
# ที่ไม่มีชื่อใน ROUTE_PERMS. ที่หายไปคือ "log เตือนตอน start" ซึ่งเป็นแค่ความสะดวก
#
# ต้องการตรวจว่าประกาศสิทธิ์ครบไหม -> ตรวจแบบ static ตอน dev (ไม่ต้องรัน Azure):
#   python3 - <<'PY'
#   import re, pathlib
#   src = pathlib.Path("function_app.py").read_text(encoding="utf-8")
#   g   = pathlib.Path("shared/guard.py").read_text(encoding="utf-8")
#   h = re.findall(r'@app\.(?:route|queue_trigger)\([^)]*\)\s*(?:@app\.[a-z_]+\([^)]*\)\s*)*def (\w+)\(', src)
#   d = set(re.findall(r'^\s*"(\w+)":', g.split('ROUTE_PERMS: dict[str, str] = {')[1].split('\n}')[0], re.M))
#   nh = set(re.findall(r'"(\w+)"', g.split('NON_HTTP_FUNCTIONS = frozenset({')[1].split('})')[0]))
#   print("undeclared:", [x for x in h if x not in d and x not in nh] or "none")
#   PY
