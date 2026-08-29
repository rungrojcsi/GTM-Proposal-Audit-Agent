"""ชั้นบังคับสิทธิ์ (authorization guard) — Wave 1 / A01-A03, B01-B03.

ทำไมต้องมีไฟล์นี้
-----------------
Static Web Apps บังคับแค่ "ยืนยันตัวตน" (authentication) ว่า login แล้วหรือยัง
แต่ไม่ได้ตรวจ "สิทธิ์" (authorization) ว่า role นั้นทำได้จริงไหม. เดิมแต่ละ handler
ต้องจำเองว่าต้องเรียก auth.require() -> ลืมได้ -> เกิดช่องโหว่ 8 จุด.

หลักการที่เปลี่ยน: จาก "ลืมเช็กแล้วผ่าน" (fail-open) เป็น "ลืมเช็กแล้วพัง" (fail-closed)
  - ทุก endpoint ต้องมีชื่อตัวเองอยู่ใน ROUTE_PERMS
  - ชื่อที่ไม่อยู่ในตาราง -> gate() ปฏิเสธ 403 ทันที (ไม่ใช่ปล่อยผ่าน)
  - audit_declarations() ตรวจตอนเริ่มระบบว่ามี endpoint ไหนลืมประกาศ -> log ERROR

ทำไมไม่ใช้ decorator
--------------------
Azure Functions Python v2 อ่าน signature/annotation ของฟังก์ชันเพื่อผูก parameter
(req: HttpRequest, msg: Out[str]). การครอบ decorator เพิ่มมีความเสี่ยงทำ binding พัง
และเราไม่มี runtime ให้ทดสอบในเครื่อง -> เลือกวิธีเรียก gate() ต้นฟังก์ชันแทน
ซึ่งไม่แตะกลไก binding เลย แต่ยังได้ fail-closed จาก audit_declarations().
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os

import azure.functions as func

from . import auth, db

# ---------------------------------------------------------------------------
# S02 — จำกัดตามเน็ตเวิร์กระดับแอป (ทางเลือก, ค่าเริ่มต้น "ปิด")
#
# ย้ายแนวคิด "เข้าได้เฉพาะเน็ตเวิร์กภายใน" จากชั้นโครงสร้างพื้นฐาน (Azure access
# restrictions) มาเป็นค่าตั้งในแอป เพื่อให้ admin เปิด/ปิดจากหน้า Settings ได้เอง
# ไม่ต้องเข้า Azure Portal.
#
# ⚠️ นี่ *ไม่ใช่* สิ่งที่ทำให้ Function App ปลอดภัยจากการปลอม principal —
# เรื่องนั้นยังต้องพึ่งข้อจำกัดเน็ตเวิร์กที่ Azure (ดู shared/auth.py). ตัวนี้เป็น
# ชั้นเสริมสำหรับจำกัดว่า "ผู้ใช้จากที่ไหนเรียกได้" เท่านั้น
# ---------------------------------------------------------------------------
SETTING_IP_ENABLED = "ip_restriction_enabled"   # "1" = เปิด, อื่น ๆ/ไม่มี = ปิด (default)
SETTING_IP_ALLOWLIST = "ip_allowlist"           # CIDR คั่นด้วย comma เช่น "203.0.113.0/24, 10.0.0.0/8"
NETWORK_SETTING_KEYS = (SETTING_IP_ENABLED, SETTING_IP_ALLOWLIST)

# break-glass: ตั้ง env นี้บน Function App เพื่อปิดการตรวจ IP ฉุกเฉิน
# (ใช้เมื่อกรอก CIDR ผิดจนล็อกตัวเองออก และแก้จาก Settings ไม่ได้)
_IP_KILL_SWITCH = os.environ.get("IP_RESTRICTION_OFF") == "1"

# endpoint ที่ยกเว้นการตรวจ IP เสมอ — กันล็อกตัวเองออกจากทางแก้
#   health      : liveness probe ของ Azure มาจาก IP ที่เราคาดเดาไม่ได้
#   me          : frontend ต้องรู้ตัวตนเพื่อ render หน้า/เด้ง login
#   settings_*   : ต้องเข้าไปปิดสวิตช์ได้เสมอ
_IP_EXEMPT = frozenset({"health", "me", "settings_get", "settings_put"})

# ค่าพิเศษของ ROUTE_PERMS (ไม่ใช่ page_key จริงใน db.PAGES)
PUBLIC = "__public__"      # ไม่ต้อง login — health probe / me (ต้องคืน authenticated:false ได้)
AUTH_ONLY = "__auth__"     # ต้อง login แต่ไม่ผูก page permission ใด

# ---------------------------------------------------------------------------
# ทะเบียนสิทธิ์ต่อ endpoint — key = ชื่อฟังก์ชัน handler ใน function_app.py
# แก้ที่นี่จุดเดียว. เพิ่ม endpoint ใหม่แล้วไม่ใส่ที่นี่ = ถูกปฏิเสธ 403 โดยปริยาย
# ---------------------------------------------------------------------------
ROUTE_PERMS: dict[str, str] = {
    # --- ไม่ต้อง login ---
    "health": PUBLIC,
    "me": PUBLIC,                       # ต้องตอบได้แม้ยัง guest -> frontend ใช้ตัดสินใจเด้ง /login
    # --- login พอ (ข้อมูลไม่ sensitive / ใช้เป็น dropdown ทุก role) ---
    "masterdata_list": AUTH_ONLY,
    "settings_get": AUTH_ONLY,          # ทุก role อ่าน default_lang/active_model
    "submission_status": AUTH_ONLY,     # + ตรวจเจ้าของผ่าน submission -> thread
    "comments": AUTH_ONLY,              # + ตรวจเจ้าของจาก thread_id ใน body
    "playbook_list": AUTH_ONLY,         # คู่มือการใช้งาน — ทุก role ต้องอ่านได้ ไม่ผูก page permission
    # --- ต้องมีสิทธิ์หน้า ---
    "prepare": "evaluate",
    "evaluate": "evaluate",
    "proposals": "proposals",
    "thread_detail": "proposals",
    "history": "proposals",
    "presentation_coach": "proposals",
    "presentation_coach_status": "proposals",   # G01 — poll สถานะงาน coach
    "thread_update": "manage_proposals",
    "thread_delete": "manage_proposals",
    "dashboard": "dashboard",
    "library_list": "library",
    "library_detail": "library",
    "library_update": "library",
    "library_backfill": "settings",     # ปลุกงาน LLM ทั้งฐานข้อมูล -> admin เท่านั้น
    "users_list": "settings",
    "users_add": "settings",
    "users_set_role": "settings",
    "admin_init_rbac": "settings",
    "roles_list": "settings",
    "roles_create": "settings",
    "roles_delete": "settings",
    "roles_set_permissions": "settings",
    "masterdata_add": "settings",
    "masterdata_delete": "settings",
    "settings_put": "settings",
    "playbook_upload": "settings",      # เปลี่ยนไฟล์คู่มือที่ทุกคนเห็น -> admin เท่านั้น
    "playbook_delete": "settings",
    "llm_models": "settings",
    "audit_list": "settings",           # C04 — อ่านร่องรอยการตรวจสอบ
    "db_migrate": "settings",           # สร้างตาราง AuditLog/CoachJobs (idempotent)
}

# queue trigger ไม่ใช่ HTTP endpoint — ไม่ต้องมีสิทธิ์ (ยกเว้นจากการตรวจทะเบียน)
NON_HTTP_FUNCTIONS = frozenset({"evaluate_worker", "coach_worker"})


def _deny(message: str, status: int) -> func.HttpResponse:
    """รูปแบบ error เดียวกันทุกจุด (B03) — frontend อ่าน .error ได้เหมือน endpoint อื่น."""
    return func.HttpResponse(
        json.dumps({"error": message}, ensure_ascii=False),
        status_code=status,
        mimetype="application/json",
    )


def ip_kill_switch_active() -> bool:
    """env IP_RESTRICTION_OFF=1 ถูกตั้งไว้ไหม (ให้ UI แจ้งว่าการตรวจ IP ถูกปิดจาก env)."""
    return _IP_KILL_SWITCH


def parse_allowlist(raw: str | None) -> tuple[list, list[str]]:
    """แปลงข้อความ CIDR คั่น comma -> (รายการ network, รายการที่ผิดรูป).

    รับได้ทั้ง CIDR ("10.0.0.0/8") และ IP เดี่ยว ("203.0.113.7" -> /32).
    """
    nets, bad = [], []
    for token in (raw or "").replace("\n", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            bad.append(token)
    return nets, bad


def ip_allowed(ip: str, nets: list) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def check_network(req: func.HttpRequest, fn_name: str) -> func.HttpResponse | None:
    """S02 — ตรวจ IP ผู้เรียกกับ allowlist ถ้าสวิตช์เปิด. คืน None ถ้าผ่าน.

    ปิดโดยค่าเริ่มต้น -> ระบบทำงานแบบเปิดสาธารณะ พึ่ง SSO + สิทธิ์หน้า.
    อ่านค่าตั้งล้มเหลว (DB ล่ม) -> ปล่อยผ่าน (fail-open) โดยเจตนา: ตัวนี้เป็นชั้นเสริม
    ไม่ใช่ชั้นหลัก การทำ fail-closed จะทำให้ DB ล่มแล้วทั้งระบบใช้ไม่ได้
    """
    if _IP_KILL_SWITCH or fn_name in _IP_EXEMPT:
        return None
    try:
        s = db.get_settings()
    except Exception:  # noqa: BLE001 — ชั้นเสริม: DB อ่านไม่ได้ ไม่ควรล้มทั้งระบบ
        logging.exception("check_network: อ่าน settings ไม่ได้ -> ข้ามการตรวจ IP")
        return None
    if str(s.get(SETTING_IP_ENABLED, "0")).strip() != "1":
        return None
    nets, _bad = parse_allowlist(s.get(SETTING_IP_ALLOWLIST))
    if not nets:
        # เปิดสวิตช์แต่ไม่ได้กรอก allowlist -> ถือว่ายังไม่ตั้งค่าเสร็จ อย่าล็อกทุกคนออก
        logging.warning("check_network: เปิดสวิตช์แต่ ip_allowlist ว่าง -> ข้ามการตรวจ")
        return None
    ip = auth.client_ip(req)
    if ip_allowed(ip, nets):
        return None
    logging.warning("check_network: ปฏิเสธ IP %s (endpoint=%s)", ip or "unknown", fn_name)
    return _deny("เรียกจากเครือข่ายนี้ไม่ได้ (ถูกจำกัดด้วยรายการ IP ที่อนุญาต)", 403)


def gate(req: func.HttpRequest, fn_name: str) -> tuple[dict, func.HttpResponse | None]:
    """ตรวจสิทธิ์หน้า. คืน (user, None) ถ้าผ่าน / (user, response) ถ้าไม่ผ่าน.

    ใช้เป็นบรรทัดแรกของทุก handler:
        u, deny = guard.gate(req, "library_detail")
        if deny:
            return deny

    user ที่คืนมาใช้ต่อได้เลย ไม่ต้องเรียก auth.current_user ซ้ำ (ประหยัด DB round-trip)
    """
    required = ROUTE_PERMS.get(fn_name)

    if required is None:
        # fail-closed: endpoint ที่ลืมประกาศสิทธิ์ ต้องถูกปฏิเสธ ไม่ใช่ปล่อยผ่าน
        logging.error("SECURITY: endpoint '%s' has no entry in guard.ROUTE_PERMS -> denied", fn_name)
        return {"user_id": None, "email": None, "name": "Guest", "role": "guest",
                "authenticated": False}, _deny("endpoint นี้ยังไม่ได้ประกาศสิทธิ์ในระบบ", 403)

    # S02 — ชั้นเสริม: จำกัดตาม IP ถ้า admin เปิดสวิตช์ไว้ (ค่าเริ่มต้นปิด)
    net_deny = check_network(req, fn_name)
    if net_deny:
        return {"user_id": None, "email": None, "name": "Guest", "role": "guest",
                "authenticated": False}, net_deny

    u = auth.current_user(req)
    u["ip"] = auth.client_ip(req)  # S03 — ให้ audit.write บันทึกได้โดยไม่ต้องแก้ทุก call site

    if required == PUBLIC:
        return u, None

    if not u.get("authenticated"):
        return u, _deny("ต้องเข้าสู่ระบบก่อน", 401)

    if required == AUTH_ONLY:
        return u, None

    if not auth.require(u, required):
        return u, _deny("ไม่มีสิทธิ์เข้าถึงรายการนี้", 403)

    return u, None


def thread_access(user: dict, thread_id: str | None) -> func.HttpResponse | None:
    """ตรวจความเป็นเจ้าของ thread (B01). คืน None ถ้าเข้าถึงได้ / response ถ้าไม่ได้.

    กฎ: มีสิทธิ์ view_all -> เข้าได้ทุก thread. ไม่มี -> ต้องเป็น owner_id ของ thread นั้น.
    หมายเหตุ: หน้า Proposal Library ตั้งใจ "ไม่" ใช้กฎนี้ (ตัดสินใจ D1) เพราะจุดประสงค์
    คือเทียบราคา/ต้นทุนข้ามดีล — กำแพงคือสิทธิ์ `library` เอง.
    """
    if not thread_id:
        return _deny("ต้องระบุ thread_id", 400)
    if auth.has_page(user["role"], "view_all"):
        return None
    owner_id = db.get_thread_owner(thread_id)
    if owner_id is None:
        # thread เก่าที่ยังไม่มี owner (owner_id nullable ตาม schema) — ไม่ให้ผู้ที่ไม่มี view_all เข้า
        return _deny("ไม่มีสิทธิ์เข้าถึงรายการนี้", 403)
    if str(owner_id).lower() != str(user.get("user_id") or "").lower():
        return _deny("ไม่มีสิทธิ์เข้าถึงรายการนี้", 403)
    return None


def gate_thread(
    req: func.HttpRequest, fn_name: str, thread_id: str | None
) -> tuple[dict, func.HttpResponse | None]:
    """gate() + thread_access() รวบเป็นครั้งเดียว — ใช้กับ endpoint ที่อ้างถึง thread เจาะจง."""
    u, deny = gate(req, fn_name)
    if deny:
        return u, deny
    return u, thread_access(u, thread_id)


def audit_declarations(app: func.FunctionApp) -> list[str]:
    """A02 — ตรวจตอนเริ่มระบบว่ามี HTTP endpoint ไหนลืมประกาศสิทธิ์ใน ROUTE_PERMS.

    คืนรายชื่อที่ลืม (ควรว่างเสมอ). ห่อ try/except เพราะ API ของ FunctionApp
    อาจต่างกันตามเวอร์ชัน worker — การตรวจนี้เป็น safety net ห้ามทำ startup ล้ม.
    """
    missing: list[str] = []
    try:
        for f in app.get_functions():
            name = f.get_function_name()
            if name in NON_HTTP_FUNCTIONS or name in ROUTE_PERMS:
                continue
            missing.append(name)
    except Exception:  # noqa: BLE001 — safety net ห้ามทำ startup พัง
        logging.exception("guard.audit_declarations skipped (FunctionApp API mismatch)")
        return []
    return sorted(missing)
