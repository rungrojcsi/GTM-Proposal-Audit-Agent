"""Azure SQL access (F04/F05/F10/F11/F17/F18/F20-F27).

ใช้ pyodbc + Managed Identity (ActiveDirectoryMsi) ตาม SQL_CONNECTION_STRING.
ฟังก์ชันเป็น thin helpers — โหลดต่ำ ไม่ optimize pooling.
"""
from __future__ import annotations

import os
import uuid

import pyodbc

from .models import EvaluationLLMOutput


def _conn() -> pyodbc.Connection:
    return pyodbc.connect(os.environ["SQL_CONNECTION_STRING"])


# ชื่อที่แสดงในคอลัมน์ Owner เมื่อ display_name ว่าง — ใช้ชื่อหน้า '@' ไม่ใช่อีเมลเต็ม
# (ผู้ใช้ที่ admin เพิ่มไว้ล่วงหน้ายังไม่มี display_name จนกว่าจะ login ครั้งแรก
#  ถ้าโชว์อีเมลเต็มเท่ากับเผยอีเมลให้ทุกคนที่เห็นรายการ)
# ต่อ '@' ท้ายก่อนหา CHARINDEX เพื่อกันกรณีค่าไม่มี '@' -> คืนทั้งสตริงแทนที่จะพัง
_OWNER_LOCALPART = "LEFT(u.email, CHARINDEX('@', u.email + '@') - 1)"


# ---------- Users / RBAC (F43-F44) ----------
def get_or_create_user(email: str, entra_oid: str, display_name: str | None = None) -> dict:
    """หา user จาก email; ไม่มี -> สร้างด้วย role 'user'. คืน {user_id, email, display_name, role}."""
    email_l = email.strip().lower()
    with _conn() as cn:
        row = cn.execute(
            "SELECT user_id, email, display_name, role FROM dbo.Users WHERE LOWER(email) = ?", email_l
        ).fetchone()
        if row:
            return {"user_id": str(row[0]), "email": row[1], "display_name": row[2], "role": row[3]}
        uid = str(uuid.uuid4())
        cn.execute(
            """INSERT INTO dbo.Users (user_id, entra_oid, email, display_name, role)
               VALUES (?, ?, ?, ?, 'user')""",
            uid, entra_oid[:100], email, display_name or email.split("@")[0],
        )
        cn.commit()
        return {"user_id": uid, "email": email, "display_name": display_name or email.split("@")[0], "role": "user"}


def list_users() -> list[dict]:
    with _conn() as cn:
        cur = cn.execute(
            "SELECT user_id, email, display_name, role, created_at FROM dbo.Users ORDER BY role DESC, email"
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def set_user_role(user_id: str, role: str) -> bool:
    with _conn() as cn:
        cur = cn.execute("UPDATE dbo.Users SET role = ? WHERE user_id = ?", role, user_id)
        ok = cur.rowcount > 0
        cn.commit()
        return ok


def add_user_by_email(email: str, role: str, display_name: str | None = None) -> None:
    """F44 — pre-add user ล่วงหน้าก่อน login (admin แต่งตั้ง role ไว้).

    พอ user คนนั้น login ผ่าน SSO จริง จะ match ด้วย email แล้วได้ role ที่กำหนดเลย.
    มีอยู่แล้ว -> อัปเดต role.
    """
    email_l = email.strip().lower()
    with _conn() as cn:
        cn.execute(
            """MERGE dbo.Users AS t USING (SELECT ? AS email) AS s ON LOWER(t.email) = s.email
               WHEN MATCHED THEN UPDATE SET role = ?
               WHEN NOT MATCHED THEN INSERT (entra_oid, email, display_name, role)
                    VALUES (?, ?, ?, ?);""",
            email_l, role,
            f"preadd:{email_l}"[:100], email.strip(), display_name or email.split("@")[0], role,
        )
        cn.commit()


# ---------- MasterData (F45) — Solution Type / Industry ----------
def list_master_data(category: str | None = None) -> list[dict]:
    with _conn() as cn:
        if category:
            cur = cn.execute(
                "SELECT id, category, value, sort_order, active FROM dbo.MasterData WHERE category = ? ORDER BY sort_order, value",
                category,
            )
        else:
            cur = cn.execute(
                "SELECT id, category, value, sort_order, active FROM dbo.MasterData ORDER BY category, sort_order, value"
            )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def add_master_data(category: str, value: str) -> str:
    mid = str(uuid.uuid4())
    with _conn() as cn:
        cn.execute(
            """IF NOT EXISTS (SELECT 1 FROM dbo.MasterData WHERE category = ? AND value = ?)
               INSERT INTO dbo.MasterData (id, category, value) VALUES (?, ?, ?)""",
            category, value, mid, category, value,
        )
        cn.commit()
    return mid


def delete_master_data(mid: str) -> bool:
    with _conn() as cn:
        cur = cn.execute("DELETE FROM dbo.MasterData WHERE id = ?", mid)
        ok = cur.rowcount > 0
        cn.commit()
        return ok


# ---------- AppSettings (F46) — audit defaults ----------
def get_settings() -> dict:
    with _conn() as cn:
        cur = cn.execute("SELECT setting_key, setting_value FROM dbo.AppSettings")
        return {r[0]: r[1] for r in cur.fetchall()}


def put_settings(kv: dict) -> None:
    with _conn() as cn:
        for k, v in kv.items():
            cn.execute(
                """MERGE dbo.AppSettings AS t USING (SELECT ? AS k) AS s ON t.setting_key = s.k
                   WHEN MATCHED THEN UPDATE SET setting_value = ?, updated_at = SYSUTCDATETIME()
                   WHEN NOT MATCHED THEN INSERT (setting_key, setting_value) VALUES (?, ?);""",
                k, str(v), k, str(v),
            )
        cn.commit()


# ---------- Roles & Permissions (R3 — dynamic RBAC) ----------
# หน้าที่คุมสิทธิ์ได้ (ตรงกับ nav 5 หน้า). matrix = role x page.
# view_all = เห็นทุกโปรเจค; manage_proposals = แก้ไขชื่อ/ลบโปรเจค (permission flags ไม่ใช่ nav page)
PAGES = ("evaluate", "proposals", "library", "dashboard", "settings", "view_all", "manage_proposals")
# seed จาก hierarchy เดิม: manager+ เห็นทุกโปรเจค, admin เท่านั้นแก้/ลบได้ (ตั้งเพิ่มผ่าน matrix ได้)
_SEED_ROLES = [
    ("user", 0, ["evaluate", "proposals"]),
    ("manager", 0, ["evaluate", "proposals", "library", "view_all"]),
    ("management", 0, ["evaluate", "proposals", "library", "dashboard", "view_all"]),
    ("admin", 1, ["evaluate", "proposals", "library", "dashboard", "settings", "view_all", "manage_proposals"]),
]


def ensure_rbac_schema() -> dict:
    """สร้าง Roles + RolePermissions (idempotent) + seed 4 role เดิม. เรียกครั้งเดียวตอน setup."""
    with _conn() as cn:
        cn.execute(
            "IF OBJECT_ID('dbo.Roles','U') IS NULL "
            "CREATE TABLE dbo.Roles (role_id UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY, "
            "name NVARCHAR(50) NOT NULL UNIQUE, is_system BIT NOT NULL DEFAULT 0, "
            "created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME());"
        )
        cn.execute(
            "IF OBJECT_ID('dbo.RolePermissions','U') IS NULL "
            "CREATE TABLE dbo.RolePermissions (role_id UNIQUEIDENTIFIER NOT NULL "
            "REFERENCES dbo.Roles(role_id) ON DELETE CASCADE, page_key NVARCHAR(30) NOT NULL, "
            "can_access BIT NOT NULL DEFAULT 0, "
            "CONSTRAINT PK_RolePermissions PRIMARY KEY (role_id, page_key));"
        )
        cn.commit()
        seeded = []
        for name, is_sys, allowed in _SEED_ROLES:
            row = cn.execute("SELECT role_id FROM dbo.Roles WHERE name = ?", name).fetchone()
            if row:
                rid = row[0]
            else:
                rid = uuid.uuid4()
                cn.execute("INSERT INTO dbo.Roles (role_id, name, is_system) VALUES (?, ?, ?)", rid, name, is_sys)
                seeded.append(name)
            for pg in PAGES:
                if cn.execute(
                    "SELECT 1 FROM dbo.RolePermissions WHERE role_id = ? AND page_key = ?", rid, pg
                ).fetchone() is None:
                    cn.execute(
                        "INSERT INTO dbo.RolePermissions (role_id, page_key, can_access) VALUES (?, ?, ?)",
                        rid, pg, 1 if pg in allowed else 0,
                    )
        cn.commit()
        return {"seeded_roles": seeded, "pages": list(PAGES)}


def list_roles() -> list[dict]:
    """คืน [{role_id, name, is_system, permissions:{page:bool}, user_count}] เรียง system ก่อน."""
    with _conn() as cn:
        roles = cn.execute("SELECT role_id, name, is_system FROM dbo.Roles ORDER BY is_system DESC, name").fetchall()
        perms = cn.execute("SELECT role_id, page_key, can_access FROM dbo.RolePermissions").fetchall()
        counts = cn.execute("SELECT role, COUNT(*) FROM dbo.Users GROUP BY role").fetchall()
    cnt_map = {r[0]: r[1] for r in counts}
    pmap: dict[str, dict] = {}
    for rid, pg, ca in perms:
        pmap.setdefault(str(rid), {})[pg] = bool(ca)
    return [
        {
            "role_id": str(rid), "name": name, "is_system": bool(issys),
            "permissions": {pg: pmap.get(str(rid), {}).get(pg, False) for pg in PAGES},
            "user_count": cnt_map.get(name, 0),
        }
        for rid, name, issys in roles
    ]


# fallback เมื่อยังไม่ init RBAC (table ยังไม่สร้าง) — hierarchy เดิม กันระบบล่ม + ให้ admin เข้า init ได้
_FALLBACK_PERMS = {
    "user":       {"evaluate": True, "proposals": True, "library": False, "dashboard": False, "settings": False},
    "manager":    {"evaluate": True, "proposals": True, "library": True,  "dashboard": False, "settings": False},
    "management": {"evaluate": True, "proposals": True, "library": True,  "dashboard": True,  "settings": False},
    "admin":      {"evaluate": True, "proposals": True, "library": True,  "dashboard": True,  "settings": True},
}


def get_role_permissions(role_name: str) -> dict:
    """คืน {page: bool} ของ role. role ไม่มี -> ทุก page False. table ยังไม่ init -> fallback hierarchy เดิม."""
    try:
        with _conn() as cn:
            rows = cn.execute(
                "SELECT rp.page_key, rp.can_access FROM dbo.RolePermissions rp "
                "JOIN dbo.Roles r ON r.role_id = rp.role_id WHERE r.name = ?", role_name
            ).fetchall()
    except Exception:  # noqa: BLE001 — Roles/RolePermissions ยังไม่สร้าง -> ใช้ hierarchy เดิม
        return dict(_FALLBACK_PERMS.get(role_name, {pg: False for pg in PAGES}))
    perms = {pg: False for pg in PAGES}
    for pg, ca in rows:
        if pg in perms:
            perms[pg] = bool(ca)
    return perms


def role_exists(name: str) -> bool:
    with _conn() as cn:
        return cn.execute("SELECT 1 FROM dbo.Roles WHERE name = ?", name).fetchone() is not None


def get_role_by_id(role_id: str) -> dict | None:
    with _conn() as cn:
        row = cn.execute("SELECT role_id, name, is_system FROM dbo.Roles WHERE role_id = ?", role_id).fetchone()
    return {"role_id": str(row[0]), "name": row[1], "is_system": bool(row[2])} if row else None


def create_role(name: str) -> str:
    """สร้าง role ใหม่ (permission ทุกหน้า = False เริ่มต้น). คืน role_id."""
    rid = str(uuid.uuid4())
    with _conn() as cn:
        cn.execute("INSERT INTO dbo.Roles (role_id, name, is_system) VALUES (?, ?, 0)", rid, name)
        for pg in PAGES:
            cn.execute("INSERT INTO dbo.RolePermissions (role_id, page_key, can_access) VALUES (?, ?, 0)", rid, pg)
        cn.commit()
    return rid


def delete_role(role_id: str) -> None:
    """ลบ role (เฉพาะ non-system) — RolePermissions cascade."""
    with _conn() as cn:
        cn.execute("DELETE FROM dbo.Roles WHERE role_id = ? AND is_system = 0", role_id)
        cn.commit()


def set_role_permissions(role_id: str, perms: dict) -> None:
    """อัปเดต can_access ตาม {page: bool}."""
    with _conn() as cn:
        for pg, ca in perms.items():
            if pg in PAGES:
                cn.execute(
                    "MERGE dbo.RolePermissions AS t USING (SELECT ? AS rid, ? AS pk) AS s "
                    "ON t.role_id = s.rid AND t.page_key = s.pk "
                    "WHEN MATCHED THEN UPDATE SET can_access = ? "
                    "WHEN NOT MATCHED THEN INSERT (role_id, page_key, can_access) VALUES (s.rid, s.pk, ?);",
                    role_id, pg, 1 if ca else 0, 1 if ca else 0,
                )
        cn.commit()


def count_users_with_role(name: str) -> int:
    with _conn() as cn:
        return cn.execute("SELECT COUNT(*) FROM dbo.Users WHERE role = ?", name).fetchone()[0]


def count_roles_with_page(page: str) -> int:
    """จำนวน role ที่มีสิทธิ์ page นี้ — guard กันถอน settings จนไม่เหลือใครเข้าได้."""
    with _conn() as cn:
        return cn.execute(
            "SELECT COUNT(*) FROM dbo.RolePermissions WHERE page_key = ? AND can_access = 1", page
        ).fetchone()[0]


# ---------- Ticket (F21) — 1 ต่อ project, PE-YYYY-NNNNN running ยาวไม่ reset ----------
def issue_ticket(year: int) -> str:
    with _conn() as cn:
        seq = int(cn.execute("SELECT NEXT VALUE FOR dbo.seq_ticket").fetchone()[0])
        return f"PE-{year}-{seq:05d}"


# ---------- Thread lookup / create (F05/F22) ----------
def find_thread_by_client_project(client_name: str, project_name: str) -> dict | None:
    """หา thread เดิมด้วย client+project (case-insensitive, trim). คืน None ถ้าไม่มี."""
    with _conn() as cn:
        row = cn.execute(
            """SELECT TOP 1 thread_id, ticket_no FROM dbo.ProposalThreads
               WHERE LOWER(LTRIM(RTRIM(client_name)))  = LOWER(LTRIM(RTRIM(?)))
                 AND LOWER(LTRIM(RTRIM(project_name))) = LOWER(LTRIM(RTRIM(?)))
               ORDER BY created_at""",
            client_name, project_name,
        ).fetchone()
        return {"thread_id": str(row[0]), "ticket_no": row[1]} if row else None


def create_thread(client_name: str, project_name: str, ticket_no: str, owner_id: str | None = None) -> str:
    thread_id = str(uuid.uuid4())
    with _conn() as cn:
        cn.execute(
            """INSERT INTO dbo.ProposalThreads (thread_id, ticket_no, client_name, project_name, owner_id)
               VALUES (?, ?, ?, ?, ?)""",
            thread_id, ticket_no, client_name, project_name, owner_id,
        )
        cn.commit()
    return thread_id


def next_version_no(thread_id: str) -> int:
    with _conn() as cn:
        row = cn.execute(
            "SELECT ISNULL(MAX(version_no), 0) FROM dbo.Submissions WHERE thread_id = ?", thread_id
        ).fetchone()
        return int(row[0]) + 1


# ---------- Prior version lookups (F24/F25) ----------
def latest_evaluated_submission(thread_id: str) -> dict | None:
    """submission ล่าสุดที่ประเมินแล้วใน thread (สำหรับ improvement-gate)."""
    with _conn() as cn:
        row = cn.execute(
            """SELECT TOP 1 s.submission_id, s.version_no, s.content_hash, s.text_content, s.lang, e.eval_id,
                      s.blob_url, s.filename
               FROM dbo.Submissions s
               JOIN dbo.EvaluationResults e ON e.submission_id = s.submission_id
               WHERE s.thread_id = ?
               ORDER BY s.version_no DESC""",
            thread_id,
        ).fetchone()
        if not row:
            return None
        return {"submission_id": str(row[0]), "version_no": int(row[1]),
                "content_hash": row[2], "text_content": row[3] or "", "lang": row[4] or "en",
                "eval_id": str(row[5]), "blob_url": row[6] or "", "filename": row[7] or "proposal"}


def find_eval_by_hash(thread_id: str, content_hash: str, lang: str) -> str | None:
    """หา eval_id ของ submission ใน thread ที่ content_hash + lang ตรง (cache hit F24).

    lang เป็นส่วนหนึ่งของ cache key — content เดิมแต่คนละภาษา = คนละผลลัพธ์ ต้องประเมินใหม่.
    """
    with _conn() as cn:
        row = cn.execute(
            """SELECT TOP 1 e.eval_id FROM dbo.Submissions s
               JOIN dbo.EvaluationResults e ON e.submission_id = s.submission_id
               WHERE s.thread_id = ? AND s.content_hash = ? AND s.lang = ?
               ORDER BY s.version_no DESC""",
            thread_id, content_hash, lang,
        ).fetchone()
        return str(row[0]) if row else None


def get_recommendation_texts(eval_id: str) -> list[str]:
    with _conn() as cn:
        cur = cn.execute("SELECT rec_text FROM dbo.Recommendations WHERE eval_id = ?", eval_id)
        return [r[0] for r in cur.fetchall()]


# ---------- Submission + evaluation persistence (F04/F10/F11) ----------
def create_submission(
    thread_id: str, version_no: int, filename: str, content_type: str,
    blob_url: str, file_size: int, content_hash: str, text_content: str, lang: str,
) -> str:
    submission_id = str(uuid.uuid4())
    with _conn() as cn:
        cn.execute(
            """INSERT INTO dbo.Submissions
               (submission_id, thread_id, version_no, filename, content_type, blob_url,
                file_size, content_hash, text_content, lang, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Evaluating')""",
            submission_id, thread_id, version_no, filename, content_type, blob_url,
            file_size, content_hash, text_content, lang,
        )
        cn.commit()
    return submission_id


def save_evaluation(
    submission_id: str, overall_score: float, verdict: str,
    llm: EvaluationLLMOutput, raw_json: str, model_name: str, score_source: str = "evaluated",
) -> str:
    """บันทึกผลประเมินใหม่ + score details + recommendations (F10/F11)."""
    eval_id = str(uuid.uuid4())
    with _conn() as cn:
        cn.execute(
            """INSERT INTO dbo.EvaluationResults
               (eval_id, submission_id, overall_score, verdict, skeleton_md, raw_llm_json, model_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            eval_id, submission_id, overall_score, verdict, llm.skeleton_md, raw_json, model_name,
        )
        for d in llm.score_details:
            cn.execute(
                """INSERT INTO dbo.ScoreDetails (detail_id, eval_id, slide_section, tier, score_1_10, coverage)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                str(uuid.uuid4()), eval_id, d.slide_section, d.tier, d.score_1_10, d.coverage,
            )
        for r in llm.recommendations:
            cn.execute(
                """INSERT INTO dbo.Recommendations (rec_id, eval_id, priority, rec_text, slide_ref)
                   VALUES (?, ?, ?, ?, ?)""",
                str(uuid.uuid4()), eval_id, r.priority, r.rec_text, r.slide_ref,
            )
        cn.execute("UPDATE dbo.Submissions SET status='Evaluated', score_source=? WHERE submission_id=?",
                   score_source, submission_id)
        cn.commit()
    return eval_id


def copy_evaluation(new_submission_id: str, source_eval_id: str) -> str:
    """Reuse (F24/F25) — copy eval เดิมมาเป็น eval ใหม่ของ submission นี้ -> คะแนนคงที่เป๊ะ."""
    new_eval_id = str(uuid.uuid4())
    with _conn() as cn:
        cn.execute(
            """INSERT INTO dbo.EvaluationResults
               (eval_id, submission_id, overall_score, verdict, skeleton_md, raw_llm_json, model_name)
               SELECT ?, ?, overall_score, verdict, skeleton_md, raw_llm_json, model_name
               FROM dbo.EvaluationResults WHERE eval_id = ?""",
            new_eval_id, new_submission_id, source_eval_id,
        )
        cn.execute(
            """INSERT INTO dbo.ScoreDetails (detail_id, eval_id, slide_section, tier, score_1_10, coverage)
               SELECT NEWID(), ?, slide_section, tier, score_1_10, coverage
               FROM dbo.ScoreDetails WHERE eval_id = ?""",
            new_eval_id, source_eval_id,
        )
        cn.execute(
            """INSERT INTO dbo.Recommendations (rec_id, eval_id, priority, rec_text, slide_ref)
               SELECT NEWID(), ?, priority, rec_text, slide_ref
               FROM dbo.Recommendations WHERE eval_id = ?""",
            new_eval_id, source_eval_id,
        )
        cn.execute("UPDATE dbo.Submissions SET status='Evaluated', score_source='reused' WHERE submission_id=?",
                   new_submission_id)
        cn.commit()
    return new_eval_id


def get_evaluation(eval_id: str) -> dict:
    """อ่าน eval เต็ม (สำหรับส่งกลับ frontend ทั้ง evaluated + reused)."""
    import json

    with _conn() as cn:
        head = cn.execute(
            "SELECT submission_id, overall_score, verdict, skeleton_md, raw_llm_json, model_name FROM dbo.EvaluationResults WHERE eval_id=?",
            eval_id,
        ).fetchone()
        details = cn.execute(
            "SELECT slide_section, tier, score_1_10, coverage FROM dbo.ScoreDetails WHERE eval_id=?", eval_id
        ).fetchall()
        recs = cn.execute(
            "SELECT priority, rec_text, slide_ref FROM dbo.Recommendations WHERE eval_id=?", eval_id
        ).fetchall()
    raw = {}
    try:
        raw = json.loads(head[4]) if head[4] else {}
    except Exception:  # noqa: BLE001
        raw = {}
    return {
        "submission_id": str(head[0]), "overall_score": float(head[1]), "verdict": head[2],
        "skeleton_md": head[3] or "",
        "score_details": [{"slide_section": d[0], "tier": d[1], "score_1_10": int(d[2]), "coverage": d[3] or ""} for d in details],
        "recommendations": [{"priority": r[0], "rec_text": r[1], "slide_ref": r[2] or ""} for r in recs],
        "strengths": raw.get("strengths", []),
        "gaps": raw.get("gaps", []),
        "model_name": head[5] or "",
    }


def set_submission_status(submission_id: str, status: str) -> None:
    with _conn() as cn:
        cn.execute("UPDATE dbo.Submissions SET status=? WHERE submission_id=?", status, submission_id)
        cn.commit()


def get_submission(submission_id: str) -> dict | None:
    """meta + text ของ submission (สำหรับ async worker + poll status). None ถ้าไม่มี."""
    with _conn() as cn:
        row = cn.execute(
            "SELECT submission_id, thread_id, version_no, text_content, lang, status "
            "FROM dbo.Submissions WHERE submission_id = ?", submission_id,
        ).fetchone()
    if not row:
        return None
    return {"submission_id": str(row[0]), "thread_id": str(row[1]), "version_no": int(row[2]),
            "text_content": row[3] or "", "lang": row[4] or "en", "status": row[5]}


# ---------- Comments (F26) ----------
def add_comment(thread_id: str, submission_id: str | None, author: str, text: str) -> str:
    comment_id = str(uuid.uuid4())
    with _conn() as cn:
        cn.execute(
            """INSERT INTO dbo.Comments (comment_id, thread_id, submission_id, author, comment_text)
               VALUES (?, ?, ?, ?, ?)""",
            comment_id, thread_id, submission_id, author, text,
        )
        cn.commit()
    return comment_id


def get_comments(thread_id: str) -> list[dict]:
    with _conn() as cn:
        cur = cn.execute(
            """SELECT submission_id, author, comment_text, created_at
               FROM dbo.Comments WHERE thread_id = ? ORDER BY created_at""",
            thread_id,
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------- Proposals list (F18/F19) ----------
def list_proposals(owner_id: str | None = None) -> list[dict]:
    """สรุป 1 แถวต่อ thread: ticket/client/project + version ล่าสุด + จำนวน version + คะแนน/verdict ล่าสุด.

    owner_id != None -> กรองเฉพาะ thread ที่ owner ตรง (F44 user เห็นเฉพาะของตัวเอง).
    """
    owner_clause = "WHERE t.owner_id = ?" if owner_id else ""
    params = (owner_id,) if owner_id else ()
    with _conn() as cn:
        cur = cn.execute(
            # E06 — ส่ง v.status ออกไปด้วย: vw_ThreadScores ใช้ LEFT JOIN จึงมีแถวของ version
            # ที่ยังประเมินไม่เสร็จ และเราเลือกแถว MAX(version_no) -> ระหว่างประเมิน v2 อยู่
            # รายการจะแสดงคะแนนว่างทับคะแนน v1 ที่เคยเห็น ผู้ใช้เข้าใจว่าคะแนนหาย
            f"""SELECT v.thread_id, v.ticket_no, v.client_name, v.project_name,
                      v.version_no, agg.version_count, v.status,
                      v.overall_score, v.verdict, v.score_source, v.evaluated_at,
                      COALESCE(NULLIF(u.display_name, ''), {_OWNER_LOCALPART}) AS owner_name
               FROM dbo.vw_ThreadScores v
               JOIN (SELECT thread_id, MAX(version_no) AS max_ver, COUNT(*) AS version_count
                     FROM dbo.vw_ThreadScores GROUP BY thread_id) agg
                 ON agg.thread_id = v.thread_id AND agg.max_ver = v.version_no
               JOIN dbo.ProposalThreads t ON t.thread_id = v.thread_id
               LEFT JOIN dbo.Users u ON u.user_id = t.owner_id
               {owner_clause}
               ORDER BY v.evaluated_at DESC, v.ticket_no DESC""",
            *params,
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_thread(thread_id: str) -> dict | None:
    """meta ของ thread (ticket/client/project). None ถ้าไม่มี."""
    with _conn() as cn:
        row = cn.execute(
            "SELECT thread_id, ticket_no, client_name, project_name FROM dbo.ProposalThreads WHERE thread_id = ?",
            thread_id,
        ).fetchone()
        return (
            {"thread_id": str(row[0]), "ticket_no": row[1],
             "client_name": row[2] or "", "project_name": row[3] or ""}
            if row else None
        )


def get_thread_owner(thread_id: str) -> str | None:
    """owner_id ของ thread (B01 — ใช้ตรวจความเป็นเจ้าของ). None = ไม่มี thread / ไม่มี owner.

    thread_id ที่ไม่ใช่ UUID จะทำให้ pyodbc error -> กลืนแล้วคืน None (fail-closed:
    guard จะตอบ 403 แทนที่จะเป็น 500 จาก input ที่ผู้ใช้พิมพ์เอง).
    """
    try:
        with _conn() as cn:
            row = cn.execute(
                "SELECT owner_id FROM dbo.ProposalThreads WHERE thread_id = ?", thread_id
            ).fetchone()
    except Exception:  # noqa: BLE001 — thread_id รูปแบบผิด -> ถือว่าเข้าไม่ได้
        return None
    return str(row[0]) if row and row[0] is not None else None


def find_thread_by_hash(content_hash: str) -> dict | None:
    """หา thread จาก content_hash ของ submission — ไฟล์เดียวกันเคยส่งแล้ว -> thread เดิม
    (แม้ detect ชื่อ client/project เพี้ยนไม่ตรงกัน). คืน thread ล่าสุดที่มี hash นี้."""
    with _conn() as cn:
        row = cn.execute(
            "SELECT TOP 1 t.thread_id, t.ticket_no, t.client_name, t.project_name "
            "FROM dbo.Submissions s JOIN dbo.ProposalThreads t ON t.thread_id = s.thread_id "
            "WHERE s.content_hash = ? ORDER BY s.version_no DESC", content_hash,
        ).fetchone()
    return (
        {"thread_id": str(row[0]), "ticket_no": row[1], "client_name": row[2] or "", "project_name": row[3] or ""}
        if row else None
    )


def update_thread(thread_id: str, client_name: str, project_name: str) -> None:
    """แก้ชื่อ client/project ของ thread (permission manage_proposals)."""
    with _conn() as cn:
        cn.execute(
            "UPDATE dbo.ProposalThreads SET client_name=?, project_name=? WHERE thread_id=?",
            client_name, project_name, thread_id,
        )
        cn.commit()


def delete_thread(thread_id: str) -> None:
    """ลบ thread + ข้อมูลลูกทั้งหมด (eval/submission/content/comment/coach) ตามลำดับ FK.

    ⚠️ ตารางลูกที่อ้าง thread_id ต้องถูกลบที่นี่ให้ครบ — มีเพียง ScoreDetails/Recommendations
    เท่านั้นที่มี ON DELETE CASCADE (จาก EvaluationResults). ที่เหลือไม่มี cascade
    ลืมตัวไหน = FK violation -> ลบโปรเจคไม่ได้ตลอดไป (คืน 500)

    CoachJobs ห่อด้วย OBJECT_ID เพราะเป็นตารางของ Wave 3 ที่อาจยังไม่ถูก migrate
    บนบางสภาพแวดล้อม — ไม่มีตารางต้องไม่ทำให้ลบ thread พัง
    """
    with _conn() as cn:
        cn.execute(
            "DELETE FROM dbo.EvaluationResults WHERE submission_id IN "
            "(SELECT submission_id FROM dbo.Submissions WHERE thread_id=?)", thread_id,
        )  # ScoreDetails/Recommendations cascade จาก eval
        cn.execute(
            "IF OBJECT_ID('dbo.CoachJobs','U') IS NOT NULL "
            "DELETE FROM dbo.CoachJobs WHERE thread_id=?", thread_id,
        )
        cn.execute("DELETE FROM dbo.ProposalContent WHERE thread_id=?", thread_id)
        cn.execute("DELETE FROM dbo.Comments WHERE thread_id=?", thread_id)
        cn.execute("DELETE FROM dbo.Submissions WHERE thread_id=?", thread_id)
        cn.execute("DELETE FROM dbo.ProposalThreads WHERE thread_id=?", thread_id)
        cn.commit()


# ---------- Proposal Library (F30-F33) ----------
_CONTENT_FIELDS = [
    "price_amount", "price_currency", "cost_amount", "cost_currency", "duration_months",
    "milestones", "manpower", "solution_type", "industry", "deal_outcome",
]


def upsert_extracted_content(thread_id: str, submission_id: str, chash: str, data: dict | None) -> None:
    """F30 — บันทึกผล extraction ต่อ thread (1:1).

    กติกา (SA Phase 2): SQL เป็น source of truth ของคน — extraction ห้ามทับข้อมูลที่ verified แล้ว
    - ยังไม่มี record            -> INSERT (data=None -> record ว่างให้กรอกมือ)
    - extracted_hash เดิม        -> ไม่ทำอะไร (เนื้อหาไม่เปลี่ยน)
    - verified แล้ว + hash เปลี่ยน -> ตั้ง content_stale=1 เท่านั้น (คนไปทบทวนเองในหน้า edit)
    - pending_verify             -> ทับด้วย extraction ใหม่
    """
    import json

    d = data or {}
    vals = (
        d.get("price_amount"), d.get("price_currency"), d.get("cost_amount"), d.get("cost_currency"),
        d.get("duration_months"),
        json.dumps(d.get("milestones") or [], ensure_ascii=False),
        json.dumps(d.get("manpower") or [], ensure_ascii=False),
        d.get("solution_type") or None, d.get("industry") or None,
        json.dumps(d.get("confidence") or {}, ensure_ascii=False),
    )
    with _conn() as cn:
        row = cn.execute(
            "SELECT verify_status, extracted_hash FROM dbo.ProposalContent WHERE thread_id = ?", thread_id
        ).fetchone()
        if row is None:
            cn.execute(
                """INSERT INTO dbo.ProposalContent
                   (content_id, thread_id, submission_id,
                    price_amount, price_currency, cost_amount, cost_currency, duration_months,
                    milestones, manpower, solution_type, industry, field_confidence,
                    extracted_hash, metadata_dirty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                str(uuid.uuid4()), thread_id, submission_id, *vals, chash,
            )
        elif row[1] == chash:
            pass  # เนื้อหาเดิม — extraction เดิมยังใช้ได้
        elif row[0] == "verified":
            cn.execute(
                """UPDATE dbo.ProposalContent
                   SET content_stale = 1, updated_at = SYSUTCDATETIME() WHERE thread_id = ?""",
                thread_id,
            )
        else:
            cn.execute(
                """UPDATE dbo.ProposalContent
                   SET submission_id = ?, price_amount = ?, price_currency = ?, cost_amount = ?,
                       cost_currency = ?, duration_months = ?, milestones = ?, manpower = ?,
                       solution_type = ?, industry = ?, field_confidence = ?, extracted_hash = ?,
                       source = 'extracted', metadata_dirty = 1, updated_at = SYSUTCDATETIME()
                   WHERE thread_id = ?""",
                submission_id, *vals, chash, thread_id,
            )
        cn.commit()


def list_library(owner_id: str | None = None) -> list[dict]:
    """F31 — 1 แถวต่อ thread: meta + project content + คะแนน version ล่าสุด (filter ทำฝั่ง frontend).

    owner_id != None -> กรองเฉพาะ thread ที่ owner ตรง.
    """
    owner_clause = "WHERE t.owner_id = ?" if owner_id else ""
    params = (owner_id,) if owner_id else ()
    with _conn() as cn:
        cur = cn.execute(
            f"""SELECT t.thread_id, t.ticket_no, t.client_name, t.project_name,
                      c.price_amount, c.price_currency, c.cost_amount, c.cost_currency,
                      c.duration_months, c.solution_type, c.industry, c.deal_outcome,
                      c.verify_status, c.content_stale, c.sync_status, c.updated_at,
                      v.version_no, v.overall_score, v.verdict,
                      COALESCE(NULLIF(u.display_name, ''), {_OWNER_LOCALPART}) AS owner_name
               FROM dbo.ProposalThreads t
               LEFT JOIN dbo.ProposalContent c ON c.thread_id = t.thread_id
               JOIN (SELECT thread_id, MAX(version_no) AS max_ver FROM dbo.vw_ThreadScores
                     GROUP BY thread_id) agg ON agg.thread_id = t.thread_id
               JOIN dbo.vw_ThreadScores v ON v.thread_id = t.thread_id AND v.version_no = agg.max_ver
               LEFT JOIN dbo.Users u ON u.user_id = t.owner_id
               {owner_clause}
               ORDER BY t.created_at DESC""",
            *params,
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_library_item(thread_id: str) -> dict | None:
    """F32 — content เต็มของ thread + ไฟล์ version ล่าสุด. None ถ้าไม่มี thread."""
    import json

    with _conn() as cn:
        row = cn.execute(
            """SELECT t.thread_id, t.ticket_no, t.client_name, t.project_name,
                      c.price_amount, c.price_currency, c.cost_amount, c.cost_currency,
                      c.duration_months, c.milestones, c.manpower, c.solution_type, c.industry,
                      c.deal_outcome, c.source, c.field_confidence, c.content_stale,
                      c.verify_status, c.verified_by, c.verified_at,
                      c.sharepoint_url, c.sync_status, c.updated_at
               FROM dbo.ProposalThreads t
               LEFT JOIN dbo.ProposalContent c ON c.thread_id = t.thread_id
               WHERE t.thread_id = ?""",
            thread_id,
        ).fetchone()
        if row is None:
            return None
        cols = ["thread_id", "ticket_no", "client_name", "project_name",
                "price_amount", "price_currency", "cost_amount", "cost_currency",
                "duration_months", "milestones", "manpower", "solution_type", "industry",
                "deal_outcome", "source", "field_confidence", "content_stale",
                "verify_status", "verified_by", "verified_at",
                "sharepoint_url", "sync_status", "updated_at"]
        item = dict(zip(cols, row))
        item["thread_id"] = str(item["thread_id"])
        for k in ("milestones", "manpower", "field_confidence"):
            try:
                item[k] = json.loads(item[k]) if item[k] else ([] if k != "field_confidence" else {})
            except Exception:  # noqa: BLE001
                item[k] = [] if k != "field_confidence" else {}
        item["has_content"] = row[13] is not None  # deal_outcome NOT NULL เมื่อมี record
        return item


def update_library_item(thread_id: str, fields: dict, verify: bool, author: str) -> bool:
    """F33 — คนแก้/ยืนยัน content. คืน False ถ้ายังไม่มี record (ต้อง extract/สร้างก่อน).

    ทุกการแก้: source='manual', metadata_dirty=1 (ให้ M3 push ตอน sync พร้อม), ล้าง content_stale.
    """
    import json

    sets, params = [], []
    for k in _CONTENT_FIELDS:
        if k not in fields:
            continue
        v = fields[k]
        if k in ("milestones", "manpower"):
            v = json.dumps(v or [], ensure_ascii=False)
        sets.append(f"{k} = ?")
        params.append(v)
    if verify:
        sets += ["verify_status = 'verified'", "verified_by = ?", "verified_at = SYSUTCDATETIME()"]
        params.append(author)
    if not sets:
        return True
    sets += ["source = 'manual'", "content_stale = 0", "metadata_dirty = 1", "updated_at = SYSUTCDATETIME()"]
    with _conn() as cn:
        cur = cn.execute(
            f"UPDATE dbo.ProposalContent SET {', '.join(sets)} WHERE thread_id = ?",
            *params, thread_id,
        )
        ok = cur.rowcount > 0
        cn.commit()
        return ok


def create_empty_content(thread_id: str) -> None:
    """สร้าง record ว่าง (กรอกมือทั้งหมด) — ใช้เมื่อ thread เก่ายังไม่มี content และคนกด edit."""
    with _conn() as cn:
        cn.execute(
            """IF NOT EXISTS (SELECT 1 FROM dbo.ProposalContent WHERE thread_id = ?)
               INSERT INTO dbo.ProposalContent (content_id, thread_id) VALUES (?, ?)""",
            thread_id, str(uuid.uuid4()), thread_id,
        )
        cn.commit()


def threads_missing_content() -> list[dict]:
    """F37 backfill — thread ที่ประเมินแล้วแต่ยังไม่มี ProposalContent."""
    with _conn() as cn:
        cur = cn.execute(
            """SELECT s.thread_id, s.submission_id, s.content_hash, s.text_content
               FROM dbo.Submissions s
               JOIN (SELECT thread_id, MAX(version_no) AS max_ver FROM dbo.Submissions
                     WHERE status IN ('Evaluated','Accepted') GROUP BY thread_id) m
                 ON m.thread_id = s.thread_id AND m.max_ver = s.version_no
               WHERE NOT EXISTS (SELECT 1 FROM dbo.ProposalContent c WHERE c.thread_id = s.thread_id)"""
        )
        return [{"thread_id": str(r[0]), "submission_id": str(r[1]),
                 "content_hash": r[2], "text_content": r[3] or ""} for r in cur.fetchall()]


# ---------- Dashboard (F42) ----------
def get_dashboard() -> dict:
    """สรุปภาพรวมสำหรับหน้า Dashboard — คำนวณจากตารางเดิม (ไม่เก็บข้อมูลเพิ่ม).

    ยึด 'version ล่าสุดต่อ thread ที่ประเมินแล้ว' เป็นหน่วยนับ (เหมือน list_proposals).
    """
    with _conn() as cn:
        # latest evaluated version ต่อ thread + project content (LEFT JOIN — บาง thread ยังไม่มี content)
        rows = cn.execute(
            """WITH latest AS (
                   SELECT v.thread_id, v.ticket_no, v.client_name, v.project_name,
                          v.overall_score, v.verdict, v.evaluated_at,
                          ROW_NUMBER() OVER (PARTITION BY v.thread_id ORDER BY v.version_no DESC) rn
                   FROM dbo.vw_ThreadScores v
                   WHERE v.overall_score IS NOT NULL
               )
               SELECT l.thread_id, l.ticket_no, l.client_name, l.project_name,
                      l.overall_score, l.verdict, l.evaluated_at,
                      c.price_amount, c.price_currency, c.deal_outcome,
                      c.verify_status, c.content_stale
               FROM latest l
               LEFT JOIN dbo.ProposalContent c ON c.thread_id = l.thread_id
               WHERE l.rn = 1""",
        ).fetchall()

    items = []
    for r in rows:
        items.append({
            "thread_id": str(r[0]), "ticket_no": r[1], "client_name": r[2] or "",
            "project_name": r[3] or "",
            "overall_score": float(r[4]) if r[4] is not None else None, "verdict": r[5],
            "evaluated_at": r[6], "price_amount": float(r[7]) if r[7] is not None else None,
            "price_currency": r[8], "deal_outcome": r[9] or "Pending",
            "verify_status": r[10], "content_stale": bool(r[11]) if r[11] is not None else False,
        })

    total = len(items)
    scored = [i["overall_score"] for i in items if i["overall_score"] is not None]
    won = sum(1 for i in items if i["deal_outcome"] == "Won")
    lost = sum(1 for i in items if i["deal_outcome"] == "Lost")
    pending_verify = sum(1 for i in items if i["verify_status"] == "pending_verify")

    # pipeline value ของดีล Pending — แยกตามสกุลเงิน (กันบวกข้ามสกุล)
    pipeline: dict[str, float] = {}
    for i in items:
        if i["deal_outcome"] == "Pending" and i["price_amount"] is not None:
            cur = i["price_currency"] or "?"
            pipeline[cur] = pipeline.get(cur, 0.0) + i["price_amount"]

    verdict_counts = {"Strong": 0, "Adequate": 0, "Weak": 0, "Critical": 0}
    for i in items:
        if i["verdict"] in verdict_counts:
            verdict_counts[i["verdict"]] += 1

    # trend รายเดือน — avg score + win rate (bucket ตามเดือนที่ประเมิน)
    by_month: dict[str, dict] = {}
    for i in items:
        if i["evaluated_at"] and i["overall_score"] is not None:
            m = str(i["evaluated_at"])[:7]  # YYYY-MM
            b = by_month.setdefault(m, {"scores": [], "won": 0, "lost": 0})
            b["scores"].append(i["overall_score"])
            if i["deal_outcome"] == "Won":
                b["won"] += 1
            elif i["deal_outcome"] == "Lost":
                b["lost"] += 1
    trend = []
    for m, b in sorted(by_month.items()):
        decided = b["won"] + b["lost"]
        trend.append({
            "month": m,
            "avg_score": round(sum(b["scores"]) / len(b["scores"]), 2),
            "count": len(b["scores"]),
            "won": b["won"], "lost": b["lost"],
            "win_rate": round(b["won"] / decided, 3) if decided > 0 else None,
        })

    def _slim(i: dict) -> dict:
        return {k: i[k] for k in ("thread_id", "ticket_no", "client_name", "project_name",
                                  "overall_score", "verdict", "deal_outcome",
                                  "verify_status", "content_stale", "price_amount", "price_currency")}

    needs_attention = [_slim(i) for i in items
                       if i["verify_status"] == "pending_verify"
                       or i["deal_outcome"] == "Pending"
                       or i["content_stale"]]
    low_score = [_slim(i) for i in items if i["verdict"] in ("Weak", "Critical")]
    low_score.sort(key=lambda x: x["overall_score"] if x["overall_score"] is not None else 99)

    return {
        "kpi": {
            "total_proposals": total,
            "avg_score": round(sum(scored) / len(scored), 2) if scored else None,
            "win_rate": round(won / (won + lost), 3) if (won + lost) > 0 else None,
            "won": won, "lost": lost, "pending_deals": total - won - lost,
            "pipeline": [{"currency": c, "amount": a} for c, a in sorted(pipeline.items(), key=lambda x: -x[1])],
            "pending_verify": pending_verify,
        },
        "verdict_breakdown": verdict_counts,
        "score_trend": trend,
        "needs_attention": needs_attention,
        "low_score": low_score,
    }


# ---------- History (F17/F27) ----------
def get_thread_scores(thread_id: str) -> list[dict]:
    with _conn() as cn:
        cur = cn.execute(
            """SELECT ticket_no, version_no, status, score_source, overall_score, verdict, evaluated_at
               FROM dbo.vw_ThreadScores WHERE thread_id = ? ORDER BY version_no""",
            thread_id,
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------- Schema migration จากโค้ด (idempotent) ----------
# ใช้แนวเดียวกับ ensure_rbac_schema() ที่มีอยู่เดิม — เรียกซ้ำได้ ไม่แตะข้อมูลเดิม
# มีเพราะเครื่องที่ deploy มักไม่มี SQL client และ DB อยู่หลัง Managed Identity
# เนื้อหาต้องตรงกับ sql/migration_audit_log.sql และ sql/migration_coach_jobs.sql
def ensure_audit_schema() -> bool:
    """สร้าง dbo.AuditLog ถ้ายังไม่มี. คืน True ถ้าสร้างในรอบนี้."""
    with _conn() as cn:
        exists = cn.execute("SELECT OBJECT_ID('dbo.AuditLog','U')").fetchone()[0] is not None
        if not exists:
            cn.execute(
                """CREATE TABLE dbo.AuditLog (
                       audit_id      UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
                       occurred_at   DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
                       actor_user_id UNIQUEIDENTIFIER NULL,
                       actor_email   NVARCHAR(256)    NULL,
                       actor_role    NVARCHAR(50)     NULL,
                       actor_ip      NVARCHAR(45)     NULL,
                       action        NVARCHAR(50)     NOT NULL,
                       target_type   NVARCHAR(30)     NOT NULL,
                       target_id     NVARCHAR(100)    NULL,
                       target_label  NVARCHAR(300)    NULL,
                       before_json   NVARCHAR(MAX)    NULL,
                       after_json    NVARCHAR(MAX)    NULL)"""
            )
            cn.execute("CREATE INDEX IX_AuditLog_target ON dbo.AuditLog (target_type, target_id, occurred_at DESC)")
            cn.execute("CREATE INDEX IX_AuditLog_actor ON dbo.AuditLog (actor_email, occurred_at DESC)")
            cn.execute("CREATE INDEX IX_AuditLog_occurred ON dbo.AuditLog (occurred_at DESC)")
            cn.commit()
        return not exists


def ensure_coach_schema() -> bool:
    """สร้าง dbo.CoachJobs ถ้ายังไม่มี. คืน True ถ้าสร้างในรอบนี้."""
    with _conn() as cn:
        exists = cn.execute("SELECT OBJECT_ID('dbo.CoachJobs','U')").fetchone()[0] is not None
        if not exists:
            cn.execute(
                """CREATE TABLE dbo.CoachJobs (
                       job_id        UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
                       thread_id     UNIQUEIDENTIFIER NOT NULL
                                     REFERENCES dbo.ProposalThreads(thread_id),
                       audience_desc NVARCHAR(500)    NOT NULL,
                       content_hash  NVARCHAR(64)     NULL,
                       status        NVARCHAR(20)     NOT NULL DEFAULT 'Processing',
                       guideline     NVARCHAR(MAX)    NULL,
                       error_message NVARCHAR(500)    NULL,
                       requested_by  NVARCHAR(256)    NULL,
                       created_at    DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
                       completed_at  DATETIME2        NULL)"""
            )
            cn.execute(
                "CREATE INDEX IX_CoachJobs_reuse ON dbo.CoachJobs (thread_id, content_hash, status) "
                "INCLUDE (audience_desc)"
            )
            cn.commit()
        return not exists


def missing_tables() -> list[str]:
    """ตารางที่ Wave 1/3 ต้องมีแต่ยังไม่มี — ให้ UI แสดงสถานะได้ก่อนกดสร้าง."""
    with _conn() as cn:
        return [
            t for t in ("AuditLog", "CoachJobs")
            if cn.execute(f"SELECT OBJECT_ID('dbo.{t}','U')").fetchone()[0] is None
        ]


# ---------- CoachJobs (Wave 3 / G01) ----------
def find_reusable_coach(thread_id: str, audience_desc: str, content_hash: str) -> dict | None:
    """ผล coach เดิมที่ยังใช้ได้ (thread + ผู้ฟัง + เนื้อหา ตรงกันเป๊ะ และ Done แล้ว).

    ประหยัดโทเคน: กดปุ่มกลุ่มผู้ฟังเดิมซ้ำ ไม่ต้องเรียก LLM ใหม่.
    เนื้อหาเปลี่ยน (มี version ใหม่) -> hash ไม่ตรง -> ไม่ reuse (ผลเก่าถือว่าล้าสมัย)
    """
    with _conn() as cn:
        row = cn.execute(
            """SELECT TOP 1 job_id, guideline FROM dbo.CoachJobs
               WHERE thread_id = ? AND audience_desc = ? AND content_hash = ? AND status = 'Done'
               ORDER BY created_at DESC""",
            thread_id, audience_desc[:500], content_hash,
        ).fetchone()
        return {"job_id": str(row[0]), "guideline": row[1]} if row else None


def create_coach_job(thread_id: str, audience_desc: str, content_hash: str, requested_by: str | None) -> str:
    job_id = str(uuid.uuid4())
    with _conn() as cn:
        cn.execute(
            """INSERT INTO dbo.CoachJobs (job_id, thread_id, audience_desc, content_hash, requested_by)
               VALUES (?, ?, ?, ?, ?)""",
            job_id, thread_id, audience_desc[:500], content_hash, (requested_by or None),
        )
        cn.commit()
    return job_id


def get_coach_job(job_id: str) -> dict | None:
    try:
        with _conn() as cn:
            row = cn.execute(
                """SELECT job_id, thread_id, audience_desc, status, guideline, error_message, created_at
                   FROM dbo.CoachJobs WHERE job_id = ?""",
                job_id,
            ).fetchone()
    except Exception:  # noqa: BLE001 — job_id รูปแบบผิด
        return None
    if not row:
        return None
    return {"job_id": str(row[0]), "thread_id": str(row[1]), "audience_desc": row[2],
            "status": row[3], "guideline": row[4], "error_message": row[5], "created_at": row[6]}


def finish_coach_job(job_id: str, guideline: str | None, error_message: str | None = None) -> None:
    status = "Failed" if error_message else "Done"
    err = error_message[:500] if error_message else None
    with _conn() as cn:
        cn.execute(
            """UPDATE dbo.CoachJobs
               SET status = ?, guideline = ?, error_message = ?, completed_at = SYSUTCDATETIME()
               WHERE job_id = ?""",
            status, guideline, err, job_id,
        )
        cn.commit()


# ---------- AuditLog (Wave 1 / C02, C04) ----------
def insert_audit(
    actor_user_id: str | None,
    actor_email: str | None,
    actor_role: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    target_label: str | None,
    before_json: str | None,
    after_json: str | None,
    actor_ip: str | None = None,
) -> None:
    """เขียน 1 แถวลง dbo.AuditLog. caller (shared.audit.write) กลืน exception ให้แล้ว."""
    with _conn() as cn:
        cn.execute(
            """INSERT INTO dbo.AuditLog
                 (audit_id, actor_user_id, actor_email, actor_role, actor_ip,
                  action, target_type, target_id, target_label, before_json, after_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            str(uuid.uuid4()), actor_user_id, actor_email, actor_role, (actor_ip or None),
            action, target_type, target_id, target_label, before_json, after_json,
        )
        cn.commit()


def list_audit(
    thread_id: str | None = None, actor_email: str | None = None, limit: int = 200
) -> list[dict]:
    """C04 — อ่าน audit ล่าสุดก่อน. กรองด้วย thread (target_id) หรือผู้กระทำ (email) ได้."""
    limit = max(1, min(int(limit), 1000))
    where, params = [], []
    if thread_id:
        where.append("target_id = ?")
        params.append(str(thread_id))
    if actor_email:
        where.append("LOWER(actor_email) = ?")
        params.append(actor_email.strip().lower())
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with _conn() as cn:
        cur = cn.execute(
            f"""SELECT TOP (?) audit_id, occurred_at, actor_email, actor_role, actor_ip, action,
                       target_type, target_id, target_label, before_json, after_json
                FROM dbo.AuditLog {clause}
                ORDER BY occurred_at DESC""",
            limit, *params,
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
