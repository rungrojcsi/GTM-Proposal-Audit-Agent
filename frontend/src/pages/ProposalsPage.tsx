/* F18/F19 — รายการผลประเมิน (1 แถว/โปรเจค) */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listProposals, type ProposalRow } from "../api/client";
import { useApp } from "../AppContext";
import { StatusBadge } from "../components/badges";
import { SortableTh } from "../components/SortableTh";
import { SCORED_STATUS, scoreVar, verdictVar } from "../lib/format";
import { NUM_DEFAULT_DESC, PROP_COLS, sortProposals, type SortKey } from "../lib/sort";

export default function ProposalsPage() {
  const { me, search } = useApp();
  const navigate = useNavigate();
  const [proposals, setProposals] = useState<ProposalRow[] | null>(null);
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("evaluated_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    let alive = true;
    setListBusy(true); setListError(null);
    listProposals()
      .then((rows) => { if (alive) setProposals(rows); })
      .catch((e) => { if (alive) setListError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (alive) setListBusy(false); });
    return () => { alive = false; };
  }, [reloadKey]);

  function toggleSort(k: SortKey) {
    if (k === sortKey) { setSortDir((d) => (d === "asc" ? "desc" : "asc")); return; }
    setSortKey(k);
    setSortDir(NUM_DEFAULT_DESC.includes(k) ? "desc" : "asc");
  }
  const openProposal = (id: string) => navigate(`/proposals/${id}`);
  const goEvaluate = () => navigate("/evaluate");

  return (
    <>
      <div className="h-title">Evaluation Results</div>
      <div className="h-sub">{me && me.role === "user" ? "Proposals you submitted" : "All evaluated proposals"} — one row per project (ticket). Click a row to open its full audit and version history.</div>
      {listError && <div className="card card-pad" style={{ marginBottom: 16, color: "var(--red)", display: "flex", alignItems: "center", gap: 12 }}><span>Error: {listError}</span><button className="btn-ghost" onClick={() => setReloadKey((k) => k + 1)}>Retry</button></div>}
      {listBusy && <div style={{ color: "var(--text-3)", padding: "40px 0", textAlign: "center" }}>Loading…</div>}
      {!listBusy && proposals && proposals.length === 0 && (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 320, color: "var(--text-3)", textAlign: "center", gap: 8 }}>
          <div style={{ fontSize: 40 }}>📄</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text-2)" }}>No proposals yet</div>
          <div>Upload your first proposal to get started</div>
          <button className="btn" style={{ marginTop: 10 }} onClick={goEvaluate}>New Evaluation</button>
        </div>
      )}
      {!listBusy && proposals && proposals.length > 0 && (() => {
        const q = search.trim().toLowerCase();
        const filtered = !q ? proposals : proposals.filter((p) =>
          [p.ticket_no, p.client_name, p.project_name, p.owner_name].some((v) => (v ?? "").toLowerCase().includes(q)));
        if (filtered.length === 0) return <div style={{ color: "var(--text-3)", padding: "40px 0", textAlign: "center" }}>No proposals match “{search}”</div>;
        return (
        <div className="card clip">
          <table className="tbl">
            <thead><tr>
              {PROP_COLS.map((c) => (
                          <SortableTh key={c.key} label={c.label} active={sortKey === c.key}
                            dir={sortDir} onSort={() => toggleSort(c.key)} />
                        ))}
            </tr></thead>
            <tbody>
              {sortProposals(filtered, sortKey, sortDir).map((p) => (
                <tr key={p.thread_id} style={{ cursor: "pointer" }} onClick={() => openProposal(p.thread_id)}>
                  <td className="num" style={{ fontWeight: 700, color: "var(--primary)" }}>{p.ticket_no}</td>
                  <td>{p.client_name || "-"}</td>
                  <td>{p.project_name || "-"}</td>
                  <td style={{ color: p.owner_name ? undefined : "var(--text-3)" }}>{p.owner_name || "-"}</td>
                  <td className="num">v{p.version_no}</td>
                  <td className="num" style={{ fontWeight: 800, color: p.overall_score != null ? scoreVar(Number(p.overall_score)) : "var(--text-3)" }}>
                    {p.overall_score != null
                      ? Number(p.overall_score).toFixed(2)
                      : !p.status || SCORED_STATUS.has(p.status)
                        ? "-"
                        : <StatusBadge status={p.status} />}
                  </td>
                  <td style={{ color: verdictVar[p.verdict ?? ""] ?? "var(--text-3)" }}>{p.verdict ?? "-"}</td>
                  <td style={{ color: "var(--text-2)" }}>{p.score_source ?? "-"}</td>
                  <td style={{ color: "var(--text-2)" }}>{p.evaluated_at ?? "-"}</td>
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
