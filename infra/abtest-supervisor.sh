#!/usr/bin/env bash
# =====================================================================
# ตัวคุมงาน A/B test — รันเองจนครบไม่ต้องมีคนเฝ้า
#
#   nohup bash abtest-supervisor.sh > .abtest-supervisor.log 2>&1 &
#
# ทำอะไร:
#   1) รอให้กระบวนการที่กำลังรันอยู่ (ถ้ามี) จบก่อน — วัดจาก "jsonl ไม่ขยับ"
#      เพราะแซนด์บ็อกซ์นี้อ่านรายการกระบวนการไม่ได้ (ps/pgrep/pkill ใช้ไม่ได้)
#   2) วนรัน ab-test-llm.sh (resume อยู่แล้ว) จนได้ครบ 63 รายการ
#   3) หยุดเองถ้า 2 รอบติดกันไม่มีรายการเพิ่ม (กันวนไม่จบเมื่อบางคู่ล้มถาวร)
#   4) สร้างรายงานสุดท้ายด้วย --report-only
#
# ปลอดภัยต่อการรันซ้ำ: ab-test-llm.sh ข้ามรายการที่ทำแล้วเสมอ
# =====================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || exit 1

RUNS="$HERE/.abtest-runs.jsonl"
TARGET=63              # 7 ไฟล์ × 3 engine × 3 รอบ
QUIET_SEC=420          # ต้องนิ่งเกินเวลานี้ถึงเชื่อว่าไม่มีใครรัน (ช้าสุดที่วัดได้ ~330s)
MAX_ROUNDS=12
STALL_LIMIT=2

count() { [ -f "$RUNS" ] && wc -l < "$RUNS" | tr -d ' ' || echo 0; }
mtime() { [ -f "$RUNS" ] && stat -f '%m' "$RUNS" || echo 0; }
stamp() { date '+%H:%M:%S'; }

echo "[$(stamp)] ตัวคุมงานเริ่มทำงาน — เป้าหมาย $TARGET รายการ (มีอยู่ $(count))"

# ---------- 1) รอให้ตัวที่รันอยู่จบ ----------
echo "[$(stamp)] รอให้กระบวนการที่รันอยู่จบก่อน (นิ่ง ${QUIET_SEC}s = ถือว่าจบ)"
while :; do
  before="$(mtime)"; n_before="$(count)"
  sleep "$QUIET_SEC"
  if [ "$(mtime)" = "$before" ]; then
    echo "[$(stamp)] นิ่งแล้ว ($(count) รายการ) — เริ่มรอบเก็บตก"
    break
  fi
  echo "[$(stamp)] ยังทำงานอยู่: $n_before -> $(count) รายการ"
  if [ "$(count)" -ge "$TARGET" ]; then
    echo "[$(stamp)] ครบ $TARGET แล้วระหว่างรอ"
    break
  fi
done

# ---------- 2) วนเก็บตกจนครบ ----------
stall=0
for round in $(seq 1 "$MAX_ROUNDS"); do
  n="$(count)"
  if [ "$n" -ge "$TARGET" ]; then
    echo "[$(stamp)] ครบ $n/$TARGET รายการแล้ว"
    break
  fi
  echo "[$(stamp)] รอบเก็บตก $round — มี $n/$TARGET รายการ"
  bash ab-test-llm.sh 2>&1 | sed "s/^/    /"
  after="$(count)"
  if [ "$after" -le "$n" ]; then
    stall=$((stall + 1))
    echo "[$(stamp)] ไม่มีรายการเพิ่ม (ติดกัน $stall ครั้ง)"
    [ "$stall" -ge "$STALL_LIMIT" ] && {
      echo "[$(stamp)] หยุด — บางคู่ล้มถาวร ไม่วนต่อ"
      break
    }
  else
    stall=0
    echo "[$(stamp)] เพิ่มเป็น $after รายการ"
  fi
done

# ---------- 3) รายงานสุดท้าย ----------
echo "[$(stamp)] สร้างรายงานสุดท้าย"
bash ab-test-llm.sh --report-only 2>&1 | sed "s/^/    /"
echo "[$(stamp)] เสร็จสิ้น — $(count) รายการดิบ · รายงานที่ .abtest-output.txt"
