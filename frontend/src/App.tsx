/* Shell ของแอป (H02) — sidebar + topbar + <Outlet/> เท่านั้น
   เดิมไฟล์นี้ยาว 1,967 บรรทัดรวมทุกหน้าไว้ด้วยกัน แก้จุดเดียวเสี่ยงพังทั้งไฟล์ (NFR N8 ≤ 400)
   ตอนนี้แต่ละหน้าอยู่ใน pages/ และถือ state ของตัวเอง; ที่นี่เก็บเฉพาะสิ่งที่ต้องใช้ข้ามหน้า */
import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { getMe, type Me } from "./api/client";
import { AppContext } from "./AppContext";
import { CsiLogo } from "./components/badges";
import { initials } from "./lib/format";

type NavKey = "evaluate" | "proposals" | "library" | "dashboard" | "playbook" | "settings";
/** always:true = เมนูที่ทุกคนเห็นเสมอ ไม่ผูก page permission (คู่มือการใช้งาน) */
const NAV: { key: NavKey; path: string; label: string; icon: JSX.Element; always?: boolean }[] = [
  { key: "proposals", path: "/proposals", label: "Evaluation Results", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M8 6h11M8 12h11M8 18h11"/><circle cx="3.6" cy="6" r="1"/><circle cx="3.6" cy="12" r="1"/><circle cx="3.6" cy="18" r="1"/></svg> },
  { key: "library", path: "/library", label: "Proposal Library", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg> },
  { key: "dashboard", path: "/dashboard", label: "COS Dashboard", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/></svg> },
  { key: "playbook", path: "/playbook", label: "Playbook", always: true, icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2 4.5A2.5 2.5 0 0 1 4.5 2H9a3 3 0 0 1 3 3v15a2.5 2.5 0 0 0-2.5-2.5H2z"/><path d="M22 4.5A2.5 2.5 0 0 0 19.5 2H15a3 3 0 0 0-3 3v15a2.5 2.5 0 0 1 2.5-2.5H22z"/></svg> },
  { key: "settings", path: "/settings", label: "Settings", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></svg> },
];

/** หน้าที่มีช่องค้นหาบนแถบบน (เฉพาะหน้ารายการที่กรองได้จริง) */
const SEARCHABLE = ["/proposals", "/library"];

export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [me, setMe] = useState<Me | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const location = useLocation();

  // ดึงตัวตน + role + สิทธิ์เข้าหน้า (F43). ยังไม่ login -> เด้งไป /login
  // (SWA จัดการ redirect เป็นด่านแรก, นี่คือด่านสำรองกันกรณี token หมดอายุกลาง session)
  //
  // ⚠️ เด้งได้ "ครั้งเดียวต่อ session" เท่านั้น: ถ้า /api/me เรียกไม่ได้ (backend ล่ม /
  // ไม่ได้รัน local) การเด้งไป /login จะโหลดแอปใหม่ -> เรียก /api/me ไม่ได้อีก -> วนไม่จบ
  // (อาการ "หน้าจอกระพริบ"). ครั้งที่สองจึงต้องแสดงข้อความบอกสาเหตุแทนการเด้งซ้ำ
  const LOGIN_TRIED = "pe:login-redirected";
  function goLoginOnce(reason: string) {
    if (sessionStorage.getItem(LOGIN_TRIED)) { setAuthError(reason); return; }
    sessionStorage.setItem(LOGIN_TRIED, "1");
    window.location.href = "/login";
  }

  useEffect(() => {
    let alive = true;
    getMe()
      .then((m) => {
        if (!alive) return;
        if (!m.authenticated) { goLoginOnce("เข้าสู่ระบบไม่สำเร็จ — ลองเข้าสู่ระบบอีกครั้ง"); return; }
        sessionStorage.removeItem(LOGIN_TRIED);   // สำเร็จแล้ว -> รีเซ็ตตัวกัน
        setMe(m);
      })
      .catch((e) => {
        if (!alive) return;
        goLoginOnce(`เชื่อมต่อ API ไม่ได้ — ${e instanceof Error ? e.message : String(e)}`);
      });
    return () => { alive = false; };
  }, []);

  // F04 — คำค้นผูกกับหน้า ไม่ควรค้างข้ามหน้า (เดิมกรองที่ Proposals แล้วสลับไป Library
  // ตัวกรองยังทำงานอยู่เงียบ ๆ ทำให้เหมือนข้อมูลหาย)
  useEffect(() => { setSearch(""); setNavOpen(false); }, [location.pathname]);

  // E02 — ปิดลิ้นชักด้วย Escape (ทางออกด้วยคีย์บอร์ด)
  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setNavOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  const ctx = useMemo(() => ({ me, notice, setNotice, search, setSearch }), [me, notice, search]);
  const visibleNav = NAV.filter((n) => n.always || !me || me.access?.[n.key]);
  const showSearch = SEARCHABLE.some((p) => location.pathname === p);

  // เข้าสู่ระบบ/เรียก API ไม่ได้ -> บอกสาเหตุ + ให้ลองใหม่ได้ (แทนการวนโหลด)
  if (authError) {
    return (
      <div data-theme={theme} style={{ minHeight: "100vh", background: "var(--bg)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
        <div className="card card-pad" style={{ maxWidth: 620, textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>⚠️</div>
          <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>เปิดแอปไม่ได้</div>
          <div className="t2" style={{ fontSize: 14, marginBottom: 14, wordBreak: "break-word" }}>{authError}</div>
          <div className="note" style={{ textAlign: "left", marginBottom: 16 }}>
            <span>
              ถ้ารันในเครื่อง (localhost) ต้องเปิด backend คู่กันด้วย —{" "}
              <code>cd api &amp;&amp; func start</code> แล้วตั้ง <code>AUTH_DEV_MODE=1</code> ใน{" "}
              <code>api/local.settings.json</code>
            </span>
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
            <button className="btn-ghost" onClick={() => { sessionStorage.removeItem(LOGIN_TRIED); window.location.reload(); }}>ลองอีกครั้ง</button>
            <a className="btn" href="/login" style={{ textDecoration: "none" }}>เข้าสู่ระบบ</a>
          </div>
        </div>
      </div>
    );
  }

  return (
    <AppContext.Provider value={ctx}>
      <div data-theme={theme} className="shell">
        {/* ---------- Sidebar (บนจอเล็กกลายเป็นลิ้นชัก) ---------- */}
        <aside className={"sidebar" + (navOpen ? " open" : "")}>
          <div className="brand"><CsiLogo /><div><div className="brand-name">CSI GROUP</div><div className="brand-sub">COS Solution Audit</div></div></div>
          <div style={{ padding: "0 8px 14px", fontSize: 17, fontWeight: 800, color: "#fff", letterSpacing: "-.01em", lineHeight: 1.15 }}>Proposal Audit Agent</div>
          {(!me || me.access?.evaluate) && (
            <Link className="btn-new" to="/evaluate" style={{ marginTop: 40, textDecoration: "none" }}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>New Evaluation
            </Link>
          )}
          <nav className="nav" style={{ marginTop: 20 }}>
            {visibleNav.map((n) => (
              <NavLink key={n.key} to={n.path} end={false}
                className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
                style={{ textDecoration: "none" }}>
                {n.icon}{n.label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-foot">
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: 6 }}>
              <div className="avatar">{initials(me?.name)}</div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ color: "#fff", fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{me?.name ?? "Guest"}</div>
                <div style={{ color: "#8494b0", fontSize: 11.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{me?.email ?? "not signed in"}</div>
              </div>
              {me && (
                <a href="/logout" aria-label="ออกจากระบบ" title="Sign out" style={{ color: "#8494b0", display: "flex", flexShrink: 0 }}>
                  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/></svg>
                </a>
              )}
            </div>
          </div>
        </aside>

        {/* E02 — ฉากหลังของลิ้นชัก (แสดงเฉพาะ <=860px ตาม CSS) */}
        <div className={"scrim" + (navOpen ? " open" : "")} onClick={() => setNavOpen(false)} aria-hidden="true" />

        {/* ---------- Main ---------- */}
        <div className="main">
          <header className="topbar">
            {/* E01 — ปุ่มเปิดเมนูบนจอเล็ก (ซ่อนอัตโนมัติบนเดสก์ท็อป) */}
            <button className="hamburger" onClick={() => setNavOpen((v) => !v)}
              aria-label={navOpen ? "ปิดเมนู" : "เปิดเมนู"} aria-expanded={navOpen}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
                {navOpen ? <path d="M6 6l12 12M18 6L6 18"/> : <path d="M4 7h16M4 12h16M4 17h16"/>}
              </svg>
            </button>
            <Breadcrumb />
            <div style={{ flex: 1 }} />
            {showSearch && (
              <div className="search">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
                <input value={search} onChange={(e) => setSearch(e.target.value)} aria-label="ค้นหา" placeholder="Search ticket, client…"
                  style={{ border: "none", outline: "none", background: "transparent", flex: 1, minWidth: 0, font: "inherit", color: "var(--text)" }} />
                {search && <button onClick={() => setSearch("")} aria-label="ล้างคำค้น" title="Clear" style={{ border: "none", background: "transparent", cursor: "pointer", color: "var(--text-3)", fontSize: 13 }}>✕</button>}
              </div>
            )}
            <button className="icon-btn" onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              aria-label={theme === "light" ? "สลับเป็นธีมมืด" : "สลับเป็นธีมสว่าง"} title="Toggle theme">
              {theme === "light"
                ? <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
                : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/></svg>}
            </button>
            <div className="avatar" style={{ width: 34, height: 34, fontSize: 12.5 }} title={me?.email ?? ""}>{initials(me?.name)}</div>
          </header>

          <main className="content">
            {/* E05 — งานประเมินยังรันอยู่หลังผู้ใช้เปลี่ยนหน้า: บอกให้รู้ ไม่ดึงหน้าจอกลับเอง */}
            {notice && (
              <div className="note" style={{ marginBottom: 18, justifyContent: "space-between" }}>
                <span>{notice}</span>
                <button onClick={() => setNotice(null)} aria-label="ปิดข้อความ"
                  style={{ border: "none", background: "transparent", cursor: "pointer", color: "var(--text-3)", fontSize: 14, flexShrink: 0 }}>✕</button>
              </div>
            )}
            <Outlet />
          </main>
        </div>
      </div>
    </AppContext.Provider>
  );
}

/** เส้นทาง -> breadcrumb (ซ่อนบนจอเล็กตาม CSS เพราะซ้ำกับหัวข้อหน้า) */
function Breadcrumb() {
  const { pathname } = useLocation();
  const parts = pathname.split("/").filter(Boolean);
  const base = NAV.find((n) => n.path === `/${parts[0]}`);
  if (parts[0] === "evaluate") {
    return <span className="crumb">Evaluate <span className="sep">/</span> <b>Upload proposal</b></span>;
  }
  if (base && parts[1]) {
    return <span className="crumb">{base.label} <span className="sep">/</span> <b className="num">{parts[1].slice(0, 8)}…</b></span>;
  }
  return <span className="crumb"><b>{base?.label ?? ""}</b></span>;
}
