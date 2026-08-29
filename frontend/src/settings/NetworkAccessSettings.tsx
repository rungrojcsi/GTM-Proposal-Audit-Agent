/* S02 — จำกัดการเข้าถึงตาม IP แทนการพึ่ง VPN (ค่าเริ่มต้นปิด) */
import { useEffect, useState } from "react";
import { getSettings, putSettings } from "../api/client";

export function NetworkAccessSettings() {
  const [enabled, setEnabled] = useState(false);
  const [allowlist, setAllowlist] = useState("");
  const [killSwitch, setKillSwitch] = useState(false);
  const [loaded, setLoaded] = useState(false);   // กัน save ทับก่อนรู้ค่าจริง
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!show) return;   // J04 — ดึงเมื่อกางกล่องเท่านั้น
    getSettings()
      .then((s) => {
        setEnabled(!!s.ip_restriction_enabled);
        setAllowlist(s.ip_allowlist ?? "");
        setKillSwitch(!!s.ip_kill_switch);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoaded(true));
  }, [show]);

  async function save() {
    setSaving(true); setMsg(null); setErr(null);
    try {
      const s = await putSettings({
        ip_restriction_enabled: enabled ? "1" : "0",
        ip_allowlist: allowlist.trim(),
      });
      setEnabled(!!s.ip_restriction_enabled);
      setAllowlist(s.ip_allowlist ?? "");
      setMsg("บันทึกแล้ว — มีผลทันที");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setSaving(false); }
  }

  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: show ? 14 : 0 }}>
        <span className="sec-title">
          Network Access
          <span style={{ marginLeft: 8, fontSize: 12, fontWeight: 700, color: enabled ? "var(--amber)" : "var(--green)" }}>
            {enabled ? "จำกัดตาม IP" : "เปิดสาธารณะ (พึ่ง SSO)"}
          </span>
        </span>
        <button className="btn-ghost btn-sm" onClick={() => setShow((v) => !v)}>{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
          <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 14, lineHeight: 1.6 }}>
            แทนการบังคับให้ผู้ใช้ต่อ VPN — ปิดไว้ = ใครที่ล็อกอินผ่าน SSO และมีสิทธิ์ตาม role
            ก็เข้าได้จากทุกที่ · เปิด = รับเฉพาะ IP ในรายการที่อนุญาต
          </div>
          {killSwitch && (
            <div className="note" style={{ marginBottom: 14, background: "var(--amber-soft)", color: "var(--amber)" }}>
              <span>การตรวจ IP ถูกปิดจาก env <b>IP_RESTRICTION_OFF=1</b> บน Function App — ค่าด้านล่างจะไม่มีผลจนกว่าจะลบ env นี้ออก</span>
            </div>
          )}
          <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
            {([[false, "เปิดสาธารณะ (พึ่ง SSO)"], [true, "จำกัดเฉพาะ IP ที่อนุญาต"]] as [boolean, string][]).map(([v, label]) => (
              <button key={String(v)} onClick={() => setEnabled(v)} disabled={!loaded}
                style={{ flex: 1, padding: 12, borderRadius: 10, cursor: loaded ? "pointer" : "default", fontSize: 14, fontWeight: 700, opacity: loaded ? 1 : 0.5,
                  border: "1px solid " + (enabled === v ? "var(--primary)" : "var(--border-strong)"),
                  background: enabled === v ? "var(--surface-2)" : "var(--surface)",
                  color: enabled === v ? "var(--primary)" : "var(--text-2)" }}>{label}</button>
            ))}
          </div>
          {enabled && (
            <div style={{ marginBottom: 14 }}>
              <div className="field-label">IP / CIDR ที่อนุญาต (คั่นด้วย comma)</div>
              <input className="field" value={allowlist} placeholder="เช่น 203.0.113.0/24, 10.0.0.0/8, 198.51.100.7"
                onChange={(e) => setAllowlist(e.target.value)} />
              <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 6 }}>
                ระบบจะปฏิเสธถ้า IP ที่คุณกำลังใช้ไม่อยู่ในรายการ — กันล็อกตัวเองออก
              </div>
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button className="btn" onClick={save} disabled={!loaded || saving}>{saving ? "กำลังบันทึก…" : "บันทึกการเข้าถึงเครือข่าย"}</button>
            {msg && <span style={{ fontSize: 13, color: "var(--green)" }}>{msg}</span>}
            {err && <span style={{ fontSize: 13, color: "var(--red)" }}>{err}</span>}
          </div>
        </>
      )}
    </div>
  );
}

export default NetworkAccessSettings;
