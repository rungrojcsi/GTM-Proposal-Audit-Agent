/* ตรวจ/สร้างตารางที่ Wave 1/3 ต้องใช้ — แทนการรันไฟล์ .sql ด้วยมือ

   มีเพราะเครื่องที่ deploy มักไม่มี SQL client และ Azure SQL อยู่หลัง Managed Identity
   ใช้แนวเดียวกับปุ่ม "Initialize RBAC" ที่มีอยู่เดิม (idempotent — กดซ้ำได้) */
import { useEffect, useState } from "react";
import { checkDbSchema, runDbMigrate, type DbMigrateResult } from "../api/client";

export function DbSchema() {
  const [r, setR] = useState<DbMigrateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [show, setShow] = useState(false);

  function load() {
    checkDbSchema().then(setR).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }
  useEffect(() => { if (show && !r) load(); }, [show, r]);   // J04 — ดึงเมื่อกางกล่อง

  async function run() {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const out = await runDbMigrate();
      setR(out);
      setMsg(out.created?.length ? `สร้างแล้ว: ${out.created.join(", ")}` : "ไม่มีตารางที่ต้องสร้าง");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  const missing = r?.missing ?? [];
  /* Managed Identity ของ Function App ได้แค่ db_datareader + db_datawriter ตาม deploy.ps1
     ซึ่งไม่รวม CREATE TABLE — กรณีนี้ต้องรัน .sql เองผ่าน Portal จึงบอกวิธีไว้ตรงนี้ */
  const denied = err != null && /permission denied|CREATE TABLE/i.test(err);
  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: show ? 14 : 0 }}>
        <span className="sec-title">
          Database schema
          {r && (
            <span style={{ marginLeft: 8, fontSize: 12, fontWeight: 700, color: missing.length ? "var(--red)" : "var(--green)" }}>
              {missing.length ? `ขาด ${missing.length} ตาราง` : "ครบ"}
            </span>
          )}
        </span>
        <button className="btn-ghost btn-sm" onClick={() => setShow((v) => !v)}>{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
          <div className="t3" style={{ fontSize: 12.5, marginBottom: 14, lineHeight: 1.6 }}>
            ตารางที่เพิ่มมาทีหลัง (<b>AuditLog</b> = ร่องรอยการตรวจสอบ · <b>CoachJobs</b> = คิวงาน Presentation Coach)
            กดสร้างได้จากที่นี่ ไม่ต้องรันไฟล์ .sql เอง · กดซ้ำได้ ไม่กระทบข้อมูลเดิม
          </div>
          {missing.length > 0 && (
            <div className="note" style={{ marginBottom: 14, background: "var(--red-soft)", color: "var(--red)" }}>
              <span>ยังไม่มีตาราง: <b>{missing.join(", ")}</b> — ฟีเจอร์ที่เกี่ยวข้องจะใช้งานไม่ได้จนกว่าจะสร้าง</span>
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <button className="btn" onClick={run} disabled={busy || (r != null && missing.length === 0)}>
              {busy ? "กำลังสร้าง…" : "สร้างตารางที่ขาด"}
            </button>
            <button className="btn-ghost" onClick={() => { setR(null); setMsg(null); setErr(null); }} disabled={busy}>
              ตรวจใหม่
            </button>
            {msg && <span style={{ fontSize: 13, color: "var(--green)" }}>{msg}</span>}
            {err && !denied && <span style={{ fontSize: 13, color: "var(--red)" }}>{err}</span>}
          </div>
          {denied && (
            <div className="note" style={{ marginTop: 14, display: "block", lineHeight: 1.7 }}>
              <b>สร้างจากที่นี่ไม่ได้ — Managed Identity ไม่มีสิทธิ์ CREATE TABLE</b> (ได้แค่ อ่าน/เขียนข้อมูล)
              <div className="t3" style={{ fontSize: 12.5, marginTop: 8 }}>
                รันด้วยมือครั้งเดียวแทน ไม่ต้องติดตั้งอะไร:
                <ol style={{ margin: "6px 0 0 18px", padding: 0 }}>
                  <li>Azure Portal → SQL databases → <b>proposal_evaluator</b> → <b>Query editor</b></li>
                  <li>Login ด้วย Entra ID (บัญชีที่เป็น SQL admin)</li>
                  <li>วางไฟล์ <code>sql/migration_all_pending.sql</code> ทั้งไฟล์ → Run</li>
                  <li>กลับมากด <b>ตรวจใหม่</b> ที่นี่ ต้องขึ้น “ครบ”</li>
                </ol>
              </div>
              <div className="t3" style={{ fontSize: 11.5, marginTop: 8, opacity: 0.85 }}>
                ข้อความจากฐานข้อมูล: {err}
              </div>
            </div>
          )}
          {r?.hint && <div className="t3" style={{ fontSize: 12, marginTop: 10 }}>{r.hint}</div>}
        </>
      )}
    </div>
  );
}

export default DbSchema;
