/* R3 — matrix สิทธิ์ (role x page) แบบยืดหยุ่น */
import { useEffect, useState } from "react";
import { createRole, deleteRole, getRoles, initRbac, setRolePermissions, type RoleRow } from "../api/client";
import { PAGE_LABEL } from "../lib/format";

export function RolesPermissions() {
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [pages, setPages] = useState<string[]>([]);
  const [newRole, setNewRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notInit, setNotInit] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [show, setShow] = useState(false);

  function apply(r: { roles: RoleRow[]; pages: string[] }) { setRoles(r.roles); setPages(r.pages); }
  useEffect(() => {
    if (!show) return;   // J04 — ดึงเมื่อกางกล่องเท่านั้น
    getRoles().then((r) => { apply(r); setNotInit(r.roles.length === 0); })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoaded(true));
  }, [show]);

  async function run(fn: () => Promise<{ roles: RoleRow[]; pages: string[] }>) {
    setBusy(true); setErr(null);
    try { apply(await fn()); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const togglePerm = (role: RoleRow, page: string) =>
    run(() => setRolePermissions(role.role_id, { ...role.permissions, [page]: !role.permissions[page] }));
  const delRole = (role: RoleRow) => run(() => deleteRole(role.role_id));
  const addRole = () => { if (newRole.trim()) run(async () => { const r = await createRole(newRole.trim()); setNewRole(""); return r; }); };
  async function doInit() {
    setBusy(true); setErr(null);
    try { await initRbac(); apply(await getRoles()); setNotInit(false); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="card clip">
      <div onClick={() => setShow((v) => !v)}
        style={{ padding: "14px 18px", borderBottom: show ? "1px solid var(--border)" : "none", display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}>
        <span className="sec-title">Roles &amp; Permissions<span className="sec-count"> — กำหนดว่าแต่ละ role เห็นเมนูหน้าไหนได้</span></span>
        <button className="btn-ghost btn-sm">{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
      {err && <div style={{ padding: "10px 18px", color: "var(--red)" }}>Error: {err}</div>}
      {!loaded ? (
        <div style={{ padding: "18px", color: "var(--text-3)" }}>Loading…</div>
      ) : notInit ? (
        <div style={{ padding: "18px" }}>
          <div style={{ fontSize: 13.5, color: "var(--text-2)", marginBottom: 12 }}>ยังไม่ได้ตั้งค่า RBAC — กดเพื่อสร้างตาราง role + ค่าเริ่มต้น (ทำครั้งเดียว)</div>
          <button className="btn" onClick={doInit} disabled={busy}>{busy ? "กำลังตั้งค่า…" : "ตั้งค่า RBAC"}</button>
        </div>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Role</th>
                  {pages.map((p) => <th key={p} style={{ textAlign: "center", whiteSpace: "nowrap" }}>{PAGE_LABEL[p] ?? p}</th>)}
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {roles.map((role) => (
                  <tr key={role.role_id}>
                    <td style={{ fontWeight: 600 }}>
                      {role.name}{role.is_system && <span style={{ color: "var(--text-3)", fontWeight: 400, fontSize: 11 }}> (system)</span>}
                      <div style={{ fontSize: 11, color: "var(--text-3)" }}>{role.user_count} users</div>
                    </td>
                    {pages.map((p) => (
                      <td key={p} style={{ textAlign: "center" }}>
                        <input type="checkbox" checked={!!role.permissions[p]} disabled={busy}
                          onChange={() => togglePerm(role, p)} style={{ cursor: "pointer", width: 16, height: 16 }} />
                      </td>
                    ))}
                    <td style={{ textAlign: "right" }}>
                      {!role.is_system && (
                        <button className="btn-ghost" style={{ padding: "4px 10px" }} disabled={busy || role.user_count > 0}
                          title={role.user_count > 0 ? "มี user ใช้อยู่ ย้าย role ก่อนลบ" : "ลบ role"} onClick={() => delRole(role)}>ลบ</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", gap: 8, padding: "14px 18px", borderTop: "1px solid var(--border)" }}>
            <input className="field" style={{ flex: 1 }} value={newRole} placeholder="เพิ่ม role ใหม่ (เช่น auditor)"
              onChange={(e) => setNewRole(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addRole()} />
            <button className="btn" onClick={addRole} disabled={busy || !newRole.trim()}>เพิ่ม role</button>
          </div>
        </>
      )}
        </>
      )}
    </div>
  );
}

export default RolesPermissions;
