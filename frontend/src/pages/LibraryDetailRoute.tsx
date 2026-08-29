/* H01 — โหลด Library item จาก URL param แล้วส่งให้ LibraryDetail (deep link: /library/:threadId) */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getLibraryItem, type LibraryItem } from "../api/client";
import { Forbidden } from "../components/RouteGuard";
import LibraryDetail from "./LibraryDetailPage";

export default function LibraryDetailRoute() {
  const { threadId = "" } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<LibraryItem | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    let alive = true;
    setErr(null);
    getLibraryItem(threadId)
      .then((it) => { if (alive) setItem(it); })
      .catch((e) => {
        if (!alive) return;
        const msg = e instanceof Error ? e.message : String(e);
        if (/สิทธิ|forbidden/i.test(msg)) setForbidden(true); else setErr(msg);
      });
    return () => { alive = false; };
  }, [threadId]);

  if (forbidden) return <Forbidden page="Proposal Library" />;
  if (err) {
    return (
      <div className="card card-pad" style={{ color: "var(--red)", display: "flex", gap: 12, alignItems: "center" }}>
        <span>Error: {err}</span>
        <button className="btn-ghost" onClick={() => navigate("/library")}>กลับรายการ</button>
      </div>
    );
  }
  if (!item) return <div className="state">Loading…</div>;
  return <LibraryDetail item={item} onBack={() => navigate("/library")} onSaved={setItem} />;
}
