#!/usr/bin/env bash
# =====================================================================
# เทียบผลประเมิน proposal ข้ามหลาย LLM ด้วยไฟล์ชุดเดียวกัน
#
#   ./ab-test-llm.sh                            # ทุกไฟล์ · azure + gemma4:26b + gpt-oss · 3 รอบ
#   ./ab-test-llm.sh --extract-only             # สกัดข้อความอย่างเดียว (ตรวจก่อนเสียเวลา LLM)
#   ./ab-test-llm.sh --repeat 1                 # รอบเดียวต่อไฟล์ต่อ engine
#   ./ab-test-llm.sh --engines azure            # เฉพาะ Azure
#   ./ab-test-llm.sh --engines local:gemma4:26b # เฉพาะ local รุ่นนี้
#   ./ab-test-llm.sh --only Acme               # เฉพาะไฟล์ที่ชื่อมีคำนี้
#   ./ab-test-llm.sh --report-only              # ทำรายงานใหม่จากข้อมูลดิบเดิม ไม่เรียก LLM
#   ./ab-test-llm.sh --fresh                    # ลบผลเดิมแล้วเริ่มใหม่
#   -> รายงาน infra/.abtest-output.txt · ข้อมูลดิบ infra/.abtest-runs.jsonl
#
# รันขาดกลางทางไม่เสียของ: บันทึกทีละรายการลง jsonl แล้วรันซ้ำจะข้ามรายการที่ทำแล้ว
#
# ที่มาของ config (เลือกอันแรกที่มี):
#   1) infra/.abtest.env   <- ไฟล์ที่สร้างเอง (gitignored) เหมาะเมื่อไม่อยากให้อ่าน App Settings
#   2) App Settings ของ Function App ผ่าน az (ต้องมีสิทธิ์อ่าน)
#
# ค่าที่ต้องมี:
#   LOCAL_LLM_BASE_URL, LOCAL_LLM_API_KEY                     (สำหรับ provider=local)
#   AZURE_OPENAI_ENDPOINT/KEY/DEPLOYMENT/API_VERSION          (สำหรับ provider=azure)
#   DOCINTEL_ENDPOINT, DOCINTEL_KEY                           (เฉพาะไฟล์ .pdf; .pptx ไม่ต้อง)
#
# 🔒 สคริปต์นี้ไม่พิมพ์ค่า secret ออกจอหรือลงไฟล์ผลลัพธ์เลย
# ⚠️ มีค่าใช้จ่ายจริง: Azure OpenAI ต่อโทเคน + Document Intelligence ต่อหน้า
#    (DIAT_Proposal เป็น PDF 94 หน้า) — ใช้ --only เพื่อทดลองไฟล์เล็กก่อน
# =====================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ENVFILE="$HERE/.abtest.env"
VENV="${TMPDIR:-/tmp}/pe-abtest-venv"
RG="${RESOURCE_GROUP:-rg-proposal-evaluator}"

# ดูจาก --engines ว่าต้องใช้ค่าของฝั่งไหน (ไม่ระบุ = ใช้ทั้งสองฝั่งตามค่า default)
ENGINES_SPEC=""
prev=""
for a in "$@"; do
  [ "$prev" = "--engines" ] && ENGINES_SPEC="$a"
  case "$a" in --engines=*) ENGINES_SPEC="${a#--engines=}" ;; esac
  prev="$a"
done
NEED_AZURE=1; NEED_LOCAL=1
if [ -n "$ENGINES_SPEC" ]; then
  case "$ENGINES_SPEC" in *azure*) NEED_AZURE=1 ;; *) NEED_AZURE=0 ;; esac
  # อะไรที่ไม่ใช่ azure ถือว่าเป็น local
  case "$(printf '%s' "$ENGINES_SPEC" | tr ',' '\n' | grep -v '^azure$' | head -1)" in
    "") NEED_LOCAL=0 ;;
    *)  NEED_LOCAL=1 ;;
  esac
fi

die() { printf '\n✘ %s\n' "$*" >&2; exit 1; }

# ---------- 1) config ----------
if [ -f "$ENVFILE" ]; then
  echo "▸ ใช้ค่าจาก infra/.abtest.env"
  set -a; . "$ENVFILE"; set +a
else
  echo "▸ ไม่พบ infra/.abtest.env — ดึงจาก App Settings ของ Function App"
  command -v az >/dev/null || die "ไม่พบ az และไม่มี .abtest.env"
  az account show >/dev/null 2>&1 || die "ยังไม่ได้ login — รัน 'az login'"
  FUNC="$(az functionapp list -g "$RG" --query "[0].name" -o tsv 2>/dev/null)"
  [ -n "$FUNC" ] || die "ไม่พบ Function App ใน '$RG'"
  # ดึงทีเดียวเป็น JSON แล้วแปลงเป็น export — ไม่พิมพ์ค่าออกจอ
  # เขียน snippet ลงไฟล์ชั่วคราวแทน -c เพื่อไม่ต้องซ้อน quote (เคยพลาดมาแล้ว)
  PYSNIP="${TMPDIR:-/tmp}/pe-abtest-env.py"
  cat > "$PYSNIP" <<'PYEOF'
import json, shlex, sys
want = {"LOCAL_LLM_BASE_URL", "LOCAL_LLM_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY",
        "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_VERSION", "DOCINTEL_ENDPOINT", "DOCINTEL_KEY"}
for s in json.load(sys.stdin):
    name = s.get("name")
    value = s.get("value")
    if name in want and value:
        print("export %s=%s" % (name, shlex.quote(value)))
PYEOF
  eval "$(az functionapp config appsettings list -g "$RG" -n "$FUNC" -o json 2>/dev/null \
          | python3 "$PYSNIP")" || die "ดึง App Settings ไม่สำเร็จ"
  rm -f "$PYSNIP"
fi

# ตรวจว่าครบ — รายงานเฉพาะ "ชื่อ" ที่ขาด ไม่แสดงค่า
missing=""
[ "$NEED_LOCAL" = 1 ] && for k in LOCAL_LLM_BASE_URL LOCAL_LLM_API_KEY; do
  [ -n "${!k:-}" ] || missing="$missing $k"
done
[ "$NEED_AZURE" = 1 ] && for k in AZURE_OPENAI_ENDPOINT AZURE_OPENAI_KEY AZURE_OPENAI_DEPLOYMENT AZURE_OPENAI_API_VERSION; do
  [ -n "${!k:-}" ] || missing="$missing $k"
done
[ -n "$missing" ] && die "ขาดค่า:$missing
สร้าง infra/.abtest.env แล้วใส่ค่าเหล่านี้ (รูปแบบ KEY=value บรรทัดละตัว)"

if [ -z "${DOCINTEL_ENDPOINT:-}" ] || [ -z "${DOCINTEL_KEY:-}" ]; then
  echo "  ⚠ ไม่มี DOCINTEL_* — ไฟล์ .pdf จะสกัดข้อความไม่ได้ (.pptx ยังทดสอบได้)"
fi
echo "  ค่าที่ต้องใช้: ครบ"

# ---------- 2) venv ----------
PKGS=("openai>=1.40.0" "pydantic>=2.0" "python-pptx" "azure-ai-formrecognizer")
if [ ! -x "$VENV/bin/python" ]; then
  echo "▸ สร้าง venv + ติดตั้ง dependency (ครั้งเดียว)"
  python3 -m venv "$VENV" || die "สร้าง venv ไม่สำเร็จ"
  PIP_ARGS=(-q --disable-pip-version-check --timeout 60 --retries 3
            --cache-dir "${TMPDIR:-/tmp}/pe-pipcache")
  # ไม่ลง pyodbc: ต้องมี unixODBC และ harness นี้ไม่แตะ DB เลย
  if ! "$VENV/bin/pip" install "${PIP_ARGS[@]}" "${PKGS[@]}" 2>&1 | tail -3; then
    # บางสภาพแวดล้อม (แซนด์บ็อกซ์/พร็อกซีองค์กร) แทรกกลาง TLS -> pip ไม่เชื่อใบรับรอง
    # (SSLCertVerificationError OSStatus -26276) แต่ curl ผ่านเพราะใช้ keychain ของระบบ
    echo "  ⚠ pip ตรวจใบรับรองไม่ผ่าน — ลองใหม่แบบเชื่อ pypi โดยตรง"
    "$VENV/bin/pip" install "${PIP_ARGS[@]}" \
        --trusted-host pypi.org --trusted-host files.pythonhosted.org \
        --trusted-host pypi.python.org "${PKGS[@]}" \
      || die "ติดตั้ง dependency ไม่สำเร็จ — ลองรันคำสั่งนี้ดูข้อความเต็ม:
  $VENV/bin/pip install ${PKGS[*]}"
  fi
fi
"$VENV/bin/python" -c "import openai, pptx, azure.ai.formrecognizer, pydantic" 2>/dev/null \
  || die "dependency ยังไม่ครบใน $VENV — ลบโฟลเดอร์นั้นแล้วรันใหม่"
echo "▸ python: $("$VENV/bin/python" -V)"

# ---------- 3) รัน ----------
echo "▸ เริ่มทดสอบ (local LLM ~20-30s ต่อการเรียก — ใจเย็น)"
echo
ABTEST_CACHE="$HERE/.abtest-cache" "$VENV/bin/python" "$HERE/ab_test_llm.py" "$@"
