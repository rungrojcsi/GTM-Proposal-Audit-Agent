/* F44 — จัดการผู้ใช้ + role */
import { useEffect, useMemo, useState } from "react";
import { addUser, getRoles, listUsers, setUserRole, type AppUser, type Role } from "../api/client";
import { SortableTh } from "../components/SortableTh";
import { ROLE_LABEL } from "../lib/format";

type UserSortKey = "display_name" | "email" | "role";
const USER_COLS: { key: UserSortKey; label: string }[] = [
  { key: "display_name", label: "User" },
  { key: "email", label: "Email" },
  { key: "role", label: "Role" },
];

export function UserManagement({ myEmail }: { myEmail: string | null }) {
  const [users, setUsers] = useState<AppUser[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<Role>("user");
  const [adding, setAdding] = useState(false);
  const [roleNames, setRoleNames] = useState<string[]>([]);
  const [show, setShow] = useState(false); // default ซ่อนรายละเอียด users
  const [sortKey, setSortKey] = useState<UserSortKey>("role");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  // role ที่ถูกซ่อน — ว่าง = แสดงทุก role (ค่าเริ่มต้น)
  const [hiddenRoles, setHiddenRoles] = useState<string[]>([]);
  // J04 — ดึงเมื่อกางกล่องเท่านั้น (เดิมยิง 2 request ทันทีที่เปิดหน้า Settings)
  useEffect(() => { if (show) listUsers().then(setUsers).catch((e) => setErr(e instanceof Error ? e.message : String(e))); }, [show]);
  useEffect(() => { if (show) getRoles().then((r) => setRoleNames(r.roles.map((x) => x.name))).catch(() => {}); }, [show]);
  async function change(userId: string, role: Role) {
    setBusyId(userId); setErr(null);
    try { const r = await setUserRole(userId, role); setUsers(r.users); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusyId(null); }
  }
  async function add() {
    if (!newEmail.includes("@")) { setErr("email ไม่ถูกต้อง"); return; }
    setAdding(true); setErr(null);
    try { const r = await addUser(newEmail.trim(), newRole); setUsers(r.users); setNewEmail(""); setNewRole("user"); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setAdding(false); }
  }

  function toggleSort(k: UserSortKey) {
    if (k === sortKey) { setSortDir((d) => (d === "asc" ? "desc" : "asc")); return; }
    setSortKey(k); setSortDir("asc");
  }

  /** role ที่ต้องมีปุ่ม = role ที่นิยามไว้ + role ที่ผู้ใช้ถืออยู่จริง (เผื่อ role ถูกลบไปแล้วแต่ยังมีคนถือ) */
  const roleChips = useMemo(() => {
    const seen = new Set<string>([...roleNames, ...users.map((u) => u.role)]);
    return [...seen].map((r) => ({ role: r, count: users.filter((u) => u.role === r).length }));
  }, [roleNames, users]);

  const visible = useMemo(() => {
    const rows = users.filter((u) => !hiddenRoles.includes(u.role));
    const sign = sortDir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const as = String(a[sortKey] ?? "").toLowerCase();
      const bs = String(b[sortKey] ?? "").toLowerCase();
      return (as < bs ? -1 : as > bs ? 1 : 0) * sign;
    });
  }, [users, hiddenRoles, sortKey, sortDir]);

  return (
    <div className="card clip">
      <div style={{ padding: "14px 18px", borderBottom: show ? "1px solid var(--border)" : "none", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="sec-title">User Management <span className="sec-count">({hiddenRoles.length ? `${visible.length}/${users.length}` : users.length})</span></span>
        <button className="btn-ghost btn-sm" onClick={() => setShow((s) => !s)}>{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
          {err && <div style={{ padding: "10px 18px", color: "var(--red)" }}>Error: {err}</div>}
          <div style={{ display: "flex", gap: 8, padding: "14px 18px", borderBottom: "1px solid var(--border)", flexWrap: "wrap", alignItems: "center" }}>
            <input className="field" style={{ flex: 2, minWidth: 220 }} value={newEmail} placeholder="เพิ่ม user ด้วย email (เช่น carlos@example.com)"
              onChange={(e) => setNewEmail(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
            <select className="field" style={{ width: 160 }} value={newRole} onChange={(e) => setNewRole(e.target.value as Role)}>
              {roleNames.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
            </select>
            <button className="btn" onClick={add} disabled={adding || !newEmail.includes("@")}>{adding ? "กำลังเพิ่ม…" : "เพิ่มผู้ใช้"}</button>
          </div>
          {/* ปุ่มซ่อน/แสดงผู้ใช้แยกตาม role — กดที่ชิปเพื่อพับ role นั้นออกจากตาราง */}
          <div style={{ display: "flex", gap: 8, padding: "12px 18px", borderBottom: "1px solid var(--border)", flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>แสดง role:</span>
            {roleChips.map(({ role, count }) => {
              const on = !hiddenRoles.includes(role);
              return (
                <button key={role} aria-pressed={on} title={on ? `ซ่อนผู้ใช้ role ${role}` : `แสดงผู้ใช้ role ${role}`}
                  onClick={() => setHiddenRoles((h) => (on ? [...h, role] : h.filter((x) => x !== role)))}
                  style={{
                    padding: "5px 11px", borderRadius: 999, cursor: "pointer", fontSize: 12.5, fontWeight: 700,
                    border: "1px solid " + (on ? "var(--primary)" : "var(--border-strong)"),
                    background: on ? "var(--primary-soft)" : "var(--surface)",
                    color: on ? "var(--primary)" : "var(--text-3)",
                    textDecoration: on ? "none" : "line-through",
                  }}>
                  {ROLE_LABEL[role] ?? role} ({count})
                </button>
              );
            })}
            {hiddenRoles.length > 0 && (
              <button className="btn-ghost btn-sm" onClick={() => setHiddenRoles([])}>แสดงทั้งหมด</button>
            )}
          </div>
          <table className="tbl">
            <thead><tr>
              {USER_COLS.map((c) => (
                <SortableTh key={c.key} label={c.label} active={sortKey === c.key}
                  dir={sortDir} onSort={() => toggleSort(c.key)} />
              ))}
            </tr></thead>
            <tbody>
              {visible.map((u) => (
                <tr key={u.user_id}>
                  <td style={{ fontWeight: 600 }}>{u.display_name || "-"}{u.email?.toLowerCase() === (myEmail ?? "").toLowerCase() && <span style={{ color: "var(--text-3)", fontWeight: 400 }}> (you)</span>}</td>
                  <td style={{ color: "var(--text-2)" }}>{u.email}</td>
                  <td style={{ width: 180 }}>
                    <select className="field" value={u.role} disabled={busyId === u.user_id} onChange={(e) => change(u.user_id, e.target.value as Role)}>
                      {roleNames.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
              {users.length === 0 && <tr><td colSpan={3} style={{ padding: "24px 18px", color: "var(--text-3)" }}>ยังไม่มี user (จะปรากฏเมื่อมีคน login ผ่าน SSO)</td></tr>}
              {users.length > 0 && visible.length === 0 && <tr><td colSpan={3} style={{ padding: "24px 18px", color: "var(--text-3)" }}>ซ่อนไว้ทุก role — กด “แสดงทั้งหมด” เพื่อดูรายชื่อ</td></tr>}
            </tbody>
          </table>
          <div style={{ padding: "12px 18px", fontSize: 12.5, color: "var(--text-3)", borderTop: "1px solid var(--border)" }}>
            กำหนดสิทธิ์ว่าแต่ละ role เห็นเมนูหน้าไหนได้ ที่ตาราง “Roles &amp; Permissions” ด้านล่าง
          </div>
        </>
      )}
    </div>
  );
}

export default UserManagement;
