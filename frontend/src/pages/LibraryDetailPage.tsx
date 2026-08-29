/* F32/F33 — หน้ารายละเอียด Proposal Library (แก้/ยืนยันข้อมูลการเงิน) */
import { useState } from "react";
import { updateLibraryItem, type DealOutcome, type LibraryItem, type ManpowerRow, type Milestone } from "../api/client";
import { ConfChip, SyncBadge } from "../components/badges";
import AuditTrail from "../components/AuditTrail";
import { OUTCOME_COLOR } from "../lib/format";

export function LibraryDetail({ item, onBack, onSaved }: { item: LibraryItem; onBack: () => void; onSaved: (it: LibraryItem) => void }) {
  const [f, setF] = useState({
    price_amount: item.price_amount != null ? String(item.price_amount) : "",
    price_currency: item.price_currency ?? "",
    cost_amount: item.cost_amount != null ? String(item.cost_amount) : "",
    cost_currency: item.cost_currency ?? "",
    duration_months: item.duration_months != null ? String(item.duration_months) : "",
    solution_type: item.solution_type ?? "",
    industry: item.industry ?? "",
    deal_outcome: (item.deal_outcome ?? "Pending") as DealOutcome,
  });
  const [ms, setMs] = useState<Milestone[]>(item.milestones ?? []);
  const [mp, setMp] = useState<ManpowerRow[]>(item.manpower ?? []);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const conf = item.field_confidence ?? {};
  const num = (s: string): number | null => (s.trim() === "" || isNaN(Number(s)) ? null : Number(s));

  async function save(verify: boolean) {
    setSaving(true); setErr(null);
    try {
      const updated = await updateLibraryItem(item.thread_id, {
        price_amount: num(f.price_amount), price_currency: f.price_currency.trim() || null,
        cost_amount: num(f.cost_amount), cost_currency: f.cost_currency.trim() || null,
        duration_months: num(f.duration_months),
        milestones: ms.filter((m) => m.name.trim()), manpower: mp.filter((m) => m.role.trim()),
        solution_type: f.solution_type.trim() || null, industry: f.industry.trim() || null,
        deal_outcome: f.deal_outcome, verify,
      });
      onSaved(updated);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setSaving(false); }
  }

  const field = (label: string, key: keyof typeof f, confKey?: string, placeholder = "", width?: string) => (
    <div style={{ width }}>
      <div className="field-label">{label}{confKey && <ConfChip c={conf[confKey]} />}</div>
      <input className="field" value={f[key] as string} placeholder={placeholder}
        onChange={(e) => setF({ ...f, [key]: e.target.value })} />
    </div>
  );

  return (
    <>
      <button className="btn-ghost" onClick={onBack} style={{ marginBottom: 14, padding: "6px 12px", display: "inline-flex", alignItems: "center", gap: 6 }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        Proposal Library
      </button>

      <div className="card" style={{ padding: "24px 28px", marginBottom: 22 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
          <div className="num" style={{ fontSize: 24, fontWeight: 800 }}>{item.ticket_no}</div>
          <span className="pill" style={{ background: item.verify_status === "verified" ? "var(--green-soft)" : "var(--amber-soft)", color: item.verify_status === "verified" ? "var(--green)" : "var(--amber)" }}>
            {item.verify_status === "verified" ? "Verified" : "Pending verify"}
          </span>
          {!!item.content_stale && <span className="pill" style={{ background: "var(--orange-soft)", color: "var(--orange)" }}>New version — review needed</span>}
          <SyncBadge status={item.sync_status} />
          <div style={{ flex: 1 }} />
          {item.file_url && (
            <a href={item.file_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--primary)", fontWeight: 700, fontSize: 13.5, textDecoration: "none" }}>Open file ↗</a>
          )}
          {item.sharepoint_url && (
            <a href={item.sharepoint_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--primary)", fontWeight: 700, fontSize: 13.5, textDecoration: "none" }}>SharePoint ↗</a>
          )}
        </div>
        <div style={{ fontSize: 15 }}><span style={{ color: "var(--text-2)" }}>Client:</span> <b>{item.client_name || "-"}</b> <span style={{ color: "var(--text-3)", margin: "0 8px" }}>·</span> <span style={{ color: "var(--text-2)" }}>Project:</span> <b>{item.project_name || "-"}</b></div>
        {item.verify_status === "verified" && <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 4 }}>Verified by {item.verified_by} · {item.verified_at}</div>}
      </div>

      <div className="card card-pad" style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Commercial & Schedule</div>
        <div className="grid grid-price grid-tight" style={{ marginBottom: 14 }}>
          {field("Price (proposed value)", "price_amount", "price", "e.g. 12500000")}
          {field("Currency", "price_currency", undefined, "THB")}
          {field("Cost (internal)", "cost_amount", "cost", "leave blank if unknown")}
          {field("Currency", "cost_currency", undefined, "THB")}
        </div>
        <div className="grid grid-4 grid-tight">
          {field("Duration (months)", "duration_months", "duration", "e.g. 8")}
          {field("Solution Type", "solution_type", "solution_type", "e.g. ERP Implementation")}
          {field("Industry", "industry", "industry", "e.g. Automotive")}
          <div>
            <div className="field-label">Deal Outcome</div>
            <div style={{ display: "flex", gap: 6 }}>
              {(["Won", "Lost", "Pending"] as DealOutcome[]).map((o) => (
                <button key={o} onClick={() => setF({ ...f, deal_outcome: o })}
                  style={{ flex: 1, padding: "9px 4px", borderRadius: 9, cursor: "pointer", fontSize: 13, fontWeight: 700,
                    border: "1px solid " + (f.deal_outcome === o ? OUTCOME_COLOR[o] : "var(--border-strong)"),
                    background: f.deal_outcome === o ? "var(--surface-2)" : "var(--surface)",
                    color: f.deal_outcome === o ? OUTCOME_COLOR[o] : "var(--text-2)" }}>{o}</button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-2" style={{ marginBottom: 22 }}>
        <div className="card card-pad">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Milestones<ConfChip c={conf["milestones"]} /></div>
          {ms.map((m, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input className="field" style={{ flex: 2 }} value={m.name} placeholder="Milestone"
                onChange={(e) => setMs(ms.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <input className="field" style={{ flex: 1 }} value={m.timeframe} placeholder="Month 3 / Q2"
                onChange={(e) => setMs(ms.map((x, j) => (j === i ? { ...x, timeframe: e.target.value } : x)))} />
              <button className="btn-ghost" style={{ padding: "4px 10px" }} aria-label={`ลบ milestone แถวที่ ${i + 1}`}
                onClick={() => setMs(ms.filter((_, j) => j !== i))}>✕</button>
            </div>
          ))}
          <button className="btn-ghost" style={{ padding: "6px 12px" }} onClick={() => setMs([...ms, { name: "", timeframe: "" }])}>+ Add milestone</button>
        </div>
        <div className="card card-pad">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>Manpower<ConfChip c={conf["manpower"]} /></div>
          {mp.map((m, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input className="field" style={{ flex: 2 }} value={m.role} placeholder="Role"
                onChange={(e) => setMp(mp.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))} />
              <input className="field" style={{ flex: 1 }} value={m.count ?? ""} placeholder="Count" type="number"
                onChange={(e) => setMp(mp.map((x, j) => (j === i ? { ...x, count: e.target.value === "" ? null : Number(e.target.value) } : x)))} />
              <input className="field" style={{ flex: 1 }} value={m.man_days ?? ""} placeholder="Man-days" type="number"
                onChange={(e) => setMp(mp.map((x, j) => (j === i ? { ...x, man_days: e.target.value === "" ? null : Number(e.target.value) } : x)))} />
              <button className="btn-ghost" style={{ padding: "4px 10px" }} aria-label={`ลบ manpower แถวที่ ${i + 1}`}
                onClick={() => setMp(mp.filter((_, j) => j !== i))}>✕</button>
            </div>
          ))}
          <button className="btn-ghost" style={{ padding: "6px 12px" }} onClick={() => setMp([...mp, { role: "", count: null, man_days: null }])}>+ Add row</button>
        </div>
      </div>

      {err && <p style={{ color: "var(--red)" }}>Error: {err}</p>}
      <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginBottom: 22 }}>
        <button className="btn-ghost" onClick={() => save(false)} disabled={saving}>{saving ? "กำลังบันทึก…" : "บันทึก"}</button>
        <button className="btn" onClick={() => save(true)} disabled={saving}>{saving ? "กำลังบันทึก…" : "บันทึกและยืนยัน"}</button>
      </div>

      {/* C05 — ใครแก้ราคา/ต้นทุน หรือกด verify ของโปรเจคนี้ไปบ้าง */}
      <AuditTrail threadId={item.thread_id} />
    </>
  );
}

export default LibraryDetail;
