/* F42 — COS Dashboard */
import { useEffect, useState } from "react";
import { getDashboard, type Dashboard, type DashActionRow } from "../api/client";
import { DonutVerdict, ScoreWinTrend } from "../components/charts";
import { KpiTile } from "../components/badges";
import { scoreVar, verdictVar } from "../lib/format";

export function DashboardView({ onOpen, onGoLibrary }: { onOpen: (id: string) => void; onGoLibrary: () => void }) {
  const [d, setD] = useState<Dashboard | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    setBusy(true); setErr(null);
    getDashboard()
      .then((r) => { if (alive) setD(r); })
      .catch((e) => { if (alive) setErr(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [reload]);

  if (busy) return <div className="state">Loading…</div>;
  if (err) return <div className="card card-pad" style={{ color: "var(--red)", display: "flex", gap: 12, alignItems: "center" }}><span>Error: {err}</span><button className="btn-ghost" onClick={() => setReload((k) => k + 1)}>Retry</button></div>;
  if (!d) return null;

  const k = d.kpi;
  const pipeline = k.pipeline[0];
  const winPct = k.win_rate != null ? `${(k.win_rate * 100).toFixed(0)}%` : "-";

  const actionTable = (title: string, rows: DashActionRow[], empty: string, tag: (r: DashActionRow) => JSX.Element) => (
    <div className="card clip">
      <div style={{ padding: "14px 18px", fontSize: 15, fontWeight: 700, borderBottom: "1px solid var(--border)" }}>{title} <span style={{ color: "var(--text-3)", fontWeight: 500 }}>({rows.length})</span></div>
      {rows.length === 0
        ? <div style={{ padding: "24px 18px", color: "var(--text-3)", fontSize: 13.5 }}>{empty}</div>
        : <table className="tbl"><tbody>
            {rows.slice(0, 8).map((r) => (
              <tr key={r.thread_id} style={{ cursor: "pointer" }} onClick={() => onOpen(r.thread_id)}>
                <td className="num" style={{ fontWeight: 700, color: "var(--primary)", whiteSpace: "nowrap" }}>{r.ticket_no}</td>
                <td>{r.client_name || "-"}</td>
                <td style={{ textAlign: "right" }}>{tag(r)}</td>
              </tr>
            ))}
          </tbody></table>}
      {rows.length > 8 && <div style={{ padding: "10px 18px", fontSize: 12.5, color: "var(--text-3)" }}>+{rows.length - 8} more · <span style={{ color: "var(--primary)", cursor: "pointer" }} onClick={onGoLibrary}>open Library</span></div>}
    </div>
  );

  return (
    <>
      <div className="h-title">COS Dashboard</div>
      <div className="h-sub">Pipeline health and outstanding work across all evaluated proposals.</div>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 22 }}>
        <KpiTile label="Total Proposals" value={String(k.total_proposals)} />
        <KpiTile label="Avg Score" value={k.avg_score != null ? k.avg_score.toFixed(2) : "-"} sub="latest per project" color={k.avg_score != null ? scoreVar(k.avg_score) : undefined} />
        <KpiTile label="Win Rate" value={winPct} sub={`${k.won} won · ${k.lost} lost · ${k.pending_deals} pending`} color={k.win_rate != null ? (k.win_rate >= 0.5 ? "var(--green)" : "var(--orange)") : undefined} />
        <KpiTile label="Pipeline Value" value={pipeline ? `${pipeline.amount.toLocaleString()}` : "-"} sub={pipeline ? `${pipeline.currency} · pending deals` : "no priced pending deals"} />
        <KpiTile label="Pending Verify" value={String(k.pending_verify)} sub="need review in Library" color={k.pending_verify > 0 ? "var(--amber)" : "var(--green)"} />
      </div>

      <div className="grid grid-2w" style={{ marginBottom: 22 }}>
        <div className="card card-pad">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 14 }}>Verdict breakdown</div>
          <DonutVerdict data={d.verdict_breakdown} />
        </div>
        <div className="card card-pad">
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Score &amp; Win-Rate trend</div>
          <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 6 }}>by month · latest version per project</div>
          <ScoreWinTrend data={d.score_trend} />
        </div>
      </div>

      <div className="grid grid-2">
        {actionTable("Needs attention", d.needs_attention, "All caught up — nothing pending.", (r) => (
          <span style={{ display: "inline-flex", gap: 6, justifyContent: "flex-end", flexWrap: "wrap" }}>
            {r.verify_status === "pending_verify" && <span className="pill" style={{ background: "var(--amber-soft)", color: "var(--amber)" }}>verify</span>}
            {r.content_stale && <span className="pill" style={{ background: "var(--orange-soft)", color: "var(--orange)" }}>stale</span>}
            {r.deal_outcome === "Pending" && <span className="pill" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>outcome?</span>}
          </span>
        ))}
        {actionTable("Low-scoring proposals", d.low_score, "No Weak/Critical proposals.", (r) => (
          <span style={{ display: "inline-flex", gap: 8, alignItems: "center", justifyContent: "flex-end" }}>
            <b className="num" style={{ color: r.overall_score != null ? scoreVar(r.overall_score) : "var(--text-3)" }}>{r.overall_score != null ? r.overall_score.toFixed(2) : "-"}</b>
            <span style={{ color: verdictVar[r.verdict ?? ""] }}>{r.verdict ?? "-"}</span>
          </span>
        ))}
      </div>
    </>
  );
}

export default DashboardView;
