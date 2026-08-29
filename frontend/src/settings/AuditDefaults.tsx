/* F46 — ค่าตั้งต้นของการ audit (ภาษา / สกุลเงิน) */
import { useEffect, useState } from "react";
import { getSettings, putSettings, type AppSettings } from "../api/client";

export function AuditDefaults() {
  const [s, setS] = useState<AppSettings>({ default_lang: "th", default_currency: "THB", llm_provider: "azure" });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  // J04 — ดึงเมื่อกางกล่องเท่านั้น
  useEffect(() => { if (show) getSettings().then(setS).catch(() => {}); }, [show]);
  async function save() {
    setSaving(true); setMsg(null);
    try { setS(await putSettings({ default_lang: s.default_lang ?? "th", default_currency: s.default_currency ?? "THB" })); setMsg("บันทึกแล้ว"); }
    catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } finally { setSaving(false); }
  }
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: show ? 12 : 0 }}>
        <span className="sec-title">Audit defaults</span>
        <button className="btn-ghost btn-sm" onClick={() => setShow((v) => !v)}>{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
          <div className="grid grid-2 grid-tight" style={{ maxWidth: 420 }}>
            <div>
              <div className="field-label">Default output language</div>
              <select className="field" value={s.default_lang ?? "th"} onChange={(e) => setS({ ...s, default_lang: e.target.value })}>
                <option value="th">Thai</option><option value="en">English</option>
              </select>
            </div>
            <div>
              <div className="field-label">Default currency</div>
              <input className="field" value={s.default_currency ?? "THB"} onChange={(e) => setS({ ...s, default_currency: e.target.value })} placeholder="THB" />
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 14 }}>
            <button className="btn" onClick={save} disabled={saving}>{saving ? "กำลังบันทึก…" : "บันทึกค่าตั้งต้น"}</button>
            {msg && <span style={{ fontSize: 13, color: "var(--text-2)" }}>{msg}</span>}
          </div>
        </>
      )}
    </div>
  );
}

export default AuditDefaults;
