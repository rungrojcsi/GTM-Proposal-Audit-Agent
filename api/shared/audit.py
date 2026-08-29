"""ร่องรอยการตรวจสอบ (audit trail) — Wave 1 / C02-C03.

บันทึกเฉพาะการกระทำที่ "เขียน" ข้อมูลสำคัญ 6 อย่าง (ขอบเขต D2) — ไม่บันทึกการอ่าน.
ผู้กระทำมาจาก x-ms-client-principal ฝั่ง server เท่านั้น ไม่เคยรับจาก request body.

หลักสำคัญ (E4): เขียน audit ล้มเหลว "ห้าม" ทำให้งานของผู้ใช้พัง — เช่นกรณี deploy โค้ด
ก่อนรัน migration_audit_log.sql. ทุก write() จึงกลืน exception แล้ว log ไว้แทน.
"""
from __future__ import annotations

import json
import logging

from . import db

# ค่า action ที่ใช้ได้ — คุมให้เป็นชุดปิด เพื่อ query/report ได้แน่นอน
CONTENT_UPDATE = "content.update"
CONTENT_VERIFY = "content.verify"
THREAD_RENAME = "thread.rename"
THREAD_DELETE = "thread.delete"
USER_ROLE = "user.role"
ROLE_PERMS = "role.perms"
SETTINGS_NETWORK = "settings.network"   # S02 — เปิด/ปิดหรือแก้รายการ IP ที่อนุญาต
PLAYBOOK_UPLOAD = "playbook.upload"     # เปลี่ยนไฟล์คู่มือที่ทุก role มองเห็น
PLAYBOOK_DELETE = "playbook.delete"


def _dump(value: object | None) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(value)


def write(
    actor: dict,
    action: str,
    target_type: str,
    target_id: str | None,
    target_label: str | None = None,
    before: object | None = None,
    after: object | None = None,
) -> None:
    """บันทึก 1 เหตุการณ์. ล้มเหลว -> log แล้วปล่อยผ่าน (ห้าม raise)."""
    try:
        db.insert_audit(
            actor_user_id=actor.get("user_id"),
            actor_email=actor.get("email"),
            actor_role=actor.get("role"),
            actor_ip=actor.get("ip"),  # S03 — guard.gate ใส่ค่านี้ให้ใน user dict

            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            target_label=target_label,
            before_json=_dump(before),
            after_json=_dump(after),
        )
    except Exception:  # noqa: BLE001 — E4: audit พังห้ามทำงานผู้ใช้พัง
        logging.exception(
            "audit write failed (action=%s target=%s/%s) — ตรวจว่ารัน migration_audit_log.sql แล้วหรือยัง",
            action, target_type, target_id,
        )
