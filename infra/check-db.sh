#!/usr/bin/env bash
# =====================================================================
# ตรวจว่าตารางที่ Wave 1/3 ต้องใช้ถูกสร้างแล้วหรือยัง (AuditLog / CoachJobs)
# และรายงาน RolePermissions (R2) ในคำสั่งเดียว
#
# ต้องมี sqlcmd (go-sqlcmd):   brew install sqlcmd
# ใช้ Entra ID interactive auth (-G) — ไม่ต้องมี connection string / รหัสผ่าน
#
#   ./check-db.sh
#   -> เขียนผลที่ infra/.checkdb-output.txt
#
# ถ้าไม่อยากติดตั้ง sqlcmd: เปิดแอปแล้วดู Settings > Audit Trail
# (ขึ้นข้อความเหลือง = ตาราง AuditLog ยังไม่มี) และแท็บ Presentation Coach
# (สร้าง guideline ไม่ได้ = ตาราง CoachJobs ยังไม่มี)
# =====================================================================
set -uo pipefail

RG="${RESOURCE_GROUP:-rg-proposal-evaluator}"
DB="${SQL_DB:-proposal_evaluator}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/.checkdb-output.txt"

command -v az >/dev/null || { echo "ไม่พบ az"; exit 1; }
az account show >/dev/null 2>&1 || { echo "ยังไม่ได้ login — รัน 'az login'"; exit 1; }
command -v sqlcmd >/dev/null || {
  echo "ไม่พบ sqlcmd — ติดตั้งก่อน:  brew install sqlcmd"
  echo "หรือใช้วิธีไม่ต้องติดตั้ง: เปิดแอป -> Settings > Audit Trail / แท็บ Presentation Coach"
  exit 1
}

SRV="$(az sql server list -g "$RG" --query "[0].fullyQualifiedDomainName" -o tsv 2>/dev/null)"
[ -n "$SRV" ] || { echo "ไม่พบ SQL server ใน '$RG'"; exit 1; }
echo "SQL server: $SRV / db: $DB"
echo "จะเปิด browser ให้ยืนยันตัวตนด้วย Entra ID (บัญชีที่เป็น SQL admin)"

QUERY=$(cat <<'SQL'
SET NOCOUNT ON;
PRINT '--- ตารางที่ Wave 1/3 ต้องมี ---';
SELECT CASE WHEN EXISTS (SELECT 1 FROM sys.tables WHERE name='AuditLog')
            THEN 'AuditLog  : มีแล้ว' ELSE 'AuditLog  : ยังไม่มี -> รัน sql/migration_audit_log.sql' END;
SELECT CASE WHEN EXISTS (SELECT 1 FROM sys.tables WHERE name='CoachJobs')
            THEN 'CoachJobs : มีแล้ว' ELSE 'CoachJobs : ยังไม่มี -> รัน sql/migration_coach_jobs.sql' END;

PRINT '';
PRINT '--- R2: role ที่มีผู้ใช้จริงต้องเปิดสิทธิ์ evaluate ---';
SELECT r.name AS role_name,
       MAX(CASE WHEN rp.page_key='evaluate' THEN rp.can_access END) AS can_evaluate,
       MAX(CASE WHEN rp.page_key='proposals' THEN rp.can_access END) AS can_proposals,
       MAX(CASE WHEN rp.page_key='view_all' THEN rp.can_access END) AS can_view_all,
       (SELECT COUNT(*) FROM dbo.Users u WHERE u.role = r.name) AS users
FROM dbo.Roles r LEFT JOIN dbo.RolePermissions rp ON rp.role_id = r.role_id
GROUP BY r.name ORDER BY users DESC;

PRINT '';
PRINT '--- จำนวนแถวในตารางหลัก (ดูว่าข้อมูลเดิมยังอยู่ครบ) ---';
SELECT 'ProposalThreads' AS tbl, COUNT(*) AS rows_ FROM dbo.ProposalThreads
UNION ALL SELECT 'Submissions', COUNT(*) FROM dbo.Submissions
UNION ALL SELECT 'EvaluationResults', COUNT(*) FROM dbo.EvaluationResults
UNION ALL SELECT 'Users', COUNT(*) FROM dbo.Users;
SQL
)

{
  echo "# Check DB — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "# server: $SRV  db: $DB"
  echo
  sqlcmd -S "$SRV" -d "$DB" -G -Q "$QUERY" 2>&1
} > "$OUT"

echo
echo "เขียนผลไว้ที่:"
echo "  $OUT"
echo "บอกผู้ช่วยว่า 'อ่านผล checkdb' ได้เลย"
