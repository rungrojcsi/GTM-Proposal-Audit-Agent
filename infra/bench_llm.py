"""วัดประสิทธิภาพเชิงเครื่องของ LLM server (Ollama) — ความเร็วต่อโมเดล + รับงานพร้อมกันได้แค่ไหน.

เรียกผ่าน infra/bench-llm.sh (ตัวนั้นโหลด env ให้) ไม่ควรรันไฟล์นี้ตรง ๆ

ทำไมใช้ Ollama native API (/api/chat) ไม่ใช่ /v1/chat/completions ที่แอปใช้:
Ollama คืนตัวเลขจับเวลาภายในมาด้วย -> แยก "เวลาโหลดโมเดลเข้า VRAM" ออกจาก
"เวลาประมวลผล prompt" และ "เวลาสร้างคำตอบ" ได้แม่นกว่าการจับเวลาจากภายนอก
เอนจินที่ทำงานเป็นตัวเดียวกัน ตัวเลขจึงใช้อ้างอิงกับการใช้งานจริงของแอปได้

วัดอะไร (ต่อโมเดล):
  - เวลาโหลดโมเดลเข้า VRAM ครั้งแรก (cold)      <- ตัวที่ทำให้ latency แกว่งในรายงานก่อน
  - ความเร็วอ่าน prompt (tokens/วินาที)          <- สำคัญมากกับเอกสารยาว
  - ความเร็วสร้างคำตอบ (tokens/วินาที)
  - เวลาจนได้ token แรกโดยประมาณ (cold และ warm)

วัดอะไร (concurrency): ยิงพร้อมกัน 1/2/4/8 งาน ดูว่าปริมาณงานรวมเพิ่มขึ้นหรือแค่เข้าคิว

ไม่แตะระบบที่ใช้งานจริง: ไม่เขียน DB ไม่เข้าคิวงาน ไม่เปลี่ยน settings
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / ".bench-output.txt"
RAW = HERE / ".bench-runs.jsonl"

BASE = os.environ.get("LOCAL_LLM_BASE_URL", "").rstrip("/")
ROOT = BASE[:-3].rstrip("/") if BASE.endswith("/v1") else BASE
KEY = os.environ.get("LOCAL_LLM_API_KEY", "")

# โมเดลที่แชทไม่ได้ — embedding / reranker / OCR (คำในชื่อบอกชนิด)
NOT_CHAT = ("embed", "rerank", "bge-", "paraphrase", "ocr", "nomic")

# prompt ยาวพอให้ตัวเลข "ความเร็วอ่าน prompt" มีความหมาย (ถ้าสั้นเกินจะวัดไม่ได้)
# แต่ไม่ยาวจนทดสอบนาน — ราว 2,000 token
_PARA = ("The vendor proposes a phased manufacturing execution system rollout covering "
         "line-side traceability, OEE dashboards, and integration with the existing ERP. "
         "Scope includes three plants, a shared master data service, and operator training. ")
PROMPT = ("Summarize the following procurement note in one short sentence.\n\n"
          + _PARA * 90)
NUM_PREDICT = 128          # จำกัดความยาวคำตอบให้เท่ากันทุกโมเดล -> tokens/s เทียบกันได้


def call(model: str, prompt: str, keep_alive: str | int = "5m",
         num_predict: int = NUM_PREDICT, timeout: int = 1200) -> dict:
    """เรียก /api/chat แบบไม่ stream แล้วคืนตัวเลขจับเวลาที่ Ollama ให้มา."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": keep_alive,
        "options": {"num_predict": num_predict, "temperature": 0},
    }).encode()
    req = urllib.request.Request(f"{ROOT}/api/chat", data=body, method="POST",
                                headers={"Content-Type": "application/json",
                                         "Authorization": f"Bearer {KEY}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as err:
        # ข้อความจริงอยู่ใน body ไม่ใช่ในสถานะ HTTP — ถ้าไม่อ่านจะเห็นแค่ "500" แล้ววินิจฉัยไม่ได้
        try:
            body = json.loads(err.read()).get("error", "")
        except Exception:  # noqa: BLE001
            body = ""
        return {"ok": False, "wall": round(time.monotonic() - t0, 2),
                "error": f"HTTP {err.code}: {(body or str(err))[:260]}"}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "wall": round(time.monotonic() - t0, 2),
                "error": f"{type(err).__name__}: {str(err)[:200]}"}
    ns = 1e9
    ev_c, ev_d = d.get("eval_count", 0), d.get("eval_duration", 0)
    pe_c, pe_d = d.get("prompt_eval_count", 0), d.get("prompt_eval_duration", 0)
    return {
        "ok": True,
        "wall": round(time.monotonic() - t0, 2),
        "load_s": round(d.get("load_duration", 0) / ns, 2),
        "prompt_tokens": pe_c,
        "prompt_s": round(pe_d / ns, 2),
        "prompt_tps": round(pe_c / (pe_d / ns), 1) if pe_d else None,
        "out_tokens": ev_c,
        "out_s": round(ev_d / ns, 2),
        "out_tps": round(ev_c / (ev_d / ns), 1) if ev_d else None,
        "total_s": round(d.get("total_duration", 0) / ns, 2),
        # เวลาจนได้ token แรกโดยประมาณ = โหลดโมเดล + อ่าน prompt
        "ttft_s": round((d.get("load_duration", 0) + pe_d) / ns, 2),
    }


def loaded_models() -> list[dict]:
    req = urllib.request.Request(f"{ROOT}/api/ps",
                                headers={"Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("models", [])
    except Exception:  # noqa: BLE001
        return []


def all_models() -> list[dict]:
    req = urllib.request.Request(f"{ROOT}/api/tags",
                                headers={"Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("models", [])


def chat_models() -> list[dict]:
    return [m for m in all_models()
            if not any(k in m["name"].lower() for k in NOT_CHAT)]


def unload(model: str) -> None:
    """คืน VRAM — ส่งงานจิ๋วพร้อม keep_alive=0 (โมเดลถูกปล่อยหลังตอบเสร็จ)."""
    call(model, "hi", keep_alive=0, num_predict=1, timeout=600)


def append(rec: dict) -> None:
    with RAW.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()


# ------------------------------------------------------------------ ส่วนที่ 1
def bench_speed(models: list[dict]) -> list[dict]:
    """ต่อโมเดล: วัด cold (รวมเวลาโหลด) แล้ววัด warm ทันที -> แยกเวลาโหลดออกได้."""
    rows = []
    for i, m in enumerate(models, 1):
        name = m["name"]
        gb = m.get("size", 0) / 1e9
        print(f"  [{i}/{len(models)}] {name[:42]:42} {gb:5.1f}GB ", end="", flush=True)

        # ให้แน่ใจว่าเย็นก่อนวัด cold
        if any(x["name"] == name for x in loaded_models()):
            unload(name)

        cold = call(name, PROMPT)                      # ค้างไว้ใน VRAM ต่อ
        if not cold["ok"]:
            print(f"✘ {cold['error'][:60]}")
            rows.append({"model": name, "gb": gb, "ok": False, "error": cold["error"]})
            append(rows[-1])
            continue
        warm = call(name, PROMPT, keep_alive=0)        # วัดซ้ำแล้วปล่อย VRAM
        row = {
            "model": name, "gb": gb, "ok": True,
            "load_s": cold["load_s"],
            "prompt_tokens": cold["prompt_tokens"],
            "prompt_tps": cold["prompt_tps"],
            "out_tps_cold": cold["out_tps"],
            "out_tps": warm["out_tps"] if warm["ok"] else cold["out_tps"],
            "ttft_cold_s": cold["ttft_s"],
            "ttft_warm_s": warm["ttft_s"] if warm["ok"] else None,
            "total_cold_s": cold["total_s"],
            "total_warm_s": warm["total_s"] if warm["ok"] else None,
            "out_tokens": cold["out_tokens"],
        }
        rows.append(row)
        append(row)
        print(f"โหลด {row['load_s']:5.1f}s · อ่าน {row['prompt_tps'] or 0:6.0f} tok/s "
              f"· ตอบ {row['out_tps'] or 0:5.1f} tok/s")
    return rows


# ------------------------------------------------------------------ ส่วนที่ 2
def bench_concurrency(model: str, levels: list[int]) -> list[dict]:
    """ยิงพร้อมกันหลายระดับ — ดูว่าปริมาณงานรวมเพิ่มขึ้นจริง หรือแค่เข้าคิวรอ."""
    rows = []
    print(f"\n  โมเดลที่ใช้ทดสอบ: {model}")
    call(model, "hi", num_predict=1)     # อุ่นเครื่องก่อน ไม่ให้เวลาโหลดปนผล
    for k in levels:
        print(f"  ยิงพร้อมกัน {k} งาน … ", end="", flush=True)
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=k) as ex:
            res = list(ex.map(lambda _: call(model, PROMPT), range(k)))
        wall = time.monotonic() - t0
        ok = [r for r in res if r["ok"]]
        if not ok:
            print("✘ ล้มทั้งหมด")
            rows.append({"level": k, "ok_count": 0, "wall_s": round(wall, 1)})
            append({"concurrency": rows[-1], "model": model})
            continue
        toks = sum(r["out_tokens"] for r in ok)
        row = {
            "level": k, "ok_count": len(ok), "wall_s": round(wall, 1),
            "lat_mean_s": round(statistics.mean(r["wall"] for r in ok), 1),
            "lat_max_s": round(max(r["wall"] for r in ok), 1),
            "out_tokens_total": toks,
            "throughput_tps": round(toks / wall, 1),
        }
        rows.append(row)
        append({"concurrency": row, "model": model})
        print(f"เสร็จ {len(ok)}/{k} · รวม {row['wall_s']}s "
              f"· ปริมาณงาน {row['throughput_tps']} tok/s · หน่วงเฉลี่ย {row['lat_mean_s']}s")
    return rows


# ------------------------------------------------------------------ รายงาน
def report(speed: list[dict], conc: list[dict], conc_model: str, vram: list[dict]) -> str:
    L: list[str] = []
    w = L.append
    ok = [r for r in speed if r.get("ok")]

    w("# ประสิทธิภาพเชิงเครื่องของ LLM server")
    w("")
    w(f"เซิร์ฟเวอร์: `{ROOT}` · โมเดลที่ทดสอบ {len(speed)} ตัว (แชทได้)")
    w(f"prompt ทดสอบ ~{ok[0]['prompt_tokens'] if ok else '?'} token · "
      f"จำกัดคำตอบ {NUM_PREDICT} token · temperature 0 · ยิงเรียงต่อกันไม่ขนาน")
    w("")
    w("ตัวเลขทั้งหมดมาจากตัวจับเวลาภายในของ Ollama เอง (`load_duration`, "
      "`prompt_eval_duration`, `eval_duration`) จึงแยกเวลาโหลดโมเดลออกจากเวลาประมวลผลได้")
    w("")

    w("## 1) ความเร็วต่อโมเดล")
    w("")
    w("| โมเดล | ขนาด | โหลดเข้า VRAM | อ่าน prompt | สร้างคำตอบ | ตอบครบ (เย็น) | ตอบครบ (อุ่น) |")
    w("|---|---|---|---|---|---|---|")
    for r in sorted(ok, key=lambda x: -(x["out_tps"] or 0)):
        w(f"| {r['model'][:38]} | {r['gb']:.1f}GB | {r['load_s']:.1f}s "
          f"| {r['prompt_tps'] or 0:,.0f} tok/s | **{r['out_tps'] or 0:.1f} tok/s** "
          f"| {r['total_cold_s']:.1f}s | {r['total_warm_s'] or 0:.1f}s |")
    bad = [r for r in speed if not r.get("ok")]
    if bad:
        w("")
        w("โมเดลที่เรียกไม่สำเร็จ:")
        w("")
        w("| โมเดล | อาการ |")
        w("|---|---|")
        for r in bad:
            w(f"| {r['model'][:38]} | {r.get('error','')[:90]} |")
    w("")
    if ok:
        loads = [r["load_s"] for r in ok]
        w(f"**เวลาโหลดโมเดลเข้า VRAM: {min(loads):.1f}s ถึง {max(loads):.1f}s** "
          f"(เฉลี่ย {statistics.mean(loads):.1f}s)")
        w("")
        w("ค่านี้คือส่วนที่ทำให้ latency แกว่งในการทดสอบคุณภาพครั้งก่อน — เกิดขึ้นเฉพาะครั้งแรก "
          "ที่เรียกโมเดลซึ่งไม่ได้ค้างอยู่ใน VRAM ถ้ามีงานเข้าต่อเนื่องจะไม่เสียเวลาส่วนนี้")
        w("")
        w("**อ่าน prompt vs สร้างคำตอบ ต่างกันคนละเรื่อง:** การอ่าน prompt เร็วกว่าการสร้างคำตอบ "
          "หลายสิบเท่า จึงเป็นเหตุผลว่าทำไมเอกสารยาวขึ้นไม่ได้ทำให้ช้าขึ้นตามสัดส่วน "
          "ตัวที่กินเวลาจริงคือความยาวคำตอบที่โมเดลต้องเขียน")
        w("")

    if vram:
        w("## 2) สถานะ VRAM ระหว่างทดสอบ")
        w("")
        w("| โมเดล | VRAM ที่ใช้ |")
        w("|---|---|")
        for m in vram:
            w(f"| {m['name'][:38]} | {m.get('size_vram', 0) / 1e9:.1f}GB |")
        w("")

    if conc:
        w("## 3) รับงานพร้อมกันได้แค่ไหน (concurrency)")
        w("")
        w(f"ทดสอบด้วย `{conc_model}` โมเดลอุ่นอยู่แล้ว (ไม่มีเวลาโหลดปน)")
        w("")
        w("| ยิงพร้อมกัน | สำเร็จ | เวลารวม | หน่วงเฉลี่ย/งาน | หน่วงสูงสุด | ปริมาณงานรวม |")
        w("|---|---|---|---|---|---|")
        for r in conc:
            if not r.get("ok_count"):
                w(f"| {r['level']} | 0 | {r['wall_s']}s | — | — | — |")
                continue
            w(f"| {r['level']} | {r['ok_count']}/{r['level']} | {r['wall_s']}s "
              f"| {r['lat_mean_s']}s | {r['lat_max_s']}s | **{r['throughput_tps']} tok/s** |")
        w("")
        base = next((r for r in conc if r["level"] == 1 and r.get("ok_count")), None)
        if base:
            w("วิธีอ่าน: ถ้าปริมาณงานรวมเพิ่มขึ้นตามจำนวนงานที่ยิง = เซิร์ฟเวอร์ทำขนานได้จริง "
              "· ถ้าปริมาณงานรวมนิ่งแต่หน่วงเฉลี่ยเพิ่มตามจำนวน = งานเข้าคิวรอ ทำได้ทีละงาน")
            w("")
            for r in conc:
                if r["level"] == 1 or not r.get("ok_count"):
                    continue
                gain = r["throughput_tps"] / base["throughput_tps"]
                lat = r["lat_mean_s"] / base["lat_mean_s"]
                verdict = ("ทำขนานได้" if gain > r["level"] * 0.6
                           else "เข้าคิว (ปริมาณงานไม่เพิ่ม)" if gain < 1.3 else "ขนานได้บางส่วน")
                w(f"- ยิง {r['level']} งาน: ปริมาณงาน {gain:.1f} เท่า · "
                  f"หน่วงต่องาน {lat:.1f} เท่า → **{verdict}**")
            w("")

    w("## ข้อจำกัดของการวัดนี้")
    w("")
    w("| ข้อจำกัด | ผลต่อการตีความ |")
    w("|---|---|")
    w("| prompt ทดสอบสั้นกว่า proposal จริงมาก | ความเร็วอ่าน prompt ที่วัดได้อาจไม่คงที่เมื่อ input ยาวขึ้นจริง |")
    w("| จำกัดคำตอบไว้ 128 token | งานจริงเขียนยาวกว่านี้หลายเท่า เวลารวมจริงจะมากกว่า |")
    w("| วัดครั้งเดียวต่อโมเดล | ไม่มีค่าความแกว่ง ตัวเลขใช้เทียบลำดับได้ ไม่ใช่ค่าที่แม่นระดับทศนิยม |")
    w("| ไม่ทราบว่ามีผู้ใช้อื่นแชร์เซิร์ฟเวอร์อยู่หรือไม่ | ถ้ามีงานอื่นแทรก ตัวเลขจะแย่กว่าความจริง |")
    w("| วัดผ่าน Ollama native API | แอปเรียกผ่าน /v1 ซึ่งเป็นชั้นห่ออีกที อาจมี overhead เล็กน้อยเพิ่ม |")
    w("")
    return "\n".join(L) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", default="", help="กรองชื่อโมเดล (substring)")
    p.add_argument("--skip-speed", action="store_true")
    p.add_argument("--conc-model", default="", help="โมเดลที่ใช้ทดสอบ concurrency")
    p.add_argument("--conc-levels", default="1,2,4,8")
    p.add_argument("--skip-conc", action="store_true")
    args = p.parse_args()

    if not ROOT:
        print("ไม่พบ LOCAL_LLM_BASE_URL")
        return 1
    models = chat_models()
    if args.only:
        models = [m for m in models if args.only.lower() in m["name"].lower()]
    print(f"เซิร์ฟเวอร์: {ROOT}")
    print(f"โมเดลที่แชทได้ {len(models)} ตัว (ตัด embedding/reranker/OCR ออกแล้ว)")
    cur = loaded_models()
    print(f"ค้างใน VRAM ตอนเริ่ม: {[m['name'] for m in cur] or 'ไม่มี'}\n")

    speed = []
    if not args.skip_speed:
        print("═══ ส่วนที่ 1: ความเร็วต่อโมเดล ═══")
        speed = bench_speed(models)

    vram = []
    conc = []
    conc_model = args.conc_model
    if not args.skip_conc:
        if not conc_model:
            ok = [r for r in speed if r.get("ok")]
            # เลือกตัวที่แอปใช้จริงถ้ามี ไม่งั้นเอาตัวที่เร็วสุด
            pref = [r for r in ok if r["model"].startswith(("gemma4:26b", "gpt-oss"))]
            conc_model = (pref or sorted(ok, key=lambda x: -(x["out_tps"] or 0)))[0]["model"] \
                if ok else (models[0]["name"] if models else "")
        if conc_model:
            print("\n═══ ส่วนที่ 2: รับงานพร้อมกันได้แค่ไหน ═══")
            conc = bench_concurrency(conc_model, [int(x) for x in args.conc_levels.split(",")])
            vram = loaded_models()

    OUT.write_text(report(speed, conc, conc_model, vram), encoding="utf-8")
    print(f"\nเขียนรายงานไว้ที่: {OUT}")
    print(f"ข้อมูลดิบ: {RAW}")
    print("บอกผู้ช่วยว่า 'อ่านผล bench' ได้เลย")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
