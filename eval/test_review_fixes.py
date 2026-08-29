"""เทสต์คุมบั๊กที่พบจาก code review 2026-08-15 + ภาษาของ Presentation Coach — รันโค้ดจริง ไม่ใช่ตรวจข้อความ

  1. delete_thread ต้องลบ dbo.CoachJobs ด้วย ไม่งั้น FK ค้าง -> ลบโปรเจคไม่ได้ตลอดไป
     (CoachJobs.thread_id -> ProposalThreads ไม่มี ON DELETE CASCADE)
  2. _DETECT_SYSTEM ต้องมีโทเคน "" อยู่จริงใน prompt ที่ส่งให้โมเดล
     (เขียนใน double-quote จะกลายเป็นต่อสตริงว่าง -> โทเคนหายเงียบ)
  3. json_text ต้องแกะ JSON ออกจากคำตอบที่ห่อ fence ได้ทุกทรง
  4. Presentation Coach ต้องตอบตามภาษาของผลประเมิน (เดิมตรึงไทย) + cache ต้องไม่ข้ามภาษา

stub เฉพาะ pyodbc (ไม่มีในเครื่อง dev และไม่เกี่ยวกับตรรกะที่ทดสอบ) — ตัว delete_thread
ที่ถูกเรียกคือของจริงจาก api/shared/db.py

    python3 eval/test_review_fixes.py
"""
from __future__ import annotations

import ast
import pathlib
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
API = HERE.parent / "api"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    results.append((ok, f"{'✅' if ok else '❌'} {label}{chr(10) + '     ' + detail if detail else ''}"))


# ---------------------------------------------------------------- stub pyodbc
class _FakeCursor:
    rowcount = 1

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeConn:
    """จด SQL ทุกคำสั่งที่ถูกสั่ง เพื่อตรวจว่า delete_thread ลบตารางไหนบ้าง."""

    def __init__(self, log: list[str]):
        self.log = log

    def execute(self, sql, *params):
        self.log.append(" ".join(sql.split()))
        return _FakeCursor()

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


pyodbc_stub = types.ModuleType("pyodbc")
pyodbc_stub.Connection = object
pyodbc_stub.connect = lambda *a, **k: None
sys.modules["pyodbc"] = pyodbc_stub

sys.path.insert(0, str(API))
from shared import db, evaluation, llm  # noqa: E402

# ---------------------------------------------------------------- 1) delete_thread
SQL_LOG: list[str] = []
db._conn = lambda: _FakeConn(SQL_LOG)          # type: ignore[assignment]
db.delete_thread("00000000-0000-0000-0000-000000000000")

tables = [t for stmt in SQL_LOG for t in ("CoachJobs", "ProposalContent", "Comments",
                                          "Submissions", "ProposalThreads", "EvaluationResults")
          if f"dbo.{t} " in stmt or f"dbo.{t}\n" in stmt or stmt.endswith(f"dbo.{t}")]
order = [t for i, t in enumerate(tables) if t not in tables[:i]]

check("CoachJobs" in order, "delete_thread ลบ dbo.CoachJobs ด้วย", f"ลำดับที่ลบจริง: {order}")
if "CoachJobs" in order and "ProposalThreads" in order:
    check(order.index("CoachJobs") < order.index("ProposalThreads"),
          "ลบ CoachJobs ก่อน ProposalThreads (ไม่งั้น FK ยังพัง)")
missing = [t for t in ("EvaluationResults", "ProposalContent", "Comments", "Submissions",
                       "ProposalThreads") if t not in order]
check(not missing, "ตารางลูกเดิมยังถูกลบครบเหมือนเดิม", f"ขาด: {missing}" if missing else "")

# ---------------------------------------------------------------- 2) prompt โทเคน ""
src = (API / "shared" / "evaluation.py").read_text(encoding="utf-8")
prompt = next(
    ast.literal_eval(n.value)
    for n in ast.walk(ast.parse(src))
    if isinstance(n, ast.Assign)
    for t in n.targets
    if isinstance(t, ast.Name) and t.id == "_DETECT_SYSTEM"
)
tail = prompt.split(";")[-1].strip()
check('use "" when' in prompt, "_DETECT_SYSTEM มีโทเคน \"\" ครบใน prompt จริง", f"ท้าย prompt: {tail!r}")
check("use  when" not in prompt, "ไม่มีร่องรอยสตริงว่างถูกกลืน (ช่องว่างคู่)")
check(prompt is evaluation._DETECT_SYSTEM or prompt == evaluation._DETECT_SYSTEM,
      "ค่าที่ตรวจคือค่าเดียวกับที่โมดูลใช้จริง")

# ---------------------------------------------------------------- 3) json_text
CASES = [
    ('{"a": 1}', '{"a": 1}', "JSON สะอาด ต้องไม่ถูกแตะ"),
    ('---\n{"a": 1}', '{"a": 1}', "front matter --- แบบ gemma4:26b"),
    ('```json\n{"a": 1}\n```', '{"a": 1}', "fence หลายบรรทัด"),
    ('```json {"a": 1}\n```', '{"a": 1}', "fence ที่ { อยู่บรรทัดเดียวกับ fence"),
    ('Here you go: {"a": 1}', '{"a": 1}', "มีข้อความนำหน้า"),
]
for raw, want, why in CASES:
    got = llm.json_text(raw)
    check(got.strip() == want, f"json_text — {why}", f"ได้ {got!r}" if got.strip() != want else "")

# ---------------------------------------------------------------- 4) Presentation Coach ตามภาษา
# ดัก llm.chat เพื่อจับ prompt ที่ถูกสร้างจริง — ไม่เรียก LLM
from shared import presentation  # noqa: E402

CAPTURED: dict = {}


class _Msg:
    content = "ok"


class _Choice:
    message = _Msg()


class _Resp:
    choices = [_Choice()]


presentation.llm.client_and_model = lambda: (object(), "fake-model")          # type: ignore[assignment]
presentation.llm.chat = lambda client, **kw: (CAPTURED.update(kw), _Resp())[1]  # type: ignore[assignment]

TH_MARK, EN_MARK = "## โฟกัสหลัก", "## Main Focus"
for lang, want, other in (("th", TH_MARK, EN_MARK), ("en", EN_MARK, TH_MARK)):
    CAPTURED.clear()
    presentation.coach_guideline("proposal text", "ผู้บริหารระดับสูง", lang)
    sysmsg = CAPTURED["messages"][0]["content"]
    check(want in sysmsg and other not in sysmsg,
          f"coach lang='{lang}' -> prompt สั่งหัวข้อ {want!r}",
          f"หัวข้อที่พบ: {[h for h in (TH_MARK, EN_MARK) if h in sysmsg]}")

CAPTURED.clear()
presentation.coach_guideline("t", "a", "")   # ค่าว่าง/ไม่รู้จัก -> ไทย (ของเดิม)
check(TH_MARK in CAPTURED["messages"][0]["content"], "lang ว่าง/ไม่รู้จัก -> ใช้ไทยเหมือนเดิม")

# กุญแจ reuse ต้องต่างกันตามภาษา ไม่งั้นสลับภาษาแล้วได้ guideline เก่าจาก cache
h_th, h_en = presentation.coach_cache_key("same text", "th"), presentation.coach_cache_key("same text", "en")
check(h_th != h_en, "กุญแจ reuse ต่างกันเมื่อภาษาต่างกัน (เนื้อหาเดิม)")
check(len(h_th) == 64, "กุญแจยังยาว 64 อักขระ พอดีคอลัมน์ content_hash", f"ยาว {len(h_th)}")
check(h_th == presentation.coach_cache_key("same text", "TH"), "ภาษาไม่สนตัวพิมพ์ใหญ่เล็ก")
check(h_th == presentation.coach_cache_key("same text", None), "lang เป็น None -> ถือเป็นไทย (ค่าเดิม)")

print()
for _, line in results:
    print(line)
_f = [l for ok, l in results if not ok]
print(f"\n{'✅ ผ่านทั้งหมด' if not _f else f'❌ ไม่ผ่าน {len(_f)} ข้อ'} ({len(results) - len(_f)}/{len(results)})")
sys.exit(1 if _f else 0)
