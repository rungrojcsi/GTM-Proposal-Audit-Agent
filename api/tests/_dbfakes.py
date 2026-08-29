"""Fake pyodbc connection/cursor for testing shared/db.py without a real Azure SQL DB.

ปรัชญา: db.py เป็น thin wrapper รอบ SQL — เราไม่ตรวจ SQL ถูกต้องตาม T-SQL จริง (ต้องมี DB จริง)
แต่ตรวจว่า "โค้ด python เรียก SQL/ประกอบ param/แปลง row->dict ถูกตามที่ตั้งใจ" — เช่น
WHERE clause branch ถูกเลือกตาม argument, param เรียงถูกตำแหน่ง, commit ถูกเรียกตอนที่ควรเขียนจริง,
error path เดิม (try/except ที่มีอยู่แล้วใน db.py) ยังทำงานเหมือนเดิม.
"""


class FakeCursor:
    def __init__(self, description=None, fetchone_result=None, fetchall_result=None, rowcount=-1):
        self.description = description or []
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result if fetchall_result is not None else []
        self.rowcount = rowcount

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_result


class FakeConnection:
    """Records every execute() call. `handler(sql, params) -> FakeCursor` decides what each call returns.

    ใช้ `sequence_handler([...])` สำหรับ query ลำดับตายตัว (ไม่มี branch ตาม data ที่อ่านมา)
    หรือเขียน handler เองเมื่อ logic แตกกิ่งตามผลลัพธ์ query ก่อนหน้า (เช่น ensure_rbac_schema).
    """

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, tuple]] = []
        self.commit_count = 0

    def execute(self, sql, *params):
        self.calls.append((sql, params))
        return self.handler(sql, params)

    def commit(self):
        self.commit_count += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def sql_calls(self) -> list[str]:
        return [c[0] for c in self.calls]


def sequence_handler(cursors: list) -> "callable":
    """คืน handler ที่ตอบ cursor ตามลำดับที่กำหนด — call ที่เกินลิสต์ = ใช้ตัวสุดท้ายซ้ำ."""
    state = {"i": 0}

    def handler(sql, params):
        i = min(state["i"], len(cursors) - 1)
        state["i"] += 1
        return cursors[i]

    return handler


def raising_connection(error: Exception) -> FakeConnection:
    """connection ที่ execute() ครั้งแรกก็ raise ทันที — จำลอง DB ล่ม/thread_id รูปแบบผิด."""

    def handler(sql, params):
        raise error

    return FakeConnection(handler)
