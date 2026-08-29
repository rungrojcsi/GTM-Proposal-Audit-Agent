/* ป้าย/ชิปเล็ก ๆ ที่ใช้ซ้ำหลายหน้า — แยกจาก App.tsx (H02) */
import { CONF_COLOR, SCORED_STATUS } from "../lib/format";

export const CsiLogo = () => (
  <img src="/logo.png" alt="CSI Groups" width={32} height={32} style={{ display: "block", objectFit: "contain" }} />
);


export function StatusBadge({ status }: { status: string | null }) {
  if (!status || SCORED_STATUS.has(status)) return null;
  const failed = status === "Failed";
  return (
    <span className="pill" style={{ background: failed ? "var(--red-soft)" : "var(--primary-soft)",
      color: failed ? "var(--red)" : "var(--primary)", whiteSpace: "nowrap" }}>
      {failed ? "ประเมินล้มเหลว" : "กำลังประเมิน…"}
    </span>
  );
}

export function ConfChip({ c }: { c?: string }) {
  if (!c) return null;
  return <span style={{ fontSize: 10.5, fontWeight: 700, color: CONF_COLOR[c] ?? "var(--text-3)", border: "1px solid currentColor", borderRadius: 999, padding: "1px 7px", marginLeft: 6 }}>{c}</span>;
}

export function SyncBadge({ status }: { status: string | null }) {
  // F41 — M3 ยังไม่ deploy: pending = รอ SharePoint setup
  const label = status === "synced" ? "SharePoint ✓" : status === "failed" ? "Sync failed" : "SharePoint: pending";
  const col = status === "synced" ? "var(--green)" : status === "failed" ? "var(--red)" : "var(--text-3)";
  return <span style={{ fontSize: 11.5, fontWeight: 700, color: col, background: "var(--surface-2)", borderRadius: 999, padding: "3px 10px" }}>{label}</span>;
}


export function KpiTile({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="card card-pad" style={{ flex: 1, minWidth: 150 }}>
      <div style={{ fontSize: 12.5, color: "var(--text-2)", marginBottom: 6 }}>{label}</div>
      <div className="num" style={{ fontSize: 28, fontWeight: 800, color: color ?? "var(--text)", lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11.5, color: "var(--text-3)", marginTop: 5 }}>{sub}</div>}
    </div>
  );
}

