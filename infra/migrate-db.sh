#!/usr/bin/env bash
# =====================================================================
# รัน migration ที่ค้างให้จบในคำสั่งเดียว — ไม่ต้องเขียน/เปิด SQL เอง
#
#   ./migrate-db.sh                 # สร้างตารางที่ขาด + ให้สิทธิ์แอปทำเองได้ครั้งหน้า
#   ./migrate-db.sh --no-grant-ddl  # สร้างตารางเท่านั้น ไม่แตะสิทธิ์
#   ./migrate-db.sh --check         # ตรวจอย่างเดียว ไม่แก้อะไร
#
# ทำไมต้องมีสคริปต์นี้: Managed Identity ของ Function App ได้แค่
# db_datareader + db_datawriter -> ปุ่มใน Settings สร้างตารางไม่ได้
# (CREATE TABLE permission denied 262) และ Portal Query editor ต้องพิมพ์ SQL เอง
#
# ใช้ token จาก 'az login' ที่มีอยู่แล้ว — ไม่ต้องกรอกรหัสผ่าน ไม่เก็บ secret
# ต้องเป็น Entra admin ของ SQL server (คนเดียวกับที่รัน schema.sql ตอนตั้งระบบ)
#
# 🔒 ไม่อ่าน App Settings / connection string / secret ใด ๆ
# =====================================================================
set -uo pipefail

RG="${RESOURCE_GROUP:-rg-proposal-evaluator}"
DB="${SQL_DB:-proposal_evaluator}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
MIG="$ROOT/sql/migration_all_pending.sql"
OUT="$HERE/.migrate-output.txt"
FW_RULE="pe-migrate-tmp"

GRANT_DDL=1
CHECK_ONLY=0
for a in "$@"; do
  case "$a" in
    --no-grant-ddl) GRANT_DDL=0 ;;
    --check)        CHECK_ONLY=1 ;;
    -h|--help)      sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "ไม่รู้จัก option: $a  (ดู --help)"; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf '\n✘ %s\n' "$*" >&2; exit 1; }

# ---------- 1) เครื่องมือที่ต้องมี ----------
command -v az >/dev/null || die "ไม่พบ az — ติดตั้ง Azure CLI ก่อน"
az account show >/dev/null 2>&1 || die "ยังไม่ได้ login — รัน 'az login'"

if ! command -v sqlcmd >/dev/null 2>&1; then
  say "▸ ไม่พบ sqlcmd — จะติดตั้งด้วย Homebrew (ครั้งเดียว ~30 วินาที)"
  command -v brew >/dev/null || die "ไม่พบทั้ง sqlcmd และ brew
ติดตั้งอันใดอันหนึ่ง:
  brew install sqlcmd
  หรือดาวน์โหลด go-sqlcmd จาก https://github.com/microsoft/go-sqlcmd/releases"
  brew install sqlcmd || die "ติดตั้ง sqlcmd ไม่สำเร็จ — ลองรัน 'brew install sqlcmd' ดูข้อความเต็ม"
fi
[ -f "$MIG" ] || die "ไม่พบไฟล์ migration: $MIG"

# ---------- 2) หา resource ----------
SRV_NAME="$(az sql server list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"
[ -n "$SRV_NAME" ] || die "ไม่พบ SQL server ใน resource group '$RG'"
SRV="$(az sql server show -g "$RG" -n "$SRV_NAME" --query fullyQualifiedDomainName -o tsv)"
FUNC="$(az functionapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"
ME="$(az account show --query user.name -o tsv)"

say "▸ SQL server : $SRV"
say "▸ database   : $DB"
say "▸ login เป็น : $ME"
say "▸ function   : ${FUNC:-<ไม่พบ>}"

# ตรวจว่าบัญชีที่ login เป็น Entra admin ของ server จริงไหม — ถ้าไม่ใช่จะ auth ไม่ผ่าน
ADMIN="$(az sql server ad-admin list -g "$RG" -s "$SRV_NAME" --query "[0].login" -o tsv 2>/dev/null)"
if [ -n "${ADMIN:-}" ]; then
  say "▸ Entra admin ของ server: $ADMIN"
  [ "$ADMIN" = "$ME" ] || say "  ⚠ ไม่ตรงกับบัญชีที่ login — ถ้าเป็นกลุ่ม (group) ที่มี $ME อยู่ ก็ผ่านได้"
else
  say "  ⚠ อ่าน Entra admin ไม่ได้ (อาจไม่มีสิทธิ์อ่าน) — ลองต่อไปเลย"
fi

# public network access ปิด = ต่อจากเครื่องนี้ไม่ได้เลย ไม่ว่าจะตั้ง firewall อย่างไร
PNA="$(az sql server show -g "$RG" -n "$SRV_NAME" --query publicNetworkAccess -o tsv 2>/dev/null)"
[ "${PNA:-Enabled}" = "Disabled" ] && die "SQL server ปิด public network access อยู่
ต่อจากเครื่องนี้ไม่ได้ — ต้องเปิดชั่วคราว (คำสั่งนี้เปลี่ยนค่าจริง อ่านก่อนรัน):
  az sql server update -g $RG -n $SRV_NAME --enable-public-network true
แล้วรัน ./migrate-db.sh อีกครั้ง จากนั้นปิดคืนด้วย --enable-public-network false"

# ---------- 3) เปิด firewall ให้ IP เครื่องนี้ชั่วคราว ----------
MYIP="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)"
FW_ADDED=0
cleanup() {
  if [ "$FW_ADDED" = "1" ]; then
    say "▸ ลบ firewall rule ชั่วคราว ($FW_RULE)"
    az sql server firewall-rule delete -g "$RG" -s "$SRV_NAME" -n "$FW_RULE" >/dev/null 2>&1
  fi
}
trap cleanup EXIT INT TERM

if [ -n "$MYIP" ]; then
  say "▸ เปิด firewall ให้ IP $MYIP ชั่วคราว (ลบอัตโนมัติเมื่อจบ)"
  az sql server firewall-rule create -g "$RG" -s "$SRV_NAME" -n "$FW_RULE" \
     --start-ip-address "$MYIP" --end-ip-address "$MYIP" >/dev/null 2>&1 \
     && FW_ADDED=1 || say "  ⚠ สร้าง firewall rule ไม่ได้ — ถ้ามี rule เดิมครอบ IP นี้อยู่แล้วก็ผ่านได้"
else
  say "  ⚠ หา public IP ของเครื่องไม่ได้ — ถ้าติดต่อ DB ไม่ได้ ให้เพิ่ม firewall rule เอง"
fi

# ---------- 4) ต่อ DB (ลอง 2 วิธี auth) ----------
# go-sqlcmd 1.10: -G กับ --authentication-method ใช้ร่วมกันไม่ได้ (mutually exclusive)
# จึงต้องส่งอย่างใดอย่างหนึ่ง — หาว่าวิธีไหนใช้ได้ "ครั้งเดียว" ก่อน แล้วใช้วิธีนั้นตลอด
# (ห้ามลองสลับวิธีตอนรัน migration จริง เพราะถ้า SQL error จะถูกรันซ้ำหลายรอบ)
#   -G เปล่า                   = ActiveDirectoryDefault -> ใช้ token จาก az login
#   ActiveDirectoryAzCli       = บังคับใช้ az login โดยตรง
#   ActiveDirectoryInteractive = เปิด browser ให้ยืนยันตัวตน (ทางสุดท้าย)
SQL_AUTH=""
PROBE_ERR=""
probe_auth() {
  local a
  for a in "-G" "--authentication-method=ActiveDirectoryAzCli" \
           "--authentication-method=ActiveDirectoryInteractive"; do
    # shellcheck disable=SC2086
    PROBE_ERR="$(sqlcmd -S "$SRV" -d "$DB" $a -l 30 -b -Q "SET NOCOUNT ON; SELECT 1" 2>&1)" \
      && { SQL_AUTH="$a"; return 0; }
    # ถ้าปัญหาคือเน็ตเวิร์ก/firewall ไม่ใช่ตัวตน -> ไม่ต้องลองต่อ
    # (Interactive จะเปิด browser ขึ้นมาเปล่า ๆ แล้วก็ล้มเหลวเหมือนกัน)
    case "$PROBE_ERR" in
      *"Cannot open server"*|*"Login timeout"*|*"no such host"*|*"connection refused"*)
        say "  (หยุดลองวิธีอื่น — อาการเป็นเรื่องเน็ตเวิร์ก/firewall ไม่ใช่การยืนยันตัวตน)"
        return 1 ;;
    esac
  done
  return 1
}
run_sql() {   # run_sql <-Q query | -i file>   ใช้ได้หลัง probe_auth สำเร็จแล้ว
  # shellcheck disable=SC2086
  sqlcmd -S "$SRV" -d "$DB" $SQL_AUTH -l 30 -b "$@" 2>&1
}

STATUS_Q="SET NOCOUNT ON;
SELECT CONCAT('AuditLog  : ', CASE WHEN OBJECT_ID('dbo.AuditLog','U')  IS NULL THEN 'ยังไม่มี' ELSE 'มีแล้ว' END);
SELECT CONCAT('CoachJobs : ', CASE WHEN OBJECT_ID('dbo.CoachJobs','U') IS NULL THEN 'ยังไม่มี' ELSE 'มีแล้ว' END);"

say "▸ ทดสอบการเชื่อมต่อ DB (หาวิธียืนยันตัวตนที่ใช้ได้)"
CONNECTED=0
probe_auth && CONNECTED=1

{
  say "# migrate-db — $(date '+%Y-%m-%d %H:%M:%S')"
  say "# server: $SRV  db: $DB  actor: $ME"
  say "# sqlcmd: $(sqlcmd --version 2>/dev/null | head -1)"
  say

  if [ "$CONNECTED" = "0" ]; then
    say "════════ ต่อ DB ไม่ได้ — ไม่ได้แก้อะไรเลย ════════"
    say "ลองแล้วทั้ง 3 วิธี (-G / AzCli / Interactive) ข้อความจากครั้งสุดท้าย:"
    say "$PROBE_ERR"
    say
    say "แปลอาการที่พบบ่อย:"
    say "  'Login failed for user <token-identified principal>' -> $ME ไม่ใช่ Entra admin ของ DB นี้"
    say "  'Cannot open server ... requested by the login'       -> firewall ยังไม่อนุญาต IP นี้"
    say "  'Login timeout expired'                              -> firewall / เน็ตเวิร์กปิดกั้น port 1433"
    say "  'not able to obtain a token'                         -> รัน 'az login' ใหม่"
  elif [ "$CHECK_ONLY" = "1" ]; then
    say "# วิธียืนยันตัวตนที่ใช้ได้: $SQL_AUTH"
    say
    say "════════ สถานะปัจจุบัน ════════"
    run_sql -Q "$STATUS_Q"
  else
    say "# วิธียืนยันตัวตนที่ใช้ได้: $SQL_AUTH"
    say
    say "════════ ก่อนรัน ════════"
    run_sql -Q "$STATUS_Q"
    say

    say "════════ สร้างตารางที่ขาด ════════"
    say "-- ไฟล์: sql/migration_all_pending.sql (idempotent — รันซ้ำได้)"
    if run_sql -i "$MIG"; then
      say ">>> ✅ รัน migration สำเร็จ"
    else
      say ">>> ❌ รัน migration ไม่สำเร็จ — อ่านข้อความข้างบน"
      say "    ถ้าเป็น 'CREATE TABLE permission denied' = บัญชี $ME ไม่ใช่ Entra admin ของ DB นี้"
      say "    ถ้าเป็น 'Login failed' / timeout = auth หรือ firewall"
    fi
    say

    if [ "$GRANT_DDL" = "1" ] && [ -n "${FUNC:-}" ]; then
      say "════════ ให้สิทธิ์แอปสร้างตารางเองได้ครั้งหน้า ════════"
      say "-- เพิ่ม '$FUNC' เข้า role db_ddladmin"
      say "-- ผลคือปุ่ม Settings > Database schema > 'สร้างตารางที่ขาด' จะใช้งานได้"
      say "-- ไม่ต้องการ: รันด้วย ./migrate-db.sh --no-grant-ddl"
      run_sql -Q "
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$FUNC')
    CREATE USER [$FUNC] FROM EXTERNAL PROVIDER;
IF IS_ROLEMEMBER('db_ddladmin', '$FUNC') = 0
    ALTER ROLE db_ddladmin ADD MEMBER [$FUNC];
SELECT CONCAT('db_ddladmin: ', CASE WHEN IS_ROLEMEMBER('db_ddladmin','$FUNC') = 1
       THEN 'ให้สิทธิ์แล้ว' ELSE 'ยังไม่ได้' END);" \
        && say ">>> ✅ เสร็จ" || say ">>> ⚠ ให้สิทธิ์ไม่สำเร็จ (ตารางอาจสร้างสำเร็จแล้ว — ดูผลด้านล่าง)"
      say
    fi

    say "════════ หลังรัน (ต้องเป็น 'มีแล้ว' ทั้งสองตัว) ════════"
    run_sql -Q "$STATUS_Q" || say "!! ตรวจซ้ำไม่ได้"
  fi
} > "$OUT" 2>&1

# ---------- 5) สรุปให้เห็นบนจอ ----------
say
say "──────── ผลลัพธ์ ────────"
grep -E "AuditLog|CoachJobs|db_ddladmin|>>>|Login|Cannot open|timeout|token" "$OUT" | tail -20
say
say "รายละเอียดเต็ม: $OUT"

# ตัดสินจาก "สองบรรทัดสถานะท้ายสุด" เท่านั้น — ไม่ใช่เดาจากทั้งไฟล์
TAIL="$(tail -14 "$OUT")"
if [ "$CONNECTED" = "0" ]; then
  say "✘ ต่อ DB ไม่ได้ — ยังไม่ได้แก้อะไรทั้งสิ้น"
  say "  บอกผู้ช่วยว่า 'อ่านผล migrate' เพื่อให้อ่านสาเหตุให้"
  exit 1
elif grep -q "AuditLog  : มีแล้ว" <<<"$TAIL" && grep -q "CoachJobs : มีแล้ว" <<<"$TAIL"; then
  say "✅ ตารางครบทั้งสองตัวแล้ว"
  say "ขั้นต่อไป: เปิดแอป → Settings → Database schema → 'ตรวจใหม่' ต้องขึ้น \"ครบ\""
else
  say "⚠ ยังไม่ครบ — บอกผู้ช่วยว่า 'อ่านผล migrate' เพื่อให้อ่านสาเหตุให้"
  exit 1
fi
