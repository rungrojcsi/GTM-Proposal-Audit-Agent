/* F45 — master data (Solution Type / Industry) */
import { useEffect, useState } from "react";
import { addMasterData, deleteMasterData, listMasterData, type MasterDataRow } from "../api/client";

export function MasterList({ category, title }: { category: "solution_type" | "industry"; title: string }) {
  const [rows, setRows] = useState<MasterDataRow[]>([]);
  const [val, setVal] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  // J04 — ดึงเมื่อกางกล่องเท่านั้น
  useEffect(() => { if (show) listMasterData(category).then(setRows).catch((e) => setErr(String(e))); }, [category, show]);
  async function add() {
    if (!val.trim()) return;
    setBusy(true); setErr(null);
    try { const all = await addMasterData(category, val.trim()); setRows(all.filter((r) => r.category === category)); setVal(""); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  async function del(id: string) {
    setBusy(true);
    try { const r = await deleteMasterData(id); setRows(r.items.filter((x) => x.category === category)); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: show ? 12 : 0 }}>
        <span className="sec-title">{title} <span className="sec-count">({rows.length})</span></span>
        <button className="btn-ghost btn-sm" onClick={() => setShow((v) => !v)}>{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
            {rows.map((r) => (
              <span key={r.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, background: "var(--surface-2)", borderRadius: 999, padding: "5px 8px 5px 12px", fontSize: 13 }}>
                {r.value}
                <button className="btn-ghost" style={{ padding: "0 6px", lineHeight: 1 }} onClick={() => del(r.id)} disabled={busy}
                  aria-label={`ลบ ${r.value}`} title="Remove">✕</button>
              </span>
            ))}
            {rows.length === 0 && <span style={{ color: "var(--text-3)", fontSize: 13 }}>ยังไม่มีรายการ</span>}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input className="field" style={{ flex: 1 }} value={val} placeholder={`เพิ่ม ${title}…`} onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
            <button className="btn" onClick={add} disabled={busy || !val.trim()}>เพิ่ม</button>
          </div>
          {err && <p style={{ color: "var(--red)", margin: "8px 0 0" }}>Error: {err}</p>}
        </>
      )}
    </div>
  );
}

export default MasterList;
