#!/usr/bin/env bash
# =====================================================================
# Proposal Evaluator — redeploy โค้ดลงระบบที่รันอยู่แล้ว (macOS / Linux)
#
# ต่างจาก deploy.ps1: ตัวนั้น provision infra ใหม่ทั้งชุด ตัวนี้ deploy "โค้ด" เท่านั้น
#
# ค่าเริ่มต้น deploy ไป PREVIEW environment (ไม่แตะ production)
#   ./redeploy.sh              -> preview
#   ./redeploy.sh --prod       -> production (ต้องพิมพ์ยืนยันอีกชั้น)
#   ./redeploy.sh --api-only   -> เฉพาะ Function App
#   ./redeploy.sh --web-only   -> เฉพาะ frontend
#
# ด่านตรวจก่อน deploy (ปิดความเสี่ยง R2/R3/R8 ที่แผน Wave 1 ระบุไว้):
#   1) az login แล้วหรือยัง + subscription ถูกตัวไหม
#   2) AUTH_DEV_MODE ต้องไม่ถูกตั้งบน Function App  (ไม่งั้นทุกคนเป็น admin)
#   3) migration 2 ไฟล์ต้องรันแล้ว                   (ไม่งั้น audit + coach พัง)
#   4) ข้อจำกัดเน็ตเวิร์กบน Function App ต้องยังอยู่   (ไม่งั้นปลอม principal เป็น admin ได้)
# =====================================================================
set -euo pipefail

RG="${RESOURCE_GROUP:-rg-proposal-evaluator}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ENV="preview"
DO_API=1
DO_WEB=1

for arg in "$@"; do
  case "$arg" in
    --prod)     TARGET_ENV="production" ;;
    --api-only) DO_WEB=0 ;;
    --web-only) DO_API=0 ;;
    -h|--help)  sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "ไม่รู้จัก option: $arg" >&2; exit 2 ;;
  esac
done

c_red=$'\033[31m'; c_grn=$'\033[32m'; c_yel=$'\033[33m'; c_cya=$'\033[36m'; c_off=$'\033[0m'
say()  { printf "%s\n" "$*"; }
step() { printf "\n%s▶ %s%s\n" "$c_cya" "$*" "$c_off"; }
ok()   { printf "  %s✔%s %s\n" "$c_grn" "$c_off" "$*"; }
warn() { printf "  %s⚠%s %s\n" "$c_yel" "$c_off" "$*"; }
die()  { printf "\n%s✘ %s%s\n" "$c_red" "$*" "$c_off" >&2; exit 1; }

# ---------------------------------------------------------------- 0) เครื่องมือ
step "0/6 ตรวจเครื่องมือ"
for c in az func npm node rsync; do command -v "$c" >/dev/null || die "ไม่พบคำสั่ง '$c'"; done

# swa CLI: ใช้ตัวที่ติดตั้งเป็น devDependency ในโปรเจคก่อน (เวอร์ชันถูกล็อกไปกับ repo
# ไม่ต้องพึ่งว่าเครื่องไหนติดตั้ง global ไว้บ้าง) แล้วค่อย fallback ไป global
if [ -x "$ROOT/frontend/node_modules/.bin/swa" ]; then
  SWA="$ROOT/frontend/node_modules/.bin/swa"
  ok "swa (local devDependency): $("$SWA" --version 2>/dev/null | head -1)"
elif command -v swa >/dev/null; then
  SWA="swa"
  ok "swa (global): $(swa --version 2>/dev/null | head -1)"
else
  die "ไม่พบ 'swa' — ติดตั้งด้วย: (cd $ROOT/frontend && npm i -D @azure/static-web-apps-cli)"
fi
ok "az / func / npm พร้อม"

# ---------------------------------------------------------------- 1) login
step "1/6 ตรวจ Azure login"
ACC="$(az account show -o json 2>/dev/null)" || die "ยังไม่ได้ login — รัน 'az login' ก่อน"
say "  Subscription: $(printf '%s' "$ACC" | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')"
say "  Tenant      : $(printf '%s' "$ACC" | python3 -c 'import json,sys;print(json.load(sys.stdin)["tenantId"])')"

# ---------------------------------------------------------------- 2) หา resource
step "2/6 ค้นหา resource ใน resource group '$RG'"
FUNC_NAME="$(az functionapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null || true)"
SWA_NAME="$(az staticwebapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null || true)"
[ -n "$FUNC_NAME" ] || die "ไม่พบ Function App ใน '$RG' (ตั้ง RESOURCE_GROUP=... ถ้าชื่อไม่ตรง)"
[ -n "$SWA_NAME" ]  || die "ไม่พบ Static Web App ใน '$RG'"
ok "Function App   : $FUNC_NAME"
ok "Static Web App : $SWA_NAME"

# ---------------------------------------------------------------- 3) ด่านความปลอดภัย
step "3/6 ด่านตรวจความปลอดภัย"

# 3.1 AUTH_DEV_MODE — ถ้าตั้งไว้ = ทุกคนเป็น admin
DEV_MODE="$(az functionapp config appsettings list -g "$RG" -n "$FUNC_NAME" \
  --query "[?name=='AUTH_DEV_MODE'].value | [0]" -o tsv 2>/dev/null || true)"
if [ -n "$DEV_MODE" ] && [ "$DEV_MODE" != "None" ]; then
  die "พบ AUTH_DEV_MODE=$DEV_MODE บน Function App — ลบออกก่อน deploy
     az functionapp config appsettings delete -g $RG -n $FUNC_NAME --setting-names AUTH_DEV_MODE
     (โค้ดกันไว้แล้วว่าจะเพิกเฉยบน Azure แต่ไม่ควรปล่อยค้างไว้)"
fi
ok "ไม่มี AUTH_DEV_MODE ค้างอยู่"

# 3.2 Function App ต้องเรียกตรงจากภายนอกไม่ได้
#
# ⚠️ ตรวจด้วย "พฤติกรรมจริง" ไม่ใช่ดู ipSecurityRestrictions
# เหตุผล: SWA linked backend ป้องกันด้วย App Service Authentication ที่ Azure ตั้งให้เอง
# ไม่ได้ใช้ IP rule -> การดู ipSecurityRestrictions จะเห็น "Allow all / Any" เสมอ
# แล้วสรุปผิดว่าเปิดโหว่ (ยืนยันแล้วว่า /api/health ซึ่งเป็น ANONYMOUS ในโค้ด
# ยังตอบ 401 body 0 bytes = ถูกปฏิเสธที่ชั้นแพลตฟอร์มก่อนถึงโค้ด)
FUNC_HOST="$(az functionapp show -g "$RG" -n "$FUNC_NAME" --query defaultHostName -o tsv 2>/dev/null)"
DIRECT="$(curl -sS -o /dev/null -m 20 -w '%{http_code}' "https://$FUNC_HOST/api/health" 2>/dev/null || echo 000)"
case "$DIRECT" in
  401|403)
    ok "เรียกตรงเข้า Function App ถูกปฏิเสธ (HTTP $DIRECT) — SWA เป็นทางเข้าเดียว" ;;
  200)
    warn "เรียกตรงเข้า https://$FUNC_HOST/api/health ได้ HTTP 200 = เปิดรับจากอินเทอร์เน็ต"
    warn "header x-ms-client-principal ไม่มีลายเซ็นให้ตรวจ -> ปลอมเป็น admin ได้"
    warn "ตรวจว่า linked backend ยังผูกอยู่: az staticwebapp backends show -g $RG -n $SWA_NAME"
    read -r -p "  เข้าใจความเสี่ยงและจะไปต่อ? พิมพ์ 'i-understand': " ack
    [ "$ack" = "i-understand" ] || die "ยกเลิก — ปิดทางเข้าตรงก่อน" ;;
  000)
    warn "ยิง https://$FUNC_HOST/api/health ไม่ถึง (เน็ตเวิร์ก/timeout) — ข้ามการตรวจนี้" ;;
  *)
    warn "เรียกตรงได้ HTTP $DIRECT — ตรวจด้วยตาว่าไม่ใช่การเปิดรับสาธารณะ" ;;
esac

# 3.2b คิวที่ queue trigger ต้องใช้ (Wave 1 eval-jobs / Wave 3 coach-jobs)
STG="$(az storage account list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"
if [ -n "$STG" ]; then
  QUEUES="$(az storage queue list --account-name "$STG" --auth-mode login --query "[].name" -o tsv 2>/dev/null || echo "")"
  for q in eval-jobs coach-jobs; do
    if printf '%s\n' "$QUEUES" | grep -qx "$q"; then
      ok "คิว '$q' มีอยู่แล้ว"
    else
      warn "ไม่พบคิว '$q' — สร้างให้เดี๋ยวนี้"
      az storage queue create --name "$q" --account-name "$STG" --auth-mode login -o none 2>/dev/null \
        && ok "สร้างคิว '$q' แล้ว" \
        || warn "สร้างคิว '$q' ไม่สำเร็จ (ต้องมีสิทธิ์ Storage Queue Data Contributor) — Functions มักสร้างเองตอน start"
    fi
  done
else
  warn "หา storage account ไม่เจอ — ข้ามการตรวจคิว"
fi

# 3.3 migration — ตรวจจาก DB ไม่ได้ (VPN + Managed Identity) จึงต้องให้คนยืนยัน
say ""
say "  ${c_yel}migration ที่ต้องรันก่อน deploy:${c_off}"
say "    sql/migration_audit_log.sql    (Wave 1 — ไม่รัน = audit เขียนไม่ได้)"
say "    sql/migration_coach_jobs.sql   (Wave 3 — ไม่รัน = Presentation Coach พังทั้งฟีเจอร์)"
say ""
say "  ${c_yel}และตรวจ RolePermissions (R2) — role ที่มีผู้ใช้จริงต้องเปิดสิทธิ์ 'evaluate':${c_off}"
cat <<'SQL'
    SELECT r.name,
           MAX(CASE WHEN rp.page_key='evaluate' THEN rp.can_access END) AS can_evaluate,
           (SELECT COUNT(*) FROM dbo.Users u WHERE u.role = r.name)     AS users
    FROM dbo.Roles r LEFT JOIN dbo.RolePermissions rp ON rp.role_id = r.role_id
    GROUP BY r.name ORDER BY users DESC;
SQL
say ""
read -r -p "  รัน migration ทั้ง 2 ไฟล์ + ตรวจ RolePermissions แล้ว? พิมพ์ 'done': " mig
[ "$mig" = "done" ] || die "ยกเลิก — ทำ migration ให้เสร็จก่อน"
ok "ยืนยัน migration แล้ว"

# ---------------------------------------------------------------- 4) production gate
if [ "$TARGET_ENV" = "production" ]; then
  say ""
  warn "กำลังจะ deploy ลง PRODUCTION ที่มีผู้ใช้จริง"
  warn "รอบนี้เปลี่ยนชั้นสิทธิ์ทั้งระบบ + rewrite หน้าจอทั้งหมด"
  read -r -p "  พิมพ์ 'deploy-production' เพื่อยืนยัน: " prod
  [ "$prod" = "deploy-production" ] || die "ยกเลิก"
fi

# ---------------------------------------------------------------- 5) deploy
if [ "$DO_API" = 1 ]; then
  step "4/6 Deploy Function App -> $FUNC_NAME"

  # ⚠️ ห้าม publish จากโฟลเดอร์ที่อยู่บน OneDrive โดยตรง
  # func publish จะลบ __pycache__/.python_packages ก่อนสร้าง archive แต่ OneDrive
  # ล็อก/virtualize ไฟล์อยู่ -> "Operation timed out" ทุกครั้ง
  # วิธีแก้: คัดลอกเฉพาะไฟล์ที่ต้อง deploy ไปที่ชั่วคราวนอก OneDrive แล้ว publish จากที่นั่น
  STAGE="${TMPDIR:-/tmp}/pe-api-deploy"
  rm -rf "$STAGE"; mkdir -p "$STAGE"
  rsync -a \
    --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.python_packages' --exclude '.venv' --exclude 'venv' \
    --exclude 'local.settings.json' --exclude '.claude' --exclude '.DS_Store' \
    "$ROOT/api/" "$STAGE/"
  ok "เตรียมไฟล์ที่ $STAGE ($(find "$STAGE" -type f | wc -l | tr -d ' ') ไฟล์)"

  # เผื่อ artifact เก่าค้างในโปรเจค (ทำให้ publish รอบถัดไปติดอีก)
  rm -rf "$ROOT/api/__pycache__" "$ROOT/api/shared/__pycache__" "$ROOT/api/.python_packages" 2>/dev/null || true

  # --build remote: ให้ Azure ติดตั้ง dependency เอง (python ในเครื่องเป็นเวอร์ชันไหนก็ไม่สำคัญ)
  (cd "$STAGE" && func azure functionapp publish "$FUNC_NAME" --python --build remote)
  rm -rf "$STAGE"
  ok "deploy API แล้ว"
fi

if [ "$DO_WEB" = 1 ]; then
  step "5/6 Build + deploy frontend -> $SWA_NAME ($TARGET_ENV)"
  (cd "$ROOT/frontend" && npm run build)
  TOKEN="$(az staticwebapp secrets list --name "$SWA_NAME" -g "$RG" \
    --query "properties.apiKey" -o tsv)"
  [ -n "$TOKEN" ] || die "ดึง deployment token ไม่ได้"
  (cd "$ROOT/frontend" && "$SWA" deploy ./dist --deployment-token "$TOKEN" --env "$TARGET_ENV")
  unset TOKEN
  ok "deploy frontend แล้ว"
fi

# ---------------------------------------------------------------- 6) ตรวจหลัง deploy
step "6/6 ตรวจหลัง deploy"
HEALTH="https://$FUNC_NAME.azurewebsites.net/api/health"
say "  ยิง $HEALTH"
if curl -fsS -m 15 "$HEALTH" 2>/dev/null | grep -q '"ok"'; then
  ok "API ตอบ health = ok"
else
  warn "ยิง health ไม่สำเร็จ — ปกติถ้า Function App จำกัดเน็ตเวิร์ก (ต้องยิงจากในเน็ตเวิร์ก/VPN)"
fi

say ""
say "  ${c_cya}ตรวจ log ตอน Function App เริ่มทำงาน ควรเจอบรรทัดนี้:${c_off}"
say "    guard: ทุก endpoint ประกาศสิทธิ์ครบ (34 รายการ)"
say "  ดู log: az webapp log tail -g $RG -n $FUNC_NAME"
say ""
say "  ${c_cya}ถ้าเจอ 'SECURITY: endpoints missing from guard.ROUTE_PERMS' = มี endpoint ลืมประกาศสิทธิ์${c_off}"
say ""
printf "%s=== เสร็จสิ้น (%s) ===%s\n" "$c_grn" "$TARGET_ENV" "$c_off"
if [ "$TARGET_ENV" = "preview" ]; then
  say "URL ของ preview อยู่ในผลลัพธ์ของ swa deploy ด้านบน"
  say "ทดสอบ checklist #1-17 (สิทธิ์/audit) ให้ผ่านก่อน แล้วค่อยรัน: ./redeploy.sh --prod"
fi
