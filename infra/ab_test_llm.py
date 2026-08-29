"""เทียบผลประเมิน proposal ข้ามหลาย LLM (Azure / local หลายรุ่น) ด้วยไฟล์ชุดเดียวกัน.

เรียกผ่าน infra/ab-test-llm.sh (ตัวนั้นเตรียม venv + env ให้) ไม่ควรรันไฟล์นี้ตรง ๆ

ออกแบบให้ "เทียบได้จริง" — ตัวแปรเดียวที่ต่างกันคือ engine:
  - สกัดข้อความ **ครั้งเดียวต่อไฟล์** แล้ว cache ไว้ใช้ทุก engine ทุกรอบ
    (ถ้าสกัดใหม่ OCR ของ Document Intelligence อาจให้ผลไม่เหมือนเดิม -> เทียบไม่ได้)
  - ใช้ evaluate_proposal / scoring ของแอปจริง ไม่ได้เขียน prompt หรือสูตรคะแนนใหม่
  - lang เดียวกัน, context=None เหมือนกัน
  - สลับ engine ด้วยการแทน llm.client_and_model (ไม่แตะ DB / ไม่แตะ settings production)

บันทึกผล **ทีละรายการ** ลง .abtest-runs.jsonl -> รันขาดกลางทางไม่เสียของ และรันซ้ำจะ
ข้ามรายการที่ทำแล้ว (resume) ทำรายงานใหม่จาก jsonl เดิมได้ด้วย --report-only

ไม่เขียนอะไรลง production: ไม่มี DB insert, ไม่มี blob upload, ไม่มีคิว
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "api"))

from shared import evaluation, llm, scoring  # noqa: E402
from shared.extraction import extract_text   # noqa: E402
from shared.rubric import SECTION_ORDER      # noqa: E402

CACHE = pathlib.Path(os.environ.get("ABTEST_CACHE", HERE / ".abtest-cache"))
RUNS = HERE / ".abtest-runs.jsonl"
REPORT = HERE / ".abtest-output.txt"
CONTENT_TYPES = {
    ".pdf":  "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


# ---------------------------------------------------------------- engines
def parse_engines(spec: str) -> list[dict]:
    """'azure,local:gemma4:26b' -> [{name,provider,model}, ...]

    ชื่อ model ของ local มี ':' อยู่ในตัว (gemma4:26b) จึงตัดแค่ prefix แรก
    """
    out = []
    for raw in (s.strip() for s in spec.split(",") if s.strip()):
        if raw.startswith("local:"):
            model = raw[len("local:"):]
            out.append({"name": model, "provider": "local", "model": model})
        elif raw in ("azure", "local"):
            out.append({"name": raw, "provider": raw, "model": ""})
        else:  # ไม่มี prefix -> ถือว่าเป็น local model
            out.append({"name": raw, "provider": "local", "model": raw})
    return out


def make_client(provider: str, model: str):
    if provider == "local":
        from openai import OpenAI
        base = os.environ["LOCAL_LLM_BASE_URL"]
        key = os.environ.get("LOCAL_LLM_API_KEY") or "not-needed"
        return OpenAI(base_url=base, api_key=key, timeout=1800), model
    from openai import AzureOpenAI
    return (
        AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version=os.environ["AZURE_OPENAI_API_VERSION"],
            timeout=1800,
        ),
        os.environ["AZURE_OPENAI_DEPLOYMENT"],
    )


# ---------------------------------------------------------------- extraction
def get_text(path: pathlib.Path) -> tuple[str, str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    st = path.stat()
    key = hashlib.sha1(f"{path.name}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]
    cached = CACHE / f"{key}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8"), "cache"
    text = extract_text(path.read_bytes(),
                        CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                        path.name)
    cached.write_text(text, encoding="utf-8")
    return text, "สกัดใหม่"


def extract_hint(err: str, size_mb: float) -> str:
    # PDF ต้องอัปโหลดเข้า Document Intelligence — พร็อกซี/แซนด์บ็อกซ์บางตัวตัดการอัปโหลดใหญ่
    if "proxy" in err.lower() or "Connection reset" in err or "RemoteDisconnected" in err:
        return (f"พร็อกซีตัดการอัปโหลด (ไฟล์ {size_mb:.0f}MB) ไม่ใช่ปัญหาของ "
                "Document Intelligence — ลองรันจากเครื่องที่ไม่มีพร็อกซีคั่น")
    return ""


# ---------------------------------------------------------------- ดัก raw output
# _normalize_to_rubric บังคับ score_details ให้ครบ 17 canonical section — section ที่ LLM
# ตั้งชื่อไม่ตรงจะถูกทิ้งและเติม 0 ทำให้ "ตอบผิด format" หน้าตาเหมือน "proposal แย่"
# ดักไว้ก่อน normalize เพื่อแยกสองกรณีนี้ออกจากกัน
_RAW: list[tuple[str, int]] = []
_orig_normalize = evaluation._normalize_to_rubric


def _capture_then_normalize(llm_out):
    _RAW.clear()
    _RAW.extend((d.slide_section, d.score_1_10) for d in llm_out.score_details)
    return _orig_normalize(llm_out)


evaluation._normalize_to_rubric = _capture_then_normalize


# ---------------------------------------------------------------- one run
def run_one(text: str, eng: dict, lang: str) -> dict:
    client, model = make_client(eng["provider"], eng["model"])
    llm.client_and_model = lambda: (client, model)
    _RAW.clear()
    t0 = time.monotonic()
    try:
        out = evaluation.evaluate_proposal(text, context=None, lang=lang)
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "elapsed": round(time.monotonic() - t0, 1),
                "error": type(err).__name__ + ": " + str(err)[:300]}
    elapsed = round(time.monotonic() - t0, 1)
    overall = scoring.compute_overall_score(out.score_details)
    scores = {d.slide_section: d.score_1_10 for d in out.score_details}
    raw = list(_RAW)
    bad = [n for n, _ in raw if n not in SECTION_ORDER]
    return {
        "ok": True, "elapsed": elapsed, "overall": overall,
        "verdict": scoring.map_verdict(overall), "scores": scores,
        "raw_count": len(raw), "bad_names": bad,
        "answered": sum(1 for v in scores.values() if v > 0),
        "strengths": len(out.strengths or []), "gaps": len(out.gaps or []),
        "recommendations": len(out.recommendations or []),
        "skeleton_chars": len(out.skeleton_md or ""),
    }


# ---------------------------------------------------------------- jsonl store
def load_runs() -> list[dict]:
    """อ่านผลดิบ + ทำความสะอาด — จำเป็นเพราะไฟล์นี้อาจถูกเขียนโดยหลายกระบวนการ.

    1) ข้ามบรรทัดที่พัง (ถูกฆ่ากลางเขียน)
    2) ทิ้งผลที่ล้มจากบั๊กเก่า `---` นำหน้า JSON (แก้แล้วด้วย llm.json_text) — เป็นสิ่งประดิษฐ์
       ของโค้ดเวอร์ชันก่อน ไม่ใช่ข้อจำกัดของโมเดล ถ้านับรวมจะทำให้อัตราสำเร็จผิด
    3) กันซ้ำต่อ (file, engine, run): เลือกรายการที่สำเร็จก่อน ไม่มีก็เอาอันล่าสุด
    """
    if not RUNS.exists():
        return []
    recs = []
    for line in RUNS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not r.get("ok") and "input_value=\'---" in r.get("error", ""):
            continue
        recs.append(r)
    best: dict[tuple, dict] = {}
    for r in recs:
        k = (r.get("file"), r.get("engine"), r.get("run"))
        cur = best.get(k)
        if cur is None or (r.get("ok") and not cur.get("ok")) or bool(cur.get("ok")) == bool(r.get("ok")):
            best[k] = r
    return list(best.values())


def append_run(rec: dict) -> None:
    with RUNS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()


# ---------------------------------------------------------------- report
def agg(vals: list[float]) -> str:
    if not vals:
        return "—"
    if len(vals) == 1:
        return f"{vals[0]:.1f}"
    return f"{statistics.mean(vals):.1f} (ต่ำสุด {min(vals):.0f} สูงสุด {max(vals):.0f})"


def sd(vals: list[float]) -> float:
    return statistics.stdev(vals) if len(vals) > 1 else 0.0


def build_report(recs: list[dict], engines: list[dict], files: list[str],
                 texts: dict[str, dict], lang: str, repeat: int) -> str:
    names = [e["name"] for e in engines]
    L: list[str] = []
    add = L.append

    def by(fname: str, ename: str) -> list[dict]:
        return [r for r in recs if r["file"] == fname and r["engine"] == ename]

    def ok_of(fname: str, ename: str) -> list[dict]:
        return [r for r in by(fname, ename) if r.get("ok")]

    add("# รายงานเทียบ LLM สำหรับประเมิน proposal")
    add("")
    add(f"engine ที่ทดสอบ: {' · '.join(names)}")
    add(f"ไฟล์: {len(files)} · รอบต่อไฟล์ต่อ engine: {repeat} · lang: {lang}")
    add(f"จำนวนการประเมินที่บันทึกไว้: {len(recs)} รายการ")
    add("")
    add("**ตัวแปรที่คุมให้เหมือนกัน:** ข้อความที่สกัด (cache ครั้งเดียวต่อไฟล์ ใช้ร่วมทุก engine), "
        "prompt, สูตรคะแนน (`scoring.py`), lang, `context=None`")
    add("ต่างกันแค่ engine — เรียก `evaluate_proposal` / `scoring` ของแอปจริง")
    add("")

    # ---- 1) อัตราสำเร็จ ----
    add("## 1) อัตราสำเร็จของงาน")
    add("")
    add("| engine | สำเร็จ | ล้มเหลว | อัตราสำเร็จ |")
    add("|---|---|---|---|")
    for e in names:
        rs = [r for r in recs if r["engine"] == e]
        good = sum(1 for r in rs if r.get("ok"))
        bad = len(rs) - good
        rate = f"{good / len(rs) * 100:.0f}%" if rs else "—"
        add(f"| {e} | {good} | {bad} | **{rate}** |")
    add("")
    fails = [r for r in recs if not r.get("ok")]
    if fails:
        add("รายการที่ล้มเหลว:")
        add("")
        add("| ไฟล์ | engine | รอบ | error |")
        add("|---|---|---|---|")
        for r in fails:
            add(f"| {r['file'][:34]} | {r['engine']} | {r['run']} | {r.get('error','')[:110]} |")
        add("")

    # ---- 2) latency ----
    add("## 2) Latency")
    add("")
    add("| engine | เฉลี่ย | มัธยฐาน | เร็วสุด | ช้าสุด | เทียบ Azure |")
    add("|---|---|---|---|---|---|")
    base = None
    for e in names:
        el = [r["elapsed"] for r in recs if r["engine"] == e and r.get("ok")]
        if not el:
            add(f"| {e} | — | — | — | — | — |")
            continue
        m = statistics.mean(el)
        if base is None:
            base = m
        add(f"| {e} | **{m:.0f}s** | {statistics.median(el):.0f}s | {min(el):.0f}s | "
            f"{max(el):.0f}s | {m / base:.1f}× |")
    add("")
    add("หมายเหตุ: latency ของ local ขึ้นกับโหลดของเซิร์ฟเวอร์ขณะทดสอบ — วัดแบบรันเรียงต่อกัน ไม่ขนาน")
    add("")

    # ---- 3) ความคงที่ของคะแนน ----
    add("## 3) ความคงที่ของคะแนน (รันไฟล์เดิม ข้อความเดิม ซ้ำหลายรอบ)")
    add("")
    add("| engine | ส่วนเบี่ยงเบนเฉลี่ย | แกว่งมากสุดในไฟล์เดียว | verdict คงที่ทุกรอบ |")
    add("|---|---|---|---|")
    for e in names:
        sds, spans, stable = [], [], 0
        counted = 0
        for f in files:
            os_ = [r["overall"] for r in ok_of(f, e)]
            if len(os_) < 2:
                continue
            counted += 1
            sds.append(sd(os_))
            spans.append(max(os_) - min(os_))
            vs = {r["verdict"] for r in ok_of(f, e)}
            stable += 1 if len(vs) == 1 else 0
        if not sds:
            add(f"| {e} | — | — | — |")
            continue
        add(f"| {e} | **±{statistics.mean(sds):.2f}** | {max(spans):.2f} จุด | {stable}/{counted} ไฟล์ |")
    add("")
    add("ยิ่งตัวเลขน้อยยิ่งดี — ค่าสูงหมายถึงคะแนนเชื่อถือได้เฉพาะเมื่อต่างกันมากกว่าค่านั้น")
    add("")

    # ---- 4) คุณภาพผลประเมิน ----
    add("## 4) คุณภาพของผลประเมิน")
    add("")
    add("| engine | section ที่ให้คะแนน >0 | ส่ง section ครบ 17 | ชื่อ section ผิด | recommendations | skeleton (ตัวอักษร) |")
    add("|---|---|---|---|---|---|")
    for e in names:
        rs = [r for r in recs if r["engine"] == e and r.get("ok")]
        if not rs:
            add(f"| {e} | — | — | — | — | — |")
            continue
        full = sum(1 for r in rs if r.get("raw_count") == 17)
        badn = sum(1 for r in rs if r.get("bad_names"))
        add(f"| {e} | **{statistics.mean([r['answered'] for r in rs]):.1f}/17** | "
            f"{full}/{len(rs)} รอบ | {badn} รอบ | "
            f"{statistics.mean([r['recommendations'] for r in rs]):.1f} | "
            f"{statistics.mean([r['skeleton_chars'] for r in rs]):,.0f} |")
    add("")
    add("`section ที่ให้คะแนน >0` — ยิ่งต่ำยิ่งแปลว่าโมเดลมองไม่เห็น/ตัดสินว่าไม่มีเนื้อหาในหัวข้อนั้น")
    add("`ชื่อ section ผิด` — โมเดลตั้งชื่อไม่ตรง canonical แล้วคะแนนถูกทิ้งเงียบ ๆ (ยิ่งมากยิ่งแย่)")
    add("")

    # ---- 5) คะแนนต่อไฟล์ ----
    add("## 5) คะแนนต่อไฟล์ (ค่าเฉลี่ยจากทุกรอบ)")
    add("")
    add("| ไฟล์ | ตัวอักษร | " + " | ".join(names) + " |")
    add("|---|---|" + "---|" * len(names))
    for f in files:
        cells = []
        for e in names:
            os_ = [r["overall"] for r in ok_of(f, e)]
            if not os_:
                cells.append("ล้มเหลว")
                continue
            v = {r["verdict"] for r in ok_of(f, e)}
            tag = next(iter(v)) if len(v) == 1 else "/".join(sorted(v))
            cells.append(f"**{statistics.mean(os_):.2f}** ±{sd(os_):.2f} · {tag}")
        ch = texts.get(f, {}).get("chars")
        ch_s = f"{ch:,}" if ch else "—"
        add(f"| {f[:38]} | {ch_s} | " + " | ".join(cells) + " |")
    add("")
    add("รูปแบบช่อง: `คะแนนเฉลี่ย ±ส่วนเบี่ยงเบน · verdict` — ถ้า verdict มีหลายค่าแสดงว่าไม่คงที่ระหว่างรอบ")
    add("")

    # ---- 6) เทียบกับ Azure ----
    if "azure" in names and len(names) > 1:
        add("## 6) ต่างจาก Azure แค่ไหน (Azure = เกณฑ์อ้างอิง)")
        add("")
        add("| engine | ต่างเฉลี่ย | ต่างมากสุด | ทิศทาง | verdict ตรงกับ Azure |")
        add("|---|---|---|---|---|")
        for e in names:
            if e == "azure":
                continue
            deltas, match, counted = [], 0, 0
            for f in files:
                a = [r["overall"] for r in ok_of(f, "azure")]
                b = [r["overall"] for r in ok_of(f, e)]
                if not a or not b:
                    continue
                counted += 1
                deltas.append(statistics.mean(b) - statistics.mean(a))
                va = statistics.mean(a)
                vb = statistics.mean(b)
                match += 1 if scoring.map_verdict(va) == scoring.map_verdict(vb) else 0
            if not deltas:
                add(f"| {e} | — | — | — | — |")
                continue
            mean_d = statistics.mean(deltas)
            direction = ("ต่ำกว่าทุกไฟล์" if all(d < 0 for d in deltas)
                         else "สูงกว่าทุกไฟล์" if all(d > 0 for d in deltas) else "ไม่คงทิศทาง")
            add(f"| {e} | **{mean_d:+.2f}** จุด | {max(deltas, key=abs):+.2f} จุด | "
                f"{direction} | {match}/{counted} ไฟล์ |")
        add("")
        add("`ทิศทาง` สำคัญกว่าขนาด — ถ้าต่ำกว่าทุกไฟล์อย่างคงเส้นคงวา ยังเทียบ proposal "
            "กันเองภายใน engine เดียวได้ แต่ห้ามเทียบคะแนนข้าม engine")
        add("")

    # ---- 7) รายละเอียดทุกรอบ ----
    add("## 7) รายละเอียดทุกรอบ")
    add("")
    add("| ไฟล์ | engine | รอบ | overall | verdict | section>0 | recs | skeleton | เวลา |")
    add("|---|---|---|---|---|---|---|---|---|")
    for f in files:
        for e in names:
            for r in by(f, e):
                if not r.get("ok"):
                    add(f"| {f[:26]} | {e} | {r['run']} | ล้มเหลว | — | — | — | — | {r['elapsed']}s |")
                    continue
                add(f"| {f[:26]} | {e} | {r['run']} | {r['overall']:.2f} | {r['verdict']} | "
                    f"{r['answered']}/17 | {r['recommendations']} | {r['skeleton_chars']:,} | "
                    f"{r['elapsed']}s |")
    add("")

    # ---- 8) การสกัดข้อความ ----
    add("## 8) การสกัดข้อความ (ตัวแปรที่กระทบคะแนนมากกว่าการเลือก engine)")
    add("")
    add("| ไฟล์ | ขนาดไฟล์ | ตัวอักษรที่สกัดได้ | สถานะ |")
    add("|---|---|---|---|")
    for f in sorted(texts, key=lambda k: -(texts[k].get("chars") or 0)):
        t = texts[f]
        ch = t.get("chars")
        ch_s = f"{ch:,}" if ch is not None else "สกัดไม่ได้"
        add(f"| {f[:38]} | {t.get('mb', 0):.1f}MB | {ch_s} | {t.get('note', '')} |")
    add("")
    got = [t["chars"] for t in texts.values() if t.get("chars")]
    if len(got) > 1:
        add(f"ช่วงตัวอักษรที่สกัดได้: {min(got):,} ถึง {max(got):,} "
            f"(ต่างกัน {max(got) / min(got):.0f} เท่า)")
        add("ปริมาณข้อความที่อ่านออกมีผลต่อคะแนนมากกว่าการเลือก engine — "
            "PDF ที่เนื้อหาอยู่ในรูปภาพจะได้คะแนนต่ำเสมอไม่ว่าใช้ engine ไหน")
        add("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- main
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default=str(ROOT / "Test_Proposal"))
    p.add_argument("--engines", default="azure,local:gemma4:26b,local:gpt-oss:latest")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--lang", default="en", choices=["en", "th"])
    p.add_argument("--only", default="")
    p.add_argument("--extract-only", action="store_true", help="สกัดข้อความอย่างเดียว ไม่เรียก LLM")
    p.add_argument("--report-only", action="store_true", help="ทำรายงานใหม่จาก jsonl เดิม")
    p.add_argument("--fresh", action="store_true", help="ลบผลเดิมแล้วเริ่มใหม่")
    args = p.parse_args()

    if args.fresh and RUNS.exists():
        RUNS.unlink()
        print("ลบผลเดิมแล้ว")

    engines = parse_engines(args.engines)
    paths = sorted(f for f in pathlib.Path(args.dir).iterdir()
                   if f.suffix.lower() in CONTENT_TYPES and not f.name.startswith("~$"))
    if args.only:
        paths = [f for f in paths if args.only.lower() in f.name.lower()]
    if not paths:
        print("ไม่พบไฟล์ทดสอบ")
        return 1

    # ---- สกัดข้อความก่อนทั้งหมด: รู้ปัญหาก่อนเสียเวลากับ LLM ----
    texts: dict[str, dict] = {}
    print(f"▸ สกัดข้อความ {len(paths)} ไฟล์ (ทำครั้งเดียว ใช้ร่วมทุก engine ทุกรอบ)")
    for f in paths:
        mb = f.stat().st_size / 1e6
        try:
            text, src = get_text(f)
            texts[f.name] = {"text": text, "chars": len(text), "mb": mb, "note": src}
            print(f"  ✅ {f.name[:46]:46} {len(text):>8,} ตัวอักษร ({src})")
        except Exception as err:  # noqa: BLE001
            note = extract_hint(str(err), mb) or str(err)[:120]
            texts[f.name] = {"text": None, "chars": None, "mb": mb, "note": note}
            print(f"  ✘ {f.name[:46]:46} {note}")
    usable = [f for f in paths if texts[f.name]["text"]]
    print(f"  สกัดได้ {len(usable)}/{len(paths)} ไฟล์")

    files = [f.name for f in paths]
    if args.extract_only:
        print("\n(--extract-only: หยุดที่นี่ ไม่เรียก LLM)")
        return 0 if len(usable) == len(paths) else 1

    # ---- รัน (resume ได้) ----
    if not args.report_only:
        done = {(r["file"], r["engine"], r["run"]) for r in load_runs()}
        todo = [(f, e, i) for f in usable for i in range(1, args.repeat + 1) for e in engines
                if (f.name, e["name"], i) not in done]
        print(f"\n▸ ต้องรัน {len(todo)} รายการ (ทำแล้ว {len(done)} ข้าม)")
        for n, (f, eng, run_i) in enumerate(todo, 1):
            print(f"  [{n}/{len(todo)}] {f.name[:34]:34} {eng['name']:16} รอบ {run_i} …",
                  end="", flush=True)
            rec = {"file": f.name, "engine": eng["name"], "provider": eng["provider"],
                   "run": run_i, "lang": args.lang}
            rec.update(run_one(texts[f.name]["text"], eng, args.lang))
            append_run(rec)          # เขียนทันทีทีละรายการ กันงานหาย
            print(f" {'%.2f' % rec['overall'] if rec.get('ok') else 'ล้มเหลว'} "
                  f"({rec['elapsed']}s)", flush=True)

    recs = [r for r in load_runs()
            if r["file"] in files and r["engine"] in [e["name"] for e in engines]]
    REPORT.write_text(build_report(recs, engines, files, texts, args.lang, args.repeat),
                      encoding="utf-8")
    print(f"\nเขียนรายงานไว้ที่: {REPORT}")
    print(f"ข้อมูลดิบ (ทำรายงานใหม่ได้ด้วย --report-only): {RUNS}")
    print("บอกผู้ช่วยว่า 'อ่านผล abtest' ได้เลย")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
