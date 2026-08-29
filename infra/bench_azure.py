"""วัดความเร็ว Azure OpenAI ด้วย prompt ชุดเดียวกับ bench_llm.py แล้วเทียบกับโมเดล local.

เรียกผ่าน infra/bench-llm.sh --azure

ทำไมต้องมีไฟล์แยก: Azure ไม่คืนตัวจับเวลาภายในแบบ Ollama (`eval_duration`)
วัดได้แค่ "เวลารวมที่ผู้เรียกรอ" จึงต้องเทียบกันบนฐานเดียวกัน คือ

    tok/s = จำนวน token ที่ได้ / เวลารวมที่รอ

ตัวเลข tok/s ของ local ในรายงาน bench เดิมคิดจาก eval_duration (เวลาสร้างคำตอบล้วน
ไม่รวมเวลาอ่าน prompt และไม่รวม network) ซึ่ง **สูงกว่า** ฐานนี้ จึงนำมาเทียบกับ Azure ตรง ๆ ไม่ได้
ไฟล์นี้จะคำนวณของ local ใหม่บนฐานเวลารวม เพื่อให้เทียบได้จริง

หมายเหตุที่ต้องระบุในรายงาน: เวลารวมของ Azure มี network ข้ามอินเทอร์เน็ตปนอยู่
ส่วน local อยู่ในเครือข่ายบริษัท — ความต่างนี้เป็นส่วนหนึ่งของประสบการณ์ใช้งานจริง ไม่ใช่ความคลาดเคลื่อน
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

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from bench_llm import NUM_PREDICT, PROMPT as _BASE  # noqa: E402

# prompt ของ bench_llm สั่งให้ "สรุปสั้น" ซึ่ง Azure ทำตามแล้วหยุดที่ ~33 token
# ขณะที่ local เขียนยาวจนชนเพดาน 128 -> tok/s เทียบกันไม่ได้
# จึงเปลี่ยนคำสั่งให้บังคับเขียนยาว ให้ทั้งสองฝั่งชนเพดานเท่ากัน (เนื้อหา input เดิม)
_INPUT = _BASE.split("\n\n", 1)[1]
PROMPT = ("Write a detailed risk assessment of the procurement note below. "
          "Cover at least twelve distinct risks, two sentences each. Be exhaustive.\n\n" + _INPUT)

RAW = HERE / ".bench-runs.jsonl"
OUT = HERE / ".bench-azure-output.txt"

EP = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
KEY = os.environ.get("AZURE_OPENAI_KEY", "")
DEP = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
VER = os.environ.get("AZURE_OPENAI_API_VERSION", "")


def call(stream: bool = False, timeout: int = 600) -> dict:
    """เรียก Azure OpenAI 1 ครั้ง — คืนเวลารวม จำนวน token และ TTFT (ถ้า stream)."""
    url = f"{EP}/openai/deployments/{DEP}/chat/completions?api-version={VER}"
    # gpt-5.x ใช้ max_completion_tokens (เลิกรับ max_tokens) และรับ temperature ได้แค่ค่า default
    payload = {
        "messages": [{"role": "user", "content": PROMPT}],
        "max_completion_tokens": NUM_PREDICT,
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                headers={"Content-Type": "application/json", "api-key": KEY})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if not stream:
                d = json.loads(r.read())
                wall = time.monotonic() - t0
                u = d.get("usage", {})
                return {"ok": True, "wall": round(wall, 2), "ttft_s": None,
                        "prompt_tokens": u.get("prompt_tokens"),
                        "out_tokens": u.get("completion_tokens"),
                        "out_tps_wall": round(u.get("completion_tokens", 0) / wall, 1) if wall else None}
            ttft = None
            usage = {}
            for raw in r:
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    ch = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if ch.get("usage"):
                    usage = ch["usage"]
                ch_list = ch.get("choices") or []
                if ttft is None and ch_list and (ch_list[0].get("delta") or {}).get("content"):
                    ttft = time.monotonic() - t0
            wall = time.monotonic() - t0
            out = usage.get("completion_tokens", 0)
            return {"ok": True, "wall": round(wall, 2),
                    "ttft_s": round(ttft, 2) if ttft else None,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "out_tokens": out,
                    "out_tps_wall": round(out / wall, 1) if wall else None}
    except urllib.error.HTTPError as err:
        try:
            body = json.loads(err.read()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            body = ""
        return {"ok": False, "wall": round(time.monotonic() - t0, 2),
                "error": f"HTTP {err.code}: {(body or str(err))[:240]}"}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "wall": round(time.monotonic() - t0, 2),
                "error": f"{type(err).__name__}: {str(err)[:200]}"}


def local_rows() -> list[dict]:
    """อ่านผล local จาก .bench-runs.jsonl (เฉพาะรายการที่สำเร็จ)."""
    if not RAW.exists():
        return []
    out = []
    for line in RAW.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("ok") and r.get("model") and r.get("total_warm_s"):
            out.append(r)
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3)
    args = p.parse_args()
    for name, v in (("AZURE_OPENAI_ENDPOINT", EP), ("AZURE_OPENAI_KEY", KEY),
                    ("AZURE_OPENAI_DEPLOYMENT", DEP), ("AZURE_OPENAI_API_VERSION", VER)):
        if not v:
            print(f"ไม่พบ {name}")
            return 1

    print(f"Azure deployment: {DEP} · api-version {VER}")
    print(f"prompt เดียวกับที่ใช้วัด local · จำกัดคำตอบ {NUM_PREDICT} token\n")

    runs = []
    for i in range(1, args.runs + 1):
        print(f"  รอบ {i}/{args.runs} … ", end="", flush=True)
        r = call(stream=True)          # ต้อง stream เพื่อได้ TTFT แยกจากเวลาสร้างคำตอบ
        if r.get("ok") and r.get("ttft_s") and r.get("out_tokens"):
            gen = max(r["wall"] - r["ttft_s"], 1e-6)
            r["gen_tps"] = round(r["out_tokens"] / gen, 1)
        runs.append(r)
        with RAW.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"azure": r, "run": i, "deployment": DEP},
                                ensure_ascii=False) + "\n")
        print(f"รวม {r['wall']}s · TTFT {r.get('ttft_s')}s · {r.get('out_tokens')} token "
              f"· สร้างคำตอบ {r.get('gen_tps')} tok/s" if r["ok"] else f"✘ {r['error'][:90]}")
    st = runs[-1] if runs else {}

    ok = [r for r in runs if r["ok"]]
    if not ok:
        print("\nเรียก Azure ไม่สำเร็จเลย — ดู error ด้านบน")
        return 1

    a_wall = statistics.mean(r["wall"] for r in ok)
    a_tps = statistics.mean(r["out_tps_wall"] for r in ok)
    a_out = statistics.mean(r["out_tokens"] for r in ok)
    a_prompt = ok[0]["prompt_tokens"]

    L: list[str] = []
    w = L.append
    w("# เทียบความเร็ว: Azure OpenAI vs โมเดล local")
    w("")
    w("**ฐานการเทียบ:** `tok/s = จำนวน token ที่ได้ / เวลารวมที่ผู้เรียกรอ` ใช้เหมือนกันทั้งสองฝั่ง")
    w("")
    w("ตัวเลข tok/s ในรายงาน bench เดิมของ local คิดจากตัวจับเวลาภายในของ Ollama "
      "(เวลาสร้างคำตอบล้วน ไม่รวมเวลาอ่าน prompt ไม่รวม network) ซึ่งสูงกว่าฐานนี้ "
      "**จึงเทียบกับ Azure ตรง ๆ ไม่ได้** ตารางนี้คิดของ local ใหม่บนฐานเวลารวม")
    w("")
    w(f"prompt {a_prompt:,} token · จำกัดคำตอบ {NUM_PREDICT} token · "
      f"Azure วัด {len(ok)} รอบ · local วัด 1 รอบต่อโมเดล")
    w("")

    w("## Azure OpenAI")
    w("")
    w("| รายการ | ค่า |")
    w("|---|---|")
    w(f"| deployment | `{DEP}` |")
    w(f"| เวลารวมเฉลี่ย | **{a_wall:.2f}s** (ต่ำสุด {min(r['wall'] for r in ok):.2f} "
      f"สูงสุด {max(r['wall'] for r in ok):.2f}) |")
    w(f"| token ที่ได้ | {a_out:.0f} |")
    w(f"| ความเร็วบนฐานเวลารวม | **{a_tps:.1f} tok/s** |")
    if st.get("ok") and st.get("ttft_s"):
        w(f"| เวลาจนได้ token แรก | **{st['ttft_s']:.2f}s** |")
    w("| เวลาโหลดโมเดล | **ไม่มี** — พร้อมใช้เสมอ |")
    w("")

    rows = local_rows()
    if rows:
        w("## เทียบกันบนฐานเดียวกัน (เวลารวม)")
        w("")
        w("| โมเดล | ขนาด | เวลารวม (อุ่น) | tok/s ฐานเวลารวม | เทียบ Azure | เวลารวม (เย็น) |")
        w("|---|---|---|---|---|---|")
        w(f"| **Azure {DEP}** | — | **{a_wall:.2f}s** | **{a_tps:.1f}** | 1.0× | ไม่มีสถานะเย็น |")
        for r in sorted(rows, key=lambda x: -(x["out_tokens"] / x["total_warm_s"])):
            tps = r["out_tokens"] / r["total_warm_s"]
            w(f"| {r['model'][:34]} | {r['gb']:.1f}GB | {r['total_warm_s']:.2f}s "
              f"| {tps:.1f} | {tps / a_tps:.1f}× | {r['total_cold_s']:.1f}s |")
        w("")
        best = max(rows, key=lambda x: x["out_tokens"] / x["total_warm_s"])
        best_tps = best["out_tokens"] / best["total_warm_s"]
        w(f"**โมเดล local ที่เร็วสุดคือ `{best['model']}` ที่ {best_tps:.1f} tok/s "
          f"= {best_tps / a_tps:.1f} เท่าของ Azure**")
        w("")
        w("ข้อควรระวัง: เวลารวมของ Azure มีการเดินทางข้ามอินเทอร์เน็ตปนอยู่ ส่วน local "
          "อยู่ในเครือข่ายที่ใกล้กว่า ความต่างนี้เป็นส่วนหนึ่งของประสบการณ์ใช้งานจริง "
          "ไม่ใช่ความคลาดเคลื่อนของการวัด")
        w("")
        w("**แต่ความเร็วนี้เป็นภาพเฉพาะเมื่อโมเดลอุ่นอยู่แล้ว** — คอลัมน์ขวาสุดคือเวลาจริง "
          "เมื่อโมเดลยังไม่ถูกโหลด ซึ่งเป็นสถานะปกติของเซิร์ฟเวอร์นี้ (`/api/ps` ว่างเปล่า)")
        w("")
        w("| สถานการณ์ | Azure | local ที่เร็วสุด |")
        w("|---|---|---|")
        w(f"| งานแรกของวัน (โมเดลเย็น) | {a_wall:.1f}s | **{best['total_cold_s']:.0f}s** "
          f"({best['total_cold_s'] / a_wall:.0f} เท่า) |")
        w(f"| งานต่อเนื่อง (โมเดลอุ่น) | {a_wall:.1f}s | {best['total_warm_s']:.1f}s "
          f"({best['total_warm_s'] / a_wall:.1f} เท่า) |")
        w("")

    w("## ข้อจำกัด")
    w("")
    w("| ข้อจำกัด | ผลต่อการตีความ |")
    w("|---|---|")
    w(f"| Azure วัด {len(ok)} รอบ · local วัด 1 รอบต่อโมเดล | ตัวเลข local ไม่มีค่าความแกว่ง |")
    w("| จำกัดคำตอบ 128 token | งานประเมินจริงเขียนยาวกว่านี้หลายเท่า ส่วนต่างจะขยายตามความยาวคำตอบ |")
    w("| วัดจากเครื่องเดียว ณ เวลาหนึ่ง | ไม่ครอบคลุมช่วงที่เซิร์ฟเวอร์หรือ Azure มีภาระงานสูง |")
    w("| ไม่ได้วัดด้วย prompt ขนาดเท่า proposal จริง | prompt จริงยาวกว่านี้ราว 9 เท่า |")
    w("")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\nเขียนรายงานไว้ที่: {OUT}")
    print("บอกผู้ช่วยว่า 'อ่านผล bench azure' ได้เลย")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
