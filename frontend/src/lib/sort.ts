/* ตรรกะเรียงลำดับตาราง (คลิกหัวคอลัมน์) — แยกจาก App.tsx (H02) */
import type { LibraryRow, ProposalRow, ScoreDetail } from "../api/client";
import { TIER_ORDER } from "./format";

export type SortKey = "ticket_no" | "client_name" | "project_name" | "owner_name" | "version_no" | "version_count" | "overall_score" | "verdict" | "score_source" | "evaluated_at";
export const PROP_COLS: { key: SortKey; label: string }[] = [
  { key: "ticket_no", label: "Ticket" },
  { key: "client_name", label: "Client" },
  { key: "project_name", label: "Project" },
  { key: "owner_name", label: "Owner" },
  { key: "version_no", label: "Version" },
  { key: "overall_score", label: "Score" },
  { key: "verdict", label: "Verdict" },
  { key: "score_source", label: "Source" },
  { key: "evaluated_at", label: "Updated" },
];

export const VERDICT_RANK: Record<string, number> = { Strong: 4, Adequate: 3, Weak: 2, Critical: 1 };
/* E06 — สถานะที่ถือว่า "มีคะแนนแล้ว". อื่น ๆ (Evaluating/Failed) ต้องขึ้นป้ายบอก
   ไม่ใช่ปล่อยช่องคะแนนว่างให้ผู้ใช้เข้าใจว่าคะแนนหาย */

export const NUM_DEFAULT_DESC: SortKey[] = ["version_no", "version_count", "overall_score", "verdict", "evaluated_at"];
export function sortProposals(rows: ProposalRow[], key: SortKey, dir: "asc" | "desc"): ProposalRow[] {
  const sign = dir === "asc" ? 1 : -1;
  const numVal = (p: ProposalRow): number | null =>
    key === "overall_score" ? (p.overall_score != null ? Number(p.overall_score) : -1)
    : key === "version_no" ? p.version_no
    : key === "version_count" ? p.version_count
    : key === "verdict" ? (VERDICT_RANK[p.verdict ?? ""] ?? 0)
    : null;
  return [...rows].sort((a, b) => {
    const an = numVal(a), bn = numVal(b);
    if (an !== null && bn !== null) return (an - bn) * sign;
    const as = String(a[key] ?? "").toLowerCase();
    const bs = String(b[key] ?? "").toLowerCase();
    return (as < bs ? -1 : as > bs ? 1 : 0) * sign;
  });
}


export type LibSortKey = "ticket_no" | "client_name" | "project_name" | "owner_name" | "industry" | "solution_type"
  | "price_amount" | "duration_months" | "deal_outcome" | "verify_status" | "overall_score";
export const LIB_COLS: { key: LibSortKey; label: string }[] = [
  { key: "ticket_no", label: "Ticket" },
  { key: "client_name", label: "Client" },
  { key: "project_name", label: "Project" },
  { key: "owner_name", label: "Owner" },
  { key: "industry", label: "Industry" },
  { key: "solution_type", label: "Solution" },
  { key: "price_amount", label: "Price" },
  { key: "duration_months", label: "Months" },
  { key: "deal_outcome", label: "Outcome" },
  { key: "verify_status", label: "Verify" },
  { key: "overall_score", label: "Score" },
];
export const LIB_NUM_KEYS: LibSortKey[] = ["price_amount", "duration_months", "overall_score"];

export function sortLibrary(rows: LibraryRow[], key: LibSortKey, dir: "asc" | "desc"): LibraryRow[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (LIB_NUM_KEYS.includes(key)) {
      // null อยู่ท้ายเสมอไม่ว่าจะ sort ทางไหน
      const an = a[key] != null ? Number(a[key]) : null;
      const bn = b[key] != null ? Number(b[key]) : null;
      if (an == null && bn == null) return 0;
      if (an == null) return 1;
      if (bn == null) return -1;
      return (an - bn) * sign;
    }
    const as = String(a[key] ?? "").toLowerCase();
    const bs = String(b[key] ?? "").toLowerCase();
    return (as < bs ? -1 : as > bs ? 1 : 0) * sign;
  });
}


/* ---------- ตาราง Section Scores ในหน้าผลประเมิน ---------- */

export type SectionSortKey = "section" | "tier" | "score";
export const SECTION_COLS: { key: SectionSortKey; label: string }[] = [
  { key: "section", label: "Section" },
  { key: "tier", label: "Tier" },
  { key: "score", label: "Score" },
];
/* ทิศทางเริ่มต้นตอนคลิกคอลัมน์ครั้งแรก — เลือกทิศที่ "มีประโยชน์ก่อน" ในแต่ละคอลัมน์
   section: 1→17 ตามลำดับเอกสาร · tier: Critical ก่อน · score: คะแนนต่ำก่อน (จุดที่ต้องแก้) */
export const SECTION_FIRST_DIR: Record<SectionSortKey, "asc" | "desc"> = {
  section: "asc", tier: "asc", score: "asc",
};

/** เลขหัวข้อจาก "7. Solution Architecture" -> 7 (ไม่มีเลข -> 0 อยู่ต้น) */
function sectionNo(s: string): number {
  return parseInt(s, 10) || 0;
}

export function sortSections(rows: ScoreDetail[], key: SectionSortKey, dir: "asc" | "desc"): ScoreDetail[] {
  const sign = dir === "asc" ? 1 : -1;
  const val = (d: ScoreDetail): number =>
    key === "tier" ? (TIER_ORDER[d.tier] ?? 9)
    : key === "score" ? Number(d.score_1_10)
    : sectionNo(d.slide_section);
  return [...rows].sort((a, b) => {
    const diff = (val(a) - val(b)) * sign;
    // tier/score เท่ากันบ่อย -> ตัดสินด้วยเลขหัวข้อเสมอ ให้ลำดับคงที่ (stable) ทุกครั้งที่กด
    return diff !== 0 ? diff : sectionNo(a.slide_section) - sectionNo(b.slide_section);
  });
}
