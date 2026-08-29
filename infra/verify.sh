#!/usr/bin/env bash
# =====================================================================
# ตรวจสถานะหลัง deploy — เขียนผลลงไฟล์ให้ผู้ช่วยอ่านต่อ
#
#   ./verify.sh
#   -> infra/.verify-output.txt
#
# ตรวจ 5 อย่างที่ต้องผ่านก่อนถือว่า deploy สำเร็จจริง:
#   1) function ถูกลงทะเบียนครบ 36 ตัว (34 HTTP + 2 queue worker)
#      ถ้าว่าง/ไม่ครบ = โมดูล import พัง -> แอปล่มทั้งระบบ
#   2) log ตอน start เจอ 'guard: ทุก endpoint ประกาศสิทธิ์ครบ'
#   3) ไม่มี 'SECURITY: endpoints missing from guard.ROUTE_PERMS'
#   4) คิว eval-jobs + coach-jobs มีครบ
#   5) ตาราง AuditLog / CoachJobs ถูกสร้างแล้ว (ตรวจผ่าน API — ต้อง login จึงบอกวิธีไว้)
#
# 🔒 ไม่ดึงค่า App Settings / secret ใด ๆ
# =====================================================================
set -uo pipefail

RG="${RESOURCE_GROUP:-rg-proposal-evaluator}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/.verify-output.txt"

# นับจำนวน function ที่ "ควรมี" จากโค้ดจริง — ไม่ hardcode เลขไว้ในสคริปต์
# (เลข hardcode ล้าสมัยทุกครั้งที่เพิ่ม endpoint แล้วทำให้อ่านผลผิด)
EXPECT_FN="$(grep -cE '^@app\.(route|queue_trigger)' "$HERE/../api/function_app.py" 2>/dev/null || echo 0)"
[ "${EXPECT_FN:-0}" -gt 0 ] || EXPECT_FN=36   # อ่านไฟล์ไม่ได้ -> ใช้ค่าที่ทราบล่าสุด

command -v az >/dev/null || { echo "ไม่พบ az"; exit 1; }
az account show >/dev/null 2>&1 || { echo "ยังไม่ได้ login — รัน 'az login'"; exit 1; }

FUNC="$(az functionapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"
SWA="$(az staticwebapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"

{
  echo "# Verify after deploy — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "# function app: ${FUNC:-<ไม่พบ>}   static web app: ${SWA:-<ไม่พบ>}"
  echo

  echo "════════ 1) function ที่ลงทะเบียนอยู่ (ต้องได้ $EXPECT_FN ตัว) ════════"
  LIST="$(az functionapp function list -g "$RG" -n "$FUNC" --query "[].name" -o tsv 2>&1)"
  N="$(printf '%s\n' "$LIST" | grep -c . || true)"
  echo "จำนวนที่พบ: $N   (นับจาก guard.ROUTE_PERMS + worker ในโค้ด = $EXPECT_FN)"
  printf '%s\n' "$LIST" | sed 's|^'"$FUNC"'/||' | sort
  echo
  if [ "$N" -eq 0 ]; then
    echo ">>> ❌ ไม่มี function เลย = โมดูล import พัง แอปใช้ไม่ได้ (ดู log ข้อ 2/3)"
    echo "    สาเหตุที่เคยเจอ: เรียกอะไรที่แตะ app (เช่น app.get_functions()) ที่ระดับโมดูล"
  elif [ "$N" -lt "$EXPECT_FN" ]; then
    echo ">>> ⚠ ได้ $N ตัว น้อยกว่า $EXPECT_FN — เทียบรายชื่อกับ guard.ROUTE_PERMS ว่าตัวไหนหาย"
  else
    echo ">>> ✅ ครบ"
  fi
  echo

  echo "════════ 2+3) log ล่าสุด — หา guard startup / SECURITY / import error ════════"
  echo "-- ดึง log ผ่าน Application Insights (ถ้าตั้งไว้) --"
  AI_APP="$(az monitor app-insights component show -g "$RG" \
             --query "[0].appId" -o tsv 2>/dev/null || true)"
  if [ -n "${AI_APP:-}" ]; then
    AI_OUT="$(az monitor app-insights query --app "$AI_APP" --analytics-query \
      "traces | where timestamp > ago(30m)
       | where message contains 'guard:' or message contains 'SECURITY'
            or message contains 'Traceback' or message contains 'ModuleNotFound'
            or severityLevel >= 3
       | order by timestamp desc | take 40
       | project timestamp, severityLevel, message" -o table 2>&1 | head -60)"
    # เดิมถ้า query ล้ม/ว่าง จะไม่พิมพ์อะไรเลย -> อ่านผลแล้วเข้าใจผิดว่า "ไม่มี error"
    if [ -n "${AI_OUT// /}" ]; then
      printf '%s\n' "$AI_OUT"
    else
      echo "(query ไม่คืนอะไร — อาจไม่มี log เข้าเกณฑ์ใน 30 นาที หรือยังไม่ได้ติดตั้ง extension)"
      echo "   ติดตั้ง:  az extension add -n application-insights"
      echo "   ⚠ 'ว่าง' ที่นี่ไม่ได้แปลว่าไม่มี error — ให้ยึดผลข้อ 1 กับข้อ 6 เป็นหลัก"
    fi
  else
    echo "(ไม่พบ Application Insights component — ใช้คำสั่งนี้ดู log สดแทน)"
    echo "   az webapp log tail -g $RG -n $FUNC"
  fi
  echo

  echo "════════ 4) คิวที่ต้องมี ════════"
  STG="$(az storage account list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"
  echo "storage account: ${STG:-<ไม่พบ>}"
  QS="$(az storage queue list --account-name "$STG" --auth-mode login --query "[].name" -o tsv 2>&1)"
  printf '%s\n' "$QS"
  for q in eval-jobs coach-jobs; do
    printf '%s\n' "$QS" | grep -qx "$q" && echo "  ✅ $q" || echo "  ❌ $q ไม่มี — สร้าง: az storage queue create --name $q --account-name $STG --auth-mode login"
  done
  echo
  # คิว -poison เกิดขึ้นเองเมื่อ Azure retry งานครบจำนวนแล้วยังล้ม = มีงานที่ตายถาวร
  # ต้องรายงานเสมอ ไม่ใช่ปล่อยให้ไปเจอเองว่าผลประเมินหาย
  echo "-- งานที่ล้มเหลวถาวร (คิว -poison) --"
  FOUND_POISON=0
  for q in eval-jobs-poison coach-jobs-poison; do
    printf '%s\n' "$QS" | grep -qx "$q" && { echo "  ⚠ พบ $q"; FOUND_POISON=1; }
  done
  if [ "$FOUND_POISON" = "1" ]; then
    echo "  คิวนี้ถูกสร้างเมื่อ Azure retry งานครบจำนวนแล้วยังล้ม = เคยมีงานตายถาวรอย่างน้อย 1 งาน"
    echo "  (คิวไม่หายไปเองแม้ข้อความถูกอ่านออกหมดแล้ว — 'มีคิว' ไม่ได้แปลว่ายังมีงานค้าง)"
    echo
    echo "  นับ/อ่านเนื้อหาต้องมี role 'Storage Queue Data Reader' ก่อน:"
    echo "    az role assignment create --role 'Storage Queue Data Reader' \\"
    echo "      --assignee \$(az ad signed-in-user show --query id -o tsv) \\"
    echo "      --scope \$(az storage account show -g $RG -n $STG --query id -o tsv)"
    echo "  แล้วดูสาเหตุด้วย:"
    echo "    az storage message peek --queue-name eval-jobs-poison --num-messages 5 \\"
    echo "      --account-name $STG --auth-mode login"
    echo "  หมายเหตุ: az storage queue metadata show ไม่คืน approximateMessageCount (ได้ None) — ใช้ peek แทน"
  else
    echo "  ✅ ไม่มีคิว poison — ไม่เคยมีงานล้มเหลวถาวร"
  fi
  echo

  echo "════════ 5) ตาราง DB ที่ Wave 1/3 ต้องใช้ (AuditLog / CoachJobs) ════════"
  echo "ตรวจ/สร้างได้ 2 ทาง (ไม่ต้องเขียน SQL เอง):"
  echo "  1) ./migrate-db.sh --check     ตรวจอย่างเดียว   |  ./migrate-db.sh  สร้างให้เลย"
  echo "  2) เปิดแอป > Settings > Database schema > 'ตรวจใหม่'"
  echo "     (ปุ่ม 'สร้างตารางที่ขาด' ใช้ได้เฉพาะเมื่อ Managed Identity มีสิทธิ์ db_ddladmin)"
  echo
  echo "════════ 6) ทดสอบด้วยตา (ชี้ขาดที่สุด) ════════"
  echo "เปิด https://green-stone-0ae1ea500.7.azurestaticapps.net"
  echo "  - login ผ่าน -> เห็นหน้า Evaluation Results = function ทำงาน"
  echo "  - ขึ้นหน้า 'เปิดแอปไม่ได้' -> API มีปัญหา (ดูข้อ 1-3)"
} > "$OUT" 2>&1

echo "เขียนผลไว้ที่:"
echo "  $OUT"
echo
echo "บอกผู้ช่วยว่า 'อ่านผล verify' ได้เลย"
