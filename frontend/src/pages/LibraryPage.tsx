/* F31 — รายการ Proposal Library */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listLibrary, type DealOutcome, type LibraryRow } from "../api/client";
import { useApp } from "../AppContext";
import { SortableTh } from "../components/SortableTh";
import { fmtMoney, OUTCOME_COLOR, scoreVar } from "../lib/format";
import { LIB_COLS, LIB_NUM_KEYS, sortLibrary, type LibSortKey } from "../lib/sort";

export default function LibraryPage() {
  const { search } = useApp();
  const navigate = useNavigate();
  const [libRows, setLibRows] = useState<LibraryRow[] | null>(null);
  const [libBusy, setLibBusy] = useState(false);
  const [libError, setLibError] = useState<string | null>(null);
  const [libReload, setLibReload] = useState(0);
  const [libOutcome, setLibOutcome] = useState<"all" | DealOutcome>("all");
  const [libVerify, setLibVerify] = useState<"all" | "verified" | "pending_verify">("all");
  const [libSortKey, setLibSortKey] = useState<LibSortKey>("ticket_no");
  const [libSortDir, setLibSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    let alive = true;
    setLibBusy(true); setLibError(null);
    listLibrary()
      .then((rows) => { if (alive) setLibRows(rows); })
      .catch((e) => { if (alive) setLibError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (alive) setLibBusy(false); });
    return () => { alive = false; };
  }, [libReload]);

  function toggleLibSort(k: LibSortKey) {
    if (k === libSortKey) { setLibSortDir((d) => (d === "asc" ? "desc" : "asc")); return; }
    setLibSortKey(k);
    setLibSortDir(LIB_NUM_KEYS.includes(k) ? "desc" : "asc");
  }
  const openLibraryItem = (id: string) => navigate(`/library/${id}`);

  return (
    <>
      <div className="h-title">Proposal Library</div>
      <div className="h-sub">Project content view — price, cost, schedule, manpower per proposal. Click a row to review and edit.</div>
      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
        <select className="field" style={{ width: 150 }} value={libOutcome} onChange={(e) => setLibOutcome(e.target.value as typeof libOutcome)}>
          <option value="all">Outcome: all</option><option value="Won">Won</option><option value="Lost">Lost</option><option value="Pending">Pending</option>
        </select>
        <select className="field" style={{ width: 170 }} value={libVerify} onChange={(e) => setLibVerify(e.target.value as typeof libVerify)}>
          <option value="all">Verify: all</option><option value="verified">Verified</option><option value="pending_verify">Pending verify</option>
        </select>
      </div>
      {libError && <div className="card card-pad" style={{ marginBottom: 16, color: "var(--red)", display: "flex", alignItems: "center", gap: 12 }}><span>Error: {libError}</span><button className="btn-ghost" onClick={() => setLibReload((k) => k + 1)}>Retry</button></div>}
      {libBusy && <div style={{ color: "var(--text-3)", padding: "40px 0", textAlign: "center" }}>Loading…</div>}
      {!libBusy && libRows && (() => {
        const q = search.trim().toLowerCase();
        const rows = libRows.filter((r) => {
          if (libOutcome !== "all" && (r.deal_outcome ?? "Pending") !== libOutcome) return false;
          if (libVerify !== "all" && (r.verify_status ?? "pending_verify") !== libVerify) return false;
          if (!q) return true;
          return [r.ticket_no, r.client_name, r.project_name, r.owner_name, r.solution_type, r.industry]
            .some((v) => (v ?? "").toLowerCase().includes(q));
        });
        if (rows.length === 0) return <div style={{ color: "var(--text-3)", padding: "40px 0", textAlign: "center" }}>No proposals match</div>;
        return (
          <div className="card clip">
            <table className="tbl">
              <thead><tr>
                {LIB_COLS.map((c) => (
                          <SortableTh key={c.key} label={c.label} active={libSortKey === c.key}
                            dir={libSortDir} onSort={() => toggleLibSort(c.key)} />
                        ))}
              </tr></thead>
              <tbody>
                {sortLibrary(rows, libSortKey, libSortDir).map((r) => (
                  <tr key={r.thread_id} style={{ cursor: "pointer" }} onClick={() => openLibraryItem(r.thread_id)}>
                    <td className="num" style={{ fontWeight: 700, color: "var(--primary)" }}>{r.ticket_no}</td>
                    <td>{r.client_name || "-"}</td>
                    <td>{r.project_name || "-"}</td>
                    <td style={{ color: r.owner_name ? undefined : "var(--text-3)" }}>{r.owner_name || "-"}</td>
                    <td>{r.industry || "-"}</td>
                    <td>{r.solution_type || "-"}</td>
                    <td className="num">{fmtMoney(r.price_amount, r.price_currency)}</td>
                    <td className="num">{r.duration_months ?? "-"}</td>
                    <td style={{ color: OUTCOME_COLOR[r.deal_outcome ?? "Pending"], fontWeight: 700 }}>{r.deal_outcome ?? "Pending"}</td>
                    <td>
                      {r.verify_status === "verified"
                        ? <span style={{ color: "var(--green)", fontWeight: 700 }}>✓{r.content_stale ? " (stale)" : ""}</span>
                        : <span style={{ color: "var(--amber)", fontWeight: 600 }}>{r.verify_status ? "pending" : "no data"}</span>}
                    </td>
                    <td className="num" style={{ fontWeight: 800, color: r.overall_score != null ? scoreVar(Number(r.overall_score)) : "var(--text-3)" }}>{r.overall_score != null ? Number(r.overall_score).toFixed(2) : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })()}
    </>
  );
}
