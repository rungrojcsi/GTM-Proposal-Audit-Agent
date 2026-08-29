#!/usr/bin/env bash
# =====================================================================
# วัดประสิทธิภาพเชิงเครื่องของ LLM server — ความเร็วต่อโมเดล + concurrency
#
#   ./bench-llm.sh                          # ทุกโมเดลแชท + concurrency 1/2/4/8
#   ./bench-llm.sh --only gemma4            # เฉพาะโมเดลที่ชื่อมีคำนี้
#   ./bench-llm.sh --skip-conc              # วัดความเร็วอย่างเดียว
#   ./bench-llm.sh --skip-speed --conc-model gpt-oss:latest
#   ./bench-llm.sh --conc-levels 1,2,4      # เปลี่ยนระดับการยิงพร้อมกัน
#   -> รายงาน infra/.bench-output.txt · ข้อมูลดิบ infra/.bench-runs.jsonl
#
# ใช้ Python มาตรฐาน (urllib) ไม่ต้องมี venv หรือ dependency ใด ๆ
# อ่านค่า endpoint/คีย์จาก App Settings ของ Function App (หรือ infra/.abtest.env ถ้ามี)
#
# 🔒 ไม่พิมพ์ค่า secret ออกจอหรือลงไฟล์ผลลัพธ์
# ⚠️ ไม่มีค่าใช้จ่ายฝั่ง Azure OpenAI — ทดสอบเฉพาะเซิร์ฟเวอร์ local
#    แต่จะยึด GPU ของเซิร์ฟเวอร์ระหว่างทดสอบ (โหลด/ปล่อยโมเดลทีละตัว)
# =====================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENVFILE="$HERE/.abtest.env"
RG="${RESOURCE_GROUP:-rg-proposal-evaluator}"

die() { printf '\n✘ %s\n' "$*" >&2; exit 1; }

MODE=local
for a in "$@"; do [ "$a" = "--azure" ] && MODE=azure; done

if [ -f "$ENVFILE" ]; then
  echo "▸ ใช้ค่าจาก infra/.abtest.env"
  set -a; . "$ENVFILE"; set +a
else
  echo "▸ ดึง endpoint/คีย์จาก App Settings ของ Function App"
  command -v az >/dev/null || die "ไม่พบ az และไม่มี .abtest.env"
  az account show >/dev/null 2>&1 || die "ยังไม่ได้ login — รัน 'az login'"
  FUNC="$(az functionapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"
  [ -n "$FUNC" ] || die "ไม่พบ Function App ใน '$RG'"
  PYSNIP="${TMPDIR:-/tmp}/pe-bench-env.py"
  cat > "$PYSNIP" <<'PYEOF'
import json, shlex, sys
want = {"LOCAL_LLM_BASE_URL", "LOCAL_LLM_API_KEY",
        "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY",
        "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_VERSION"}
for s in json.load(sys.stdin):
    name, value = s.get("name"), s.get("value")
    if name in want and value:
        print("export %s=%s" % (name, shlex.quote(value)))
PYEOF
  eval "$(az functionapp config appsettings list -g "$RG" -n "$FUNC" -o json 2>/dev/null \
          | python3 "$PYSNIP")" || die "ดึง App Settings ไม่สำเร็จ"
  rm -f "$PYSNIP"
fi

if [ "$MODE" = azure ]; then
  for k in AZURE_OPENAI_ENDPOINT AZURE_OPENAI_KEY AZURE_OPENAI_DEPLOYMENT AZURE_OPENAI_API_VERSION; do
    [ -n "${!k:-}" ] || die "ไม่พบ $k"
  done
  echo "  endpoint Azure: พร้อม (ไม่แสดงค่า)"
  echo
  # ตัด --azure ออกก่อนส่งต่อ (bench_azure.py ไม่รู้จัก flag นี้)
  ARGS=(); for a in "$@"; do [ "$a" = "--azure" ] || ARGS+=("$a"); done
  exec python3 "$HERE/bench_azure.py" "${ARGS[@]+"${ARGS[@]}"}"
fi

[ -n "${LOCAL_LLM_BASE_URL:-}" ] || die "ไม่พบ LOCAL_LLM_BASE_URL"
echo "  endpoint: พร้อม (ไม่แสดงค่า)"
echo

exec python3 "$HERE/bench_llm.py" "$@"
