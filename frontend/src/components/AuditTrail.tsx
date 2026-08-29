/* C05 — แผงร่องรอยการตรวจสอบ (ใช้ทั้งหน้า Settings และ Library detail) */
import { Fragment, useEffect, useState } from "react";
import { listAudit, type AuditRow } from "../api/client";
import { AUDIT_LABEL } from "../lib/format";

export function AuditTrail({ threadId }: { threadId?: string }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [ready, setReady] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  const [open, setOpen] = useState<string | null>(null);   // แถวที่กางดู before/after

  // C05 — ดึงเมื่อกางกล่องเท่านั้น (ไม่ยิงตอนโหลดหน้า)
  useEffect(() => {
    if (!show || rows) return;
    listAudit({ thread_id: threadId, limit: 100 })
      .then((r) => { setReady(r.ready); setRows(r.items); })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [show, rows, threadId]);

  return (
    <div className="card clip">
      <div onClick={() => setShow((v) => !v)}
        style={{ padding: "14px 18px", borderBottom: show ? "1px solid var(--border)" : "none", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}>
        <span className="sec-title">
          Audit Trail
          <span className="sec-count">
            {threadId ? " — ประวัติการแก้ของโปรเจคนี้" : " — ใคร/เมื่อไร/แก้อะไร"}
          </span>
        </span>
        <button className="btn-ghost btn-sm">{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
          {err && <div style={{ padding: "10px 18px", color: "var(--red)" }}>Error: {err}</div>}
          {!ready && (
            <div style={{ padding: "18px", fontSize: 13.5, color: "var(--amber)" }}>
              ยังไม่ได้สร้างตาราง audit — รัน <b>sql/migration_audit_log.sql</b> ก่อน
            </div>
          )}
          {ready && rows === null && <div style={{ padding: 18, color: "var(--text-3)" }}>Loading…</div>}
          {ready && rows?.length === 0 && <div style={{ padding: 18, color: "var(--text-3)", fontSize: 13.5 }}>ยังไม่มีประวัติการแก้</div>}
          {ready && !!rows?.length && (
            <table className="tbl">
              <thead><tr><th>เวลา</th><th>ผู้ทำ</th><th>การกระทำ</th><th>เป้าหมาย</th><th>IP</th><th></th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.audit_id}>
                    <tr>
                      <td style={{ color: "var(--text-2)", whiteSpace: "nowrap" }}>{String(r.occurred_at).slice(0, 19).replace("T", " ")}</td>
                      <td>{r.actor_email || "-"}<div style={{ fontSize: 11, color: "var(--text-3)" }}>{r.actor_role || ""}</div></td>
                      <td style={{ fontWeight: 600 }}>{AUDIT_LABEL[r.action] ?? r.action}</td>
                      <td className="num">{r.target_label || r.target_id || "-"}</td>
                      <td className="num" style={{ color: "var(--text-3)", fontSize: 12.5 }}>{r.actor_ip || "-"}</td>
                      <td style={{ textAlign: "right" }}>
                        {(r.before_json || r.after_json) && (
                          <button className="btn-ghost" style={{ padding: "3px 10px", fontSize: 12 }}
                            onClick={() => setOpen(open === r.audit_id ? null : r.audit_id)}>
                            {open === r.audit_id ? "ซ่อน" : "ดูค่า"}
                          </button>
                        )}
                      </td>
                    </tr>
                    {open === r.audit_id && (
                      <tr>
                        <td colSpan={6} style={{ background: "var(--surface-2)" }}>
                          <div className="grid grid-2 grid-tight">
                            <div>
                              <div className="field-label">ค่าเดิม</div>
                              <pre style={{ margin: 0, fontSize: 11.5, whiteSpace: "pre-wrap", wordBreak: "break-all", color: "var(--text-2)" }}>{r.before_json || "—"}</pre>
                            </div>
                            <div>
                              <div className="field-label">ค่าใหม่</div>
                              <pre style={{ margin: 0, fontSize: 11.5, whiteSpace: "pre-wrap", wordBreak: "break-all", color: "var(--text-2)" }}>{r.after_json || "—"}</pre>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

export default AuditTrail;
