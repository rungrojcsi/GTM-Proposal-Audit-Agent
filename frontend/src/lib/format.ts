/* ค่าคงที่การแสดงผล + ฟังก์ชันจัดรูปแบบ — แยกจาก App.tsx (H02)
   ไม่มี JSX ในไฟล์นี้ (นามสกุล .ts) */
import type { Audience, Role } from "../api/client";

export const verdictVar: Record<string, string> = {
  Strong: "var(--green)", Adequate: "var(--amber)", Weak: "var(--orange)", Critical: "var(--red)",
};
export const verdictSoft: Record<string, string> = {
  Strong: "var(--green-soft)", Adequate: "var(--amber-soft)", Weak: "var(--orange-soft)", Critical: "var(--red-soft)",
};
/* F01 — เกณฑ์สีต้องตรงกับ scoring.map_verdict ฝั่ง backend (7 / 5 / 3.5) เป๊ะ
   เดิมใช้ 8/6/4 ทำให้คะแนน 7.5 แสดงตัวเลขสีเหลืองแต่ป้ายบอก "Strong" สีเขียวในแถวเดียวกัน */

export const SCORE_THRESHOLD = { strong: 7, adequate: 5, weak: 3.5 } as const;
export function scoreVar(s: number): string {
  return s >= SCORE_THRESHOLD.strong ? "var(--green)"
    : s >= SCORE_THRESHOLD.adequate ? "var(--amber)"
    : s >= SCORE_THRESHOLD.weak ? "var(--orange)"
    : "var(--red)";
}
/* ตัวย่อชื่อผู้ใช้สำหรับ avatar (F02) — ใช้ร่วมทั้ง sidebar และแถบบน */
export function initials(name: string | null | undefined): string {
  return (name ?? "GU").trim().slice(0, 2).toUpperCase() || "GU";
}
/* E04 — เพดานขนาดไฟล์ ต้องตรงกับ _MAX_BYTES ใน api/function_app.py */

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export function bySectionNo<T extends { slide_section: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => (parseInt(a.slide_section, 10) || 0) - (parseInt(b.slide_section, 10) || 0));
}


export const TIER_ORDER: Record<string, number> = { Critical: 0, Important: 1, Optional: 2 };


export const SCORED_STATUS = new Set(["Evaluated", "Accepted"]);

export const CONF_COLOR: Record<string, string> = { high: "var(--green)", medium: "var(--amber)", low: "var(--red)" };

export const OUTCOME_COLOR: Record<string, string> = { Won: "var(--green)", Lost: "var(--red)", Pending: "var(--amber)" };
export function fmtMoney(v: number | null, cur: string | null): string {
  return v == null ? "-" : `${Number(v).toLocaleString()} ${cur ?? ""}`.trim();
}
/* Library table sorting (คลิกหัว column) */

export const ROLE_LABEL: Record<Role, string> = { user: "User", manager: "Manager", management: "Management", admin: "Master Admin" };


export const PAGE_LABEL: Record<string, string> = {
  evaluate: "New Evaluation", proposals: "Evaluation Results", library: "Proposal Library",
  dashboard: "Dashboard", settings: "Settings", view_all: "เห็นทุกโปรเจค",
};

export const AUDIT_LABEL: Record<string, string> = {
  "content.update": "แก้ข้อมูลการเงิน/โครงการ",
  "content.verify": "ยืนยันข้อมูล (verify)",
  "thread.rename": "แก้ชื่อ client/project",
  "thread.delete": "ลบโปรเจค",
  "user.role": "เปลี่ยน role ผู้ใช้",
  "role.perms": "แก้สิทธิ์ของ role",
  "settings.network": "แก้การจำกัดเครือข่าย",
  "playbook.upload": "อัปโหลด/แทนที่ไฟล์คู่มือ",
  "playbook.delete": "ลบไฟล์คู่มือ",
};

/** ขนาดไฟล์อ่านง่าย — ใช้ในหน้า Playbook (ไฟล์ 16-20 MB บอกเป็น byte อ่านไม่รู้เรื่อง) */
export function fmtBytes(n: number): string {
  if (!n || n < 0) return "-";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function evalStep(sec: number): string {
  if (sec < 15) return "ส่งเข้าคิวแล้ว — รอเครื่องประเมินรับงาน";
  if (sec < 75) return "กำลังอ่าน proposal และให้คะแนน 17 หัวข้อ";
  if (sec < 180) return "กำลังสรุปจุดแข็ง ช่องว่าง และคำแนะนำ";
  return "กำลังประกอบโครงร่างที่แนะนำ — ใกล้เสร็จแล้ว";
}
export function mmss(sec: number): string {
  return `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
}


export const AUDIENCES: { k: Audience; label: string }[] = [
  { k: "c_level", label: "C-Level (ผู้บริหาร)" },
  { k: "users", label: "Users (ผู้ใช้งาน)" },
  { k: "it", label: "IT" },
  { k: "purchase", label: "Purchase (จัดซื้อ)" },
  { k: "technical", label: "Technical" },
  { k: "non_technical", label: "Non-technical" },
];

/* แท็บในหน้าผลประเมิน */
export type TabKey = "history" | "score" | "recs" | "skeleton" | "sg" | "comments" | "coach";
export const TABS: { key: TabKey; label: string }[] = [
  { key: "score", label: "Section Scores" },
  { key: "sg", label: "Strengths & Gaps" },
  { key: "recs", label: "Recommendations" },
  { key: "skeleton", label: "Skeleton" },
  { key: "coach", label: "Presentation Coach" },
  { key: "history", label: "History" },
  { key: "comments", label: "Comments" },
];
