"""Import bootstrap shared by every test module in this folder.

ทำให้ `import shared.xxx` ใช้ได้จากที่นี่ (เหมือน eval/run_eval.py) โดยไม่ต้อง
ติดตั้ง package หรือแตะ sys.path ของ Azure Functions runtime จริง.
"""
import sys
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))
