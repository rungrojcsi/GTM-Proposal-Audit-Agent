"""Eval harness for the proposal-master evaluation pipeline.

โหมด:
  python run_eval.py              -> OFFLINE เท่านั้น (ไม่เรียก API) — ทดสอบ invariant + determinism
  python run_eval.py --integration -> เรียก Azure OpenAI จริงกับ fixtures (ต้องตั้ง env vars)

Integration ตรวจ:
  - โครงสร้าง: score_details ครบ 17 section เสมอ, tier ตรง rubric
  - relative ordering: strong_proposal ต้องได้คะแนน > weak_proposal
  - anti-pattern: weak_proposal ควรถูก flag (Why-Us-first / TBD team / one-number pricing)

Exit code: 0 = ผ่านทั้งหมด, 1 = มี assertion fail
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ให้ import จาก ../api/shared ได้
_API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(_API_DIR))

from shared.evaluation import _normalize_to_rubric  # noqa: E402
from shared.models import EvaluationLLMOutput, Recommendation, ScoreDetail  # noqa: E402
from shared.rubric import CANONICAL_SECTIONS, SECTION_TIER  # noqa: E402
from shared.scoring import CALIBRATION_OFFSET, TIER_WEIGHT, compute_overall_score, map_verdict  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PASS, _FAIL = "✅ PASS", "❌ FAIL"
_failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _failures
    print(f"  {_PASS if ok else _FAIL}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        _failures += 1


# =====================================================================
# OFFLINE — ทดสอบ deterministic core โดยไม่เรียก API
# =====================================================================
def run_offline() -> None:
    print("\n=== OFFLINE: rubric normalization + deterministic scoring ===")

    # LLM ส่งมาไม่ครบ + มี section แปลกปลอม + score เกินขอบเขต
    partial = EvaluationLLMOutput(
        score_details=[
            ScoreDetail(slide_section="4. Pain Statement", tier="Critical", score_1_10=9, coverage="strong"),
            ScoreDetail(slide_section="10. Commercial Summary & TCO", tier="Critical", score_1_10=15, coverage="over-range"),
            ScoreDetail(slide_section="1. Hero Cover", tier="Optional", score_1_10=7, coverage="wrong-tier-from-llm"),
            ScoreDetail(slide_section="99. Bogus Section", tier="Critical", score_1_10=10, coverage="not in rubric"),
        ],
        recommendations=[Recommendation(priority="Critical", rec_text="add cost of inaction", slide_ref="Slide 5")],
        skeleton_md="# skeleton",
        strengths=["clear pain"],
        gaps=["no cost of inaction"],
    )
    norm = _normalize_to_rubric(partial)

    check("ได้ครบ 17 section เสมอ", len(norm.score_details) == 17, f"got {len(norm.score_details)}")
    check("section แปลกปลอมถูกตัดทิ้ง",
          all(d.slide_section != "99. Bogus Section" for d in norm.score_details))
    check("tier ถูก override ตาม rubric",
          all(d.tier == SECTION_TIER[d.slide_section] for d in norm.score_details),
          "Hero Cover ต้องเป็น Important ไม่ใช่ Optional ที่ LLM ส่งมา")
    check("score เกินขอบเขตถูก clamp เป็น 0-10",
          all(0 <= d.score_1_10 <= 10 for d in norm.score_details))
    missing = {d.slide_section for d in norm.score_details if d.coverage == "missing"}
    check("section ที่ LLM ไม่ส่ง -> เติม missing (score 0)",
          "5. Cost of Inaction" in missing and len(missing) == 14)

    # determinism: normalize+score ซ้ำ ต้องได้เท่ากันเป๊ะ
    s1 = compute_overall_score(_normalize_to_rubric(partial).score_details)
    s2 = compute_overall_score(_normalize_to_rubric(partial).score_details)
    check("คะแนนรวม deterministic (รันซ้ำได้ค่าเดียวกัน)", s1 == s2, f"{s1} == {s2}")

    # verdict boundaries (v4 threshold: 7 / 5 / 3.5)
    check("verdict mapping ถูกต้องที่ขอบเขต",
          map_verdict(7.0) == "Strong" and map_verdict(6.99) == "Adequate"
          and map_verdict(5.0) == "Adequate" and map_verdict(4.99) == "Weak"
          and map_verdict(3.5) == "Weak" and map_verdict(3.49) == "Critical")

    # denominator คงที่ (v6 = 48: weight 4/3/1, tier v5)
    denom = sum(TIER_WEIGHT[t] for _, t in CANONICAL_SECTIONS)
    check("weighted denominator คงที่ = 48", denom == 48, f"got {denom}")

    # calibration offset (v7): ทุก section=5 -> raw 5.0 + offset ; ทุก section=10 -> clamp 10
    flat5 = [ScoreDetail(slide_section=n, tier=t, score_1_10=5, coverage="") for n, t in CANONICAL_SECTIONS]
    flat10 = [ScoreDetail(slide_section=n, tier=t, score_1_10=10, coverage="") for n, t in CANONICAL_SECTIONS]
    check(f"calibration offset = {CALIBRATION_OFFSET} apply (ทุก section=5 -> {5 + CALIBRATION_OFFSET})",
          compute_overall_score(flat5) == round(5 + CALIBRATION_OFFSET, 2),
          f"got {compute_overall_score(flat5)}")
    check("calibrated score clamp เพดาน 10 (ทุก section=10 -> 10.0)",
          compute_overall_score(flat10) == 10.0, f"got {compute_overall_score(flat10)}")


# =====================================================================
# INTEGRATION — เรียก GPT-4o จริง (ต้องมี env vars)
# =====================================================================
_REQUIRED_ENV = ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_VERSION"]


def _print_report(name: str, result: EvaluationLLMOutput, overall: float) -> None:
    print(f"\n  --- {name}: {overall:.2f}/10 ({map_verdict(overall)}) ---")
    for d in result.score_details:
        print(f"    {d.tier}  {d.score_1_10:>2}  {d.slide_section}")
    if result.gaps:
        print("    gaps:", "; ".join(result.gaps[:3]))


def run_integration() -> None:
    print(f"\n=== INTEGRATION: Azure OpenAI ({os.environ.get('AZURE_OPENAI_DEPLOYMENT', '?')}) จริง ===")
    missing_env = [e for e in _REQUIRED_ENV if not os.environ.get(e)]
    if missing_env:
        print(f"  {_FAIL}  ขาด env vars: {', '.join(missing_env)} — ข้าม integration")
        globals()["_failures"] += 1
        return

    from shared.evaluation import evaluate_proposal  # lazy — ต้องมี openai ติดตั้ง

    results: dict[str, tuple[EvaluationLLMOutput, float]] = {}
    for fixture in ["strong_proposal.txt", "weak_proposal.txt"]:
        text = (_FIXTURES / fixture).read_text(encoding="utf-8")
        r = evaluate_proposal(text)
        overall = compute_overall_score(r.score_details)
        results[fixture] = (r, overall)
        _print_report(fixture, r, overall)

        check(f"[{fixture}] ได้ครบ 17 section", len(r.score_details) == 17)
        check(f"[{fixture}] tier ตรง rubric",
              all(d.tier == SECTION_TIER[d.slide_section] for d in r.score_details))

    strong = results["strong_proposal.txt"][1]
    weak = results["weak_proposal.txt"][1]
    check("strong ได้คะแนน > weak (relative ordering)", strong > weak, f"{strong:.2f} > {weak:.2f}")

    # anti-pattern: weak ควรถูก flag (soft — เตือนถ้าไม่เจอ ไม่ fail เพราะ wording LLM แปรผัน)
    weak_text = " ".join(results["weak_proposal.txt"][0].gaps).lower()
    hit = any(k in weak_text for k in ["why us", "why-us", "pain", "tbd", "team", "pricing", "breakdown", "cost of inaction"])
    if not hit:
        print("  ⚠️  weak_proposal gaps ไม่ได้ระบุ anti-pattern ที่คาด — ตรวจ prompt tuning")


def main() -> int:
    print("Proposal Evaluator — eval harness")
    run_offline()
    if "--integration" in sys.argv:
        run_integration()
    else:
        print("\n(ข้าม integration — ใส่ --integration + ตั้ง AZURE_OPENAI_* env เพื่อเรียก GPT จริง)")

    print(f"\n=== {'ALL PASSED' if _failures == 0 else str(_failures) + ' CHECK(S) FAILED'} ===")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
