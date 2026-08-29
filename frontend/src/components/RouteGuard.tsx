/* H04/H05 — ป้องกันเส้นทางด้วยสิทธิ์จาก /api/me และรองรับการเปิด deep link ที่ไม่มีสิทธิ์

   เดิมซ่อนแค่เมนู -> พิมพ์ URL ตรงก็เข้าได้ (backend ปฏิเสธ แต่หน้าจอขึ้นหน้าขาว).
   ตอนนี้เช็กที่ router ด้วย และถ้าไม่มีสิทธิ์จะบอกเหตุผล + ทางออกที่กดได้ */
import { Link } from "react-router-dom";
import type { PageKey } from "../api/client";
import { useApp } from "../AppContext";

export function Forbidden({ page }: { page?: string }) {
  const { me } = useApp();
  const first = (["evaluate", "proposals", "library", "dashboard", "settings"] as PageKey[])
    .find((p) => me?.access?.[p]);
  return (
    <div className="card card-pad" style={{ maxWidth: 560, margin: "40px auto", textAlign: "center" }}>
      <div style={{ fontSize: 40, marginBottom: 8 }}>🔒</div>
      <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>ไม่มีสิทธิ์เข้าถึงหน้านี้</div>
      <div style={{ color: "var(--text-2)", fontSize: 14, marginBottom: 18 }}>
        role ของคุณ ({me?.role ?? "-"}) ยังไม่ได้รับสิทธิ์{page ? ` "${page}"` : ""} — ติดต่อผู้ดูแลระบบเพื่อขอเปิดสิทธิ์
      </div>
      <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
        {first && <Link className="btn" to={`/${first}`} style={{ textDecoration: "none" }}>กลับหน้าที่เข้าได้</Link>}
        {/* Playbook เปิดให้ทุกคน -> มีทางออกให้เสมอ แม้ role นั้นยังไม่ได้สิทธิ์หน้าไหนเลย */}
        <Link className="btn-ghost" to="/playbook" style={{ textDecoration: "none" }}>เปิดคู่มือการใช้งาน</Link>
      </div>
    </div>
  );
}

export default function RouteGuard({ page, label, children }: { page: PageKey; label?: string; children: React.ReactNode }) {
  const { me } = useApp();
  if (!me) return <div className="state">Loading…</div>;
  if (!me.access?.[page]) return <Forbidden page={label ?? page} />;
  return <>{children}</>;
}
