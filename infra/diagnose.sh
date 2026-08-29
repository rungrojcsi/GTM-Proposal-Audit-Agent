#!/usr/bin/env bash
# =====================================================================
# เก็บข้อมูลการตั้งค่า Azure ที่ต้องใช้วินิจฉัย -> เขียนลงไฟล์ในโปรเจค
#
# ทำไมต้องมีสคริปต์นี้: ผู้ช่วย (Claude) อ่าน ~/.azure ไม่ได้ (sandbox บล็อก)
# จึงสั่ง az เองไม่ได้ — Boss รันตัวนี้ครั้งเดียว แล้วผู้ช่วยอ่านผลจากไฟล์ได้
#
#   ./diagnose.sh
#   -> เขียนที่ infra/.diagnose-output.txt
#
# 🔒 ความปลอดภัย: ดึงเฉพาะ "ชื่อ" ของ App Settings ไม่ดึงค่า
#    (ค่าจริงมี AZURE_OPENAI_KEY / SQL_CONNECTION_STRING / BLOB_CONNECTION_STRING)
#    และไม่ดึง deployment token ใด ๆ — ไฟล์ผลลัพธ์จึงไม่มี secret
#    ไฟล์นี้ถูก gitignore ไว้แล้ว
# =====================================================================
set -uo pipefail

RG="${RESOURCE_GROUP:-rg-proposal-evaluator}"
OUT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.diagnose-output.txt"

command -v az >/dev/null || { echo "ไม่พบ az"; exit 1; }
az account show >/dev/null 2>&1 || { echo "ยังไม่ได้ login — รัน 'az login' ก่อน"; exit 1; }

FUNC="$(az functionapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"
SWA="$(az staticwebapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"

{
  echo "# Azure diagnosis — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "# resource group : $RG"
  echo "# function app   : ${FUNC:-<ไม่พบ>}"
  echo "# static web app : ${SWA:-<ไม่พบ>}"
  echo

  echo "════════ 1) SWA linked backend (สำคัญสุด — ตัดสินว่าต้องตั้ง IP rule ไหม) ════════"
  az staticwebapp backends show -g "$RG" -n "$SWA" -o json 2>&1 || echo "(คำสั่งไม่สำเร็จ / ไม่มี linked backend)"
  echo

  echo "════════ 2) SWA environments (มี preview อยู่แล้วไหม) ════════"
  az staticwebapp environment list -g "$RG" -n "$SWA" \
    --query "[].{name:name, hostname:hostname, status:status}" -o json 2>&1 || echo "(ไม่สำเร็จ)"
  echo

  echo "════════ 3) Function App — network + runtime ════════"
  az functionapp show -g "$RG" -n "$FUNC" -o json \
    --query "{state:state, httpsOnly:httpsOnly, defaultHostName:defaultHostName,
              publicNetworkAccess:publicNetworkAccess,
              vnetSubnet:virtualNetworkSubnetId,
              linuxFxVersion:siteConfig.linuxFxVersion,
              ipRules:siteConfig.ipSecurityRestrictions,
              scmIpRules:siteConfig.scmIpSecurityRestrictions,
              scmUsesMain:siteConfig.scmIpSecurityRestrictionsUseMain}" 2>&1 || echo "(ไม่สำเร็จ)"
  echo

  echo "════════ 4) access-restriction (มุมมองแบบสรุป) ════════"
  az functionapp config access-restriction show -g "$RG" -n "$FUNC" -o json 2>&1 || echo "(ไม่สำเร็จ)"
  echo

  echo "════════ 5) private endpoint (ถ้ามี = ปลอดภัยอยู่แล้ว) ════════"
  az network private-endpoint list -g "$RG" \
    --query "[].{name:name, target:privateLinkServiceConnections[0].privateLinkServiceId}" -o json 2>&1 || echo "(ไม่สำเร็จ)"
  echo

  echo "════════ 6) App Settings — ชื่อเท่านั้น (ไม่ดึงค่า เพราะมี secret) ════════"
  az functionapp config appsettings list -g "$RG" -n "$FUNC" \
    --query "sort_by([].{name:name}, &name)" -o tsv 2>&1 || echo "(ไม่สำเร็จ)"
  echo
  echo "-- ตรวจเฉพาะตัวที่ต้องไม่มี --"
  for k in AUTH_DEV_MODE IP_RESTRICTION_OFF; do
    v="$(az functionapp config appsettings list -g "$RG" -n "$FUNC" \
          --query "[?name=='$k'] | length(@)" -o tsv 2>/dev/null)"
    echo "$k : ${v:-0} รายการ  $([ "${v:-0}" = "0" ] && echo '(ดี)' || echo '(⚠ ต้องลบ)')"
  done
  echo

  echo "════════ 7) Python version ของ Function App ════════"
  az functionapp config show -g "$RG" -n "$FUNC" \
    --query "{pythonVersion:pythonVersion, linuxFxVersion:linuxFxVersion}" -o json 2>&1 || echo "(ไม่สำเร็จ)"
  echo

  echo "════════ 8) Storage queue ที่ต้องมี (eval-jobs / coach-jobs) ════════"
  # หาชื่อ storage account จาก resource group โดยตรง — ไม่แตะ connection string
  # (ก่อนหน้านี้ใช้ค่าของ AzureWebJobsStorage ซึ่งเป็น secret; เลี่ยงไปเลยดีกว่า)
  for ST in $(az storage account list -g "$RG" --query "[].name" -o tsv 2>/dev/null); do
    echo "-- storage account: $ST"
    az storage queue list --account-name "$ST" --auth-mode login \
      --query "[].name" -o tsv 2>&1 || echo "   (อ่าน queue ไม่ได้ — ต้องมีสิทธิ์ Storage Queue Data Reader)"
  done
} > "$OUT" 2>&1

echo "เขียนผลไว้ที่:"
echo "  $OUT"
echo
echo "ไฟล์นี้ไม่มี secret (ดึงเฉพาะชื่อ App Settings) และถูก gitignore ไว้แล้ว"
echo "บอกผู้ช่วยว่า 'อ่านผล diagnose' ได้เลย"
