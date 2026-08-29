"""ตรวจว่า "ผู้ใช้เห็นข้ามโปรเจคกันไม่ได้" เป็นจริงไหม — รันโค้ด guard.py/auth.py ตัวจริง

ไม่ใช่การอ่านโค้ดแล้วเดา: import โมดูลจริงจาก api/shared แล้วป้อน "เมทริกซ์สิทธิ์ + ผู้ใช้ +
เจ้าของ thread" ที่ดึงสดจากฐานข้อมูล production เข้าไป จากนั้นเรียก guard.gate() /
guard.thread_access() ตรง ๆ แล้วดูว่าอนุญาตหรือปฏิเสธ

สิ่งที่ถูก stub มีแค่ 2 อย่างและไม่ใช่ตรรกะสิทธิ์:
  - azure.functions : เปลือก HttpRequest/HttpResponse (ไม่มี Azure runtime ในเครื่อง)
  - shared.db       : คืนข้อมูลที่ดึงมาจาก DB จริง (แทนการต่อ SQL ตอนรันเทส)

    python3 eval/test_isolation.py /tmp/rbac_live.txt
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
API = HERE.parent / "api"

# ---------------------------------------------------------------- โหลดข้อมูลจริง
dump = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rbac_live.txt")
PERMS: dict[str, dict[str, bool]] = {}
USERS: dict[str, dict] = {}     # email -> row
THREADS: dict[str, dict] = {}   # thread_id(lower) -> row
for line in dump.read_text(encoding="utf-8").splitlines():
    kind, *rest = line.strip().split("|")
    if kind == "PERM":
        role, page, can = rest
        PERMS.setdefault(role, {})[page] = can == "1"
    elif kind == "USER":
        uid, email, role, name = rest
        USERS[email.lower()] = {"user_id": uid, "email": email.lower(), "role": role, "display_name": name}
    elif kind == "THREAD":
        tid, ticket, owner = rest
        THREADS[tid.lower()] = {"ticket": ticket, "owner_id": None if owner == "NULL" else owner}

# ---------------------------------------------------------------- stub azure.functions
class HttpResponse:
    def __init__(self, body=None, status_code=200, **kw):
        self.body, self.status_code = body, status_code

class HttpRequest:
    def __init__(self, headers): self.headers = headers

azf = types.ModuleType("azure.functions")
azf.HttpResponse, azf.HttpRequest = HttpResponse, HttpRequest
azf.FunctionApp, azf.AuthLevel = object, types.SimpleNamespace(ANONYMOUS=0)
az = types.ModuleType("azure"); az.functions = azf
sys.modules["azure"], sys.modules["azure.functions"] = az, azf

# ---------------------------------------------------------------- stub shared.db
sys.path.insert(0, str(API))
import shared  # noqa: E402

db_stub = types.ModuleType("shared.db")
db_stub.PAGES = ("evaluate", "proposals", "library", "dashboard", "settings", "view_all", "manage_proposals")
db_stub.get_role_permissions = lambda role: PERMS.get(role, {})
db_stub.get_settings = lambda: {}                      # ไม่เปิดตัวกรอง IP
db_stub.get_or_create_user = lambda email, oid: USERS[email.lower()]
db_stub.get_thread_owner = lambda tid: (THREADS.get(str(tid).lower()) or {}).get("owner_id")
sys.modules["shared.db"] = db_stub
shared.db = db_stub

from shared import auth, guard  # noqa: E402

# ---------------------------------------------------------------- ตัวช่วย
def req_as(email: str | None):
    """สร้าง request ที่มี principal เหมือนที่ SWA ใส่ให้ (หรือไม่มี = ยังไม่ login)"""
    if email is None:
        return HttpRequest({})
    blob = base64.b64encode(json.dumps(
        {"identityProvider": "aad", "userId": USERS[email]["user_id"], "userDetails": email}
    ).encode()).decode()
    return HttpRequest({"x-ms-client-principal": blob})

results: list[tuple[bool, str]] = []

def check(label: str, got, want_allowed: bool):
    allowed = got is None
    ok = allowed == want_allowed
    results.append((ok, f"{'✅' if ok else '❌'} {label} -> {'อนุญาต' if allowed else f'ปฏิเสธ {got.status_code}'}"
                        f"{'' if ok else f'  (คาดว่าจะ{"อนุญาต" if want_allowed else "ปฏิเสธ"})'}"))

BOSS = "owner@example.com"
PLAIN = next(e for e, u in USERS.items() if u["role"] == "user")          # role 'user'
MGMT = next(e for e, u in USERS.items() if u["role"] == "management")
BOSS_THREAD = next(t for t, v in THREADS.items() if v["owner_id"] and v["owner_id"].lower() == USERS[BOSS]["user_id"].lower())

print(f"ข้อมูลจริงที่ใช้ทดสอบ: role {len(PERMS)} ตัว · ผู้ใช้ {len(USERS)} คน · thread {len(THREADS)} รายการ")
print(f"  ผู้ใช้ role 'user'       : {PLAIN}")
print(f"  ผู้ใช้ role 'management' : {MGMT}")
print(f"  thread ที่ Boss เป็นเจ้าของ: {THREADS[BOSS_THREAD]['ticket']}\n")

print("── ชั้นที่ 1: เปิดดู thread ของคนอื่น (guard.thread_access) ──")
u_plain = auth.current_user(req_as(PLAIN))
u_mgmt = auth.current_user(req_as(MGMT))
u_boss = auth.current_user(req_as(BOSS))
check(f"'{PLAIN}' (user) เปิด thread ของ Boss", guard.thread_access(u_plain, BOSS_THREAD), False)
check(f"'{MGMT}' (management) เปิด thread ของ Boss", guard.thread_access(u_mgmt, BOSS_THREAD), True)
check("Boss เปิด thread ของตัวเอง", guard.thread_access(u_boss, BOSS_THREAD), True)
check(f"'{PLAIN}' (user) เปิด thread ที่ไม่มีเจ้าของ", guard.thread_access(u_plain, "00000000-0000-0000-0000-000000000000"), False)

print("\n── ชั้นที่ 2: เข้าหน้า/endpoint (guard.gate) ──")
for fn, want in [("proposals", True), ("thread_detail", True), ("library_list", False),
                 ("library_detail", False), ("dashboard", False), ("users_list", False),
                 ("thread_delete", False), ("audit_list", False)]:
    _, deny = guard.gate(req_as(PLAIN), fn)
    check(f"'{PLAIN}' (user) เรียก {fn}", deny, want)

print("\n── ชั้นที่ 3: ยังไม่ login ──")
for fn in ("proposals", "library_list", "dashboard"):
    _, deny = guard.gate(req_as(None), fn)
    check(f"guest เรียก {fn}", deny, False)

print("\n── ชั้นที่ 4: ตัวกรองรายการ (ตรรกะเดียวกับ endpoint proposals) ──")
for email in (PLAIN, MGMT, BOSS):
    u = auth.current_user(req_as(email))
    owner = None if auth.has_page(u["role"], "view_all") else u["user_id"]
    mine = [v["ticket"] for v in THREADS.values()
            if owner is None or (v["owner_id"] or "").lower() == owner.lower()]
    print(f"  {email:<28} role={u['role']:<11} เห็น {len(mine)}/{len(THREADS)} รายการ {sorted(mine)}")
    results.append((
        (len(mine) == 0) if u["role"] == "user" else (len(mine) == len(THREADS)),
        f"{'✅' if ((len(mine)==0) if u['role']=='user' else (len(mine)==len(THREADS))) else '❌'} ตัวกรองรายการของ {email}",
    ))

print()
for _, line in results:
    print(line)
failed = [l for ok, l in results if not ok]
print(f"\n{'✅ ผ่านทั้งหมด' if not failed else '❌ ไม่ผ่าน ' + str(len(failed)) + ' ข้อ'} ({len(results) - len(failed)}/{len(results)})")
sys.exit(1 if failed else 0)
