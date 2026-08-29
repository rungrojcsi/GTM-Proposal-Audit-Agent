"""RBAC (F43) — resolve ผู้ใช้ + role จาก SWA client principal.

SWA ส่ง header `x-ms-client-principal` (base64 JSON) มาที่ linked backend เมื่อ user login.
SSO เปิดแล้ว (route protection บังคับ authenticated) -> ทุก request จริงจะมี principal เสมอ,
role มาจาก DB. ไม่มี principal = ยังไม่ login -> guest (ไม่มีสิทธิ์) -> frontend เด้งไป /login.

Local dev (ไม่มี SWA อยู่หน้า) ตั้ง env `AUTH_DEV_MODE=1` เพื่อจำลอง admin ที่ login แล้ว —
ห้ามตั้งบน production (ค่า default = ปิด -> enforce SSO จริง).

⚠️ ขีดจำกัดด้านความปลอดภัยที่ต้องเข้าใจ (สำคัญมาก)
--------------------------------------------------
header `x-ms-client-principal` ถูก "เชื่อโดยไม่ตรวจลายเซ็น" — ปลอมได้ง่ายมาก.
สิ่งเดียวที่ทำให้ปลอดภัยคือ Function App ต้องเรียกได้จาก Static Web Apps เท่านั้น
(SWA จะลบ header ที่ client ส่งมาเองแล้วใส่ค่าจริงให้). ห้ามเปิด Function App
ตรงสู่อินเทอร์เน็ตเด็ดขาด ไม่ว่าผู้ใช้จะต้องต่อ VPN หรือไม่ก็ตาม — ถ้าเปิด
ใครก็ปลอม principal เป็น admin ได้ และชั้นสิทธิ์ทั้งหมดใน shared.guard จะไร้ผล.
"""
from __future__ import annotations

import base64
import json
import logging
import os

from . import db

# ตรวจว่ารันบน Azure จริงไหม (App Service/Functions ตั้ง env นี้ให้เสมอ)
_ON_AZURE = bool(os.environ.get("WEBSITE_INSTANCE_ID"))

# local dev เท่านั้น: จำลอง admin ที่ login แล้ว เมื่อไม่มี SWA principal. prod ต้องไม่ตั้ง.
# S01 (R8) — บน Azure ให้ "ปฏิเสธ" ค่านี้เสมอ แม้จะถูกตั้งไว้: ถ้าหลุดไป production
# มันคือช่องให้ทุกคนกลายเป็น admin. ปิดในโค้ดปลอดภัยกว่าพึ่งวินัยการตั้ง App Settings.
_DEV_ADMIN = os.environ.get("AUTH_DEV_MODE") == "1" and not _ON_AZURE
if os.environ.get("AUTH_DEV_MODE") == "1" and _ON_AZURE:
    logging.error(
        "SECURITY: พบ AUTH_DEV_MODE=1 บน Azure — ถูกเพิกเฉยโดยระบบ (ไม่งั้นทุกคนจะเป็น admin). "
        "กรุณาลบ App Setting นี้ออกจาก Function App"
    )


def client_ip(req) -> str:
    """IP ผู้เรียกจริง สำหรับ audit + ตรวจ allowlist (S02/S03).

    SWA/Azure ส่ง x-forwarded-for แบบ "ip1, ip2, ..." โดย proxy ที่เชื่อถือได้ (ของเรา)
    จะ *ต่อท้าย* IP จริงเข้าไป -> ต้องอ่านค่า "ตัวขวาสุด" ไม่ใช่ตัวซ้ายสุด
    (ตัวซ้ายสุดเป็นค่าที่ client ส่งมาเอง = ปลอมได้). รูปแบบอาจมี :port ติดมาด้วย.
    """
    xff = req.headers.get("x-forwarded-for") or ""
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    raw = parts[-1] if parts else (req.headers.get("x-client-ip") or "")
    if not raw:
        return ""
    # ตัด :port ออก — ระวัง IPv6 ที่มี ':' หลายตัว (ตัดเฉพาะกรณี IPv4:port)
    if raw.count(":") == 1:
        raw = raw.split(":", 1)[0]
    return raw.strip("[]")

# RBAC เป็น dynamic (R3): role + สิทธิ์เข้าหน้า เก็บใน dbo.Roles/RolePermissions
# (เลิก hardcode ROLE_RANK/PAGE_MIN_ROLE) — admin จัดการผ่านหน้า Settings. หน้าทั้งหมด = db.PAGES


def parse_principal(req) -> dict | None:
    """อ่าน x-ms-client-principal จาก SWA. None ถ้าไม่มี (ยังไม่ login)."""
    header = req.headers.get("x-ms-client-principal")
    if not header:
        return None
    try:
        data = json.loads(base64.b64decode(header).decode("utf-8"))
        return {
            "identity_provider": data.get("identityProvider"),
            "user_id": data.get("userId"),
            "email": (data.get("userDetails") or "").strip().lower(),
        }
    except Exception:  # noqa: BLE001
        return None


def current_user(req) -> dict:
    """คืน {user_id, email, name, role, authenticated}.

    มี principal -> role จาก DB (authenticated=True).
    ไม่มี principal -> guest ไม่มีสิทธิ์ (authenticated=False) เพื่อให้ frontend เด้งไป /login;
    ยกเว้น local dev (AUTH_DEV_MODE=1) -> จำลอง admin ที่ login แล้ว.
    """
    p = parse_principal(req)
    if not p or not p["email"]:
        if _DEV_ADMIN:
            return {"user_id": None, "email": None, "name": "Dev Admin",
                    "role": "admin", "authenticated": True}
        return {"user_id": None, "email": None, "name": "Guest",
                "role": "guest", "authenticated": False}
    u = db.get_or_create_user(p["email"], p.get("user_id") or p["email"])
    return {"user_id": u["user_id"], "email": u["email"],
            "name": u["display_name"] or u["email"], "role": u["role"], "authenticated": True}


def has_page(role: str, page: str) -> bool:
    """สิทธิ์เข้าหน้า — อ่านจาก RolePermissions (DB). role ไม่รู้จัก -> False (ปฏิเสธ)."""
    return db.get_role_permissions(role).get(page, False)


def require(user: dict, page: str) -> bool:
    """gate ฝั่ง API — True ถ้าเข้าได้."""
    return has_page(user["role"], page)


def page_access(role: str) -> dict:
    """map หน้า -> เข้าได้ไหม (ให้ frontend ใช้ซ่อน/แสดงเมนู). อ่านจาก DB matrix."""
    return db.get_role_permissions(role)
