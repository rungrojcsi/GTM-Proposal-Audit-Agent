/* F17/F26/F27/R8 — หน้าผลประเมินเต็มของโปรเจค (deep link ได้: /proposals/:threadId) */
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  addComment, deleteThread, getThread, updateThread, type EvaluationResult,
} from "../api/client";
import { useApp } from "../AppContext";
import { StatusBadge } from "../components/badges";
import Modal from "../components/Modal";
import PresentationCoach from "../components/PresentationCoach";
import { SortableTh } from "../components/SortableTh";
import { Gauge, Trend } from "../components/charts";
import { Forbidden } from "../components/RouteGuard";
import { scoreVar, TABS, TIER_ORDER, verdictVar, type TabKey } from "../lib/format";
import { SECTION_COLS, SECTION_FIRST_DIR, sortSections, type SectionSortKey } from "../lib/sort";

export default function ProposalDetailPage() {
  const { threadId = "" } = useParams();
  const navigate = useNavigate();
  const { me } = useApp();
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [client, setClient] = useState("");
  const [project, setProject] = useState("");
  const [tab, setTab] = useState<TabKey>("score");
  // เรียงตาราง Section Scores — ค่าเริ่มต้นคือลำดับหัวข้อ 1→17 (เหมือนเดิมก่อนมีปุ่มเรียง)
  const [secKey, setSecKey] = useState<SectionSortKey>("section");
  const [secDir, setSecDir] = useState<"asc" | "desc">("asc");
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState<"" | "evaluate" | "comment">("");
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  /* แถบแท็บเป็น role="tablist" จริง -> เดินด้วยปุ่มลูกศรตามแบบแผน ARIA
     (เดิมเป็นปุ่มเรียง ๆ กัน screen reader ไม่รู้ว่าเป็นแท็บ และผู้ใช้สายตาก็ไม่รู้ว่ากดได้) */
  function onTabKey(e: React.KeyboardEvent<HTMLDivElement>) {
    const i = TABS.findIndex((t) => t.key === tab);
    let n = -1;
    if (e.key === "ArrowRight") n = (i + 1) % TABS.length;
    else if (e.key === "ArrowLeft") n = (i - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = TABS.length - 1;
    else return;
    e.preventDefault();
    const key = TABS[n].key;
    setTab(key);
    document.getElementById(`tab-${key}`)?.focus();
  }

  // H05 — เปิด deep link ที่ไม่มีสิทธิ์: backend ตอบ 403 -> แสดงหน้าอธิบาย ไม่ใช่หน้าขาว
  async function load() {
    setBusy("evaluate"); setError(null);
    try {
      const r = await getThread(threadId);
      setResult(r); setClient(r.client_name ?? ""); setProject(r.project_name ?? ""); setTab("score");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (/สิทธิ|forbidden/i.test(msg)) setForbidden(true); else setError(msg);
    } finally { setBusy(""); }
  }
  useEffect(() => { void load(); /* eslint-disable-next-line */ }, [threadId]);

  const backToList = () => navigate("/proposals");

  async function saveEdit() {
    if (!result || !client.trim() || !project.trim()) return;
    setBusy("evaluate"); setError(null);
    try { await updateThread(result.thread_id, client.trim(), project.trim()); setEditing(false); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  }
  async function doDelete() {
    if (!result) return;
    setConfirmDelete(false);
    setBusy("evaluate"); setError(null);
    try { await deleteThread(result.thread_id); backToList(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  }
  async function onAddComment() {
    if (!result || !comment.trim()) return;
    setBusy("comment");
    try {
      const { comments } = await addComment(result.thread_id, result.submission_id, comment.trim());
      setResult({ ...result, comments }); setComment("");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  }
  const openProposal = (id: string) => navigate(`/proposals/${id}`);

  if (forbidden) return <Forbidden page="โปรเจคนี้" />;
  if (!result) {
    return busy
      ? <div className="state">Loading…</div>
      : <div className="card card-pad" style={{ color: "var(--red)", display: "flex", gap: 12, alignItems: "center" }}>
          <span>Error: {error ?? "ไม่พบโปรเจคนี้"}</span>
          <button className="btn-ghost" onClick={backToList}>กลับรายการ</button>
        </div>;
  }

  // E06 — ทุก version ของ thread นี้ยังไม่เคยประเมินสำเร็จ (ล้มเหลว/กำลังประเมิน):
  // backend คืนแค่ thread meta + history, ไม่มี overall_score/score_details/ฯลฯ เลย
  // ต้องกันไว้ก่อนแตะ field พวกนี้ ไม่งั้นหน้าเปิดไม่ได้ (โดยเฉพาะ Gauge.toFixed() บน undefined)
  const hasScore = result.overall_score != null;
  const latestStatus = result.history[result.history.length - 1]?.status ?? null;

  return (
    <>
      <button className="btn-ghost" onClick={backToList} style={{ marginBottom: 14, padding: "6px 12px", display: "inline-flex", alignItems: "center", gap: 6 }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        กลับรายการทั้งหมด
      </button>
      <div className="card hero-row" style={{ padding: "26px 28px", marginBottom: 22 }}>
        <div className="hero" style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
            <div style={{ width: 40, height: 40, borderRadius: 10, background: "var(--primary-soft)", color: "var(--primary)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M3 10h18M8 7V5h8v2"/></svg>
            </div>
            <div className="num" style={{ fontSize: 26, fontWeight: 800, letterSpacing: "-.01em" }}>{result.ticket_no}</div>
            {hasScore ? (
              <>
                <span className={"pill " + (result.score_source === "reused" ? "pill-reused" : "pill-eval")}>
                  {result.score_source === "reused" ? "Reused score" : "Newly evaluated"}
                </span>
                <span className="pill" style={{ background: "var(--surface-2)", color: "var(--text-2)" }}>{result.lang === "th" ? "TH" : "EN"}</span>
              </>
            ) : <StatusBadge status={latestStatus} />}
          </div>
          {editing ? (
            <div style={{ display: "flex", gap: 8, marginBottom: 6, flexWrap: "wrap", alignItems: "center" }}>
              <input className="field" style={{ flex: 1, minWidth: 140 }} value={client} onChange={(e) => setClient(e.target.value)} placeholder="Client" />
              <input className="field" style={{ flex: 1, minWidth: 140 }} value={project} onChange={(e) => setProject(e.target.value)} placeholder="Project" />
              <button className="btn" style={{ padding: "6px 14px" }} onClick={saveEdit} disabled={busy !== ""}>บันทึก</button>
              <button className="btn-ghost" style={{ padding: "6px 12px" }} onClick={() => { setEditing(false); if (result) openProposal(result.thread_id); }}>ยกเลิก</button>
            </div>
          ) : (
            <div style={{ fontSize: 15, marginBottom: 6, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <span><span style={{ color: "var(--text-2)" }}>Client:</span> <b>{client || "-"}</b> <span style={{ color: "var(--text-3)", margin: "0 8px" }}>·</span> <span style={{ color: "var(--text-2)" }}>Project:</span> <b>{project || "-"}</b></span>
              {me?.access?.manage_proposals && (
                <>
                  <button className="btn-ghost" style={{ padding: "3px 10px", fontSize: 12.5 }} onClick={() => setEditing(true)}>แก้ไข</button>
                  <button className="btn-ghost" style={{ padding: "3px 10px", fontSize: 12.5, color: "var(--red)" }} onClick={() => setConfirmDelete(true)} disabled={busy !== ""}>ลบ</button>
                </>
              )}
            </div>
          )}
          <div style={{ fontSize: 14, color: "var(--text-2)", marginBottom: 16 }}>Version <b style={{ color: "var(--text)" }}>v{result.version_no ?? result.history.length}</b> จาก {result.history.length} เวอร์ชัน{result.model_name && <> · Model: <b style={{ color: "var(--text)" }}>{result.model_name}</b></>}</div>
          {result.gate_note && <div className="note" style={{ width: "fit-content" }}><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="1.9" style={{ flexShrink: 0, marginTop: 1 }}><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.6" r=".7" fill="var(--primary)" stroke="none"/></svg><span>{result.gate_note}</span></div>}
          {result.file_url && (
            <a href={result.file_url} target="_blank" rel="noopener noreferrer" title={result.filename}
              style={{ alignSelf: "center", marginTop: 12, display: "inline-flex", alignItems: "center", gap: 8, padding: "10px 22px", borderRadius: 999, background: "var(--primary-soft)", color: "var(--primary)", fontWeight: 700, fontSize: 14, textDecoration: "none" }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
              Open Latest Proposal
            </a>
          )}
        </div>
        {hasScore
          ? <Gauge score={result.overall_score!} verdict={result.verdict!} />
          : <div style={{ flexShrink: 0, display: "flex", alignItems: "center", paddingLeft: 28, borderLeft: "1px solid var(--border)", color: "var(--text-3)", fontSize: 13.5 }}>ยังไม่มีคะแนน</div>}
      </div>

      <div className="tabs" role="tablist" aria-label="ส่วนของผลประเมิน" onKeyDown={onTabKey}>
        {TABS.map((t) => (
          <button key={t.key} id={`tab-${t.key}`} role="tab" aria-selected={tab === t.key}
            aria-controls="result-tabpanel" tabIndex={tab === t.key ? 0 : -1}
            className={"tab" + (tab === t.key ? " active" : "")} onClick={() => setTab(t.key)}>
            {t.label}{t.key === "comments" && result.comments.length > 0 ? ` (${result.comments.length})` : ""}
          </button>
        ))}
      </div>

      <div id="result-tabpanel" role="tabpanel" aria-labelledby={`tab-${tab}`}>

      {tab === "history" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <div className="card card-pad">
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Score across versions</div>
            <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 12 }}>score 0–10 · single series</div>
            <Trend history={result.history} />
          </div>
          <div className="card clip">
            <table className="tbl"><thead><tr><th>Version</th><th>Score</th><th>Verdict</th><th>Source</th><th>Evaluated</th></tr></thead>
              <tbody>{result.history.map((h, i) => (
                <tr key={i}><td className="num">v{h.version_no}</td><td className="num">{h.overall_score != null ? Number(h.overall_score).toFixed(2) : "-"}</td>
                  <td style={{ color: verdictVar[h.verdict ?? ""] }}>{h.verdict ?? "-"}</td><td>{h.score_source ?? "-"}</td><td style={{ color: "var(--text-2)" }}>{h.evaluated_at ?? "-"}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "score" && !hasScore && (
        <div className="card card-pad" style={{ color: "var(--text-3)" }}>ยังไม่มีคะแนน — โปรเจคนี้ยังไม่เคยประเมินสำเร็จ</div>
      )}
      {tab === "score" && hasScore && (
        <div className="card clip">
          <table className="tbl"><thead><tr>
            {SECTION_COLS.map((c) => (
              <SortableTh key={c.key} label={c.label} active={secKey === c.key} dir={secDir}
                width={c.key === "section" ? "22%" : undefined}
                onSort={() => {
                  if (c.key === secKey) { setSecDir((d) => (d === "asc" ? "desc" : "asc")); return; }
                  setSecKey(c.key); setSecDir(SECTION_FIRST_DIR[c.key]);
                }} />
            ))}
            <th style={{ width: "54%" }}>Coverage</th>
          </tr></thead>
            <tbody>{sortSections(result.score_details ?? [], secKey, secDir).map((d, i) => (
              <tr key={i}>
                <td style={{ fontWeight: 600 }}>{d.slide_section}</td>
                <td><span className={"tier tier-" + d.tier}>{d.tier}</span></td>
                <td style={{ width: 90 }}><span className="num" style={{ fontWeight: 800, color: scoreVar(d.score_1_10) }}>{d.score_1_10}</span><div className="bar"><i style={{ width: `${d.score_1_10 * 10}%`, background: scoreVar(d.score_1_10) }} /></div></td>
                <td style={{ color: "var(--text-2)", fontSize: 13 }}>{d.coverage}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}

      {tab === "recs" && (
        <div className="card card-pad">
          {(result.recommendations ?? []).length === 0 && <div style={{ color: "var(--text-3)" }}>No recommendations</div>}
          {[...(result.recommendations ?? [])].sort((a, b) => (TIER_ORDER[a.priority] ?? 9) - (TIER_ORDER[b.priority] ?? 9)).map((r, i, arr) => (
            <div key={i} style={{ display: "flex", gap: 12, padding: "12px 0", borderBottom: i < arr.length - 1 ? "1px solid var(--border)" : "none" }}>
              <span className={"tier tier-" + r.priority} style={{ height: "fit-content" }}>{r.priority}</span>
              <div><div style={{ fontSize: 14 }}>{r.rec_text}</div>{r.slide_ref && <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 2 }}>{r.slide_ref}</div>}</div>
            </div>
          ))}
        </div>
      )}

      {tab === "skeleton" && (
        <div className="card card-pad"><pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "'IBM Plex Sans Thai', Inter, sans-serif", fontSize: 14, lineHeight: 1.6, color: "var(--text)" }}>{result.skeleton_md || "-"}</pre></div>
      )}

      {tab === "sg" && (
        <div className="grid grid-2">
          <div className="card card-pad"><div style={{ fontSize: 15, fontWeight: 700, color: "var(--green)", marginBottom: 10 }}>Strengths</div><ul style={{ margin: 0, paddingLeft: 18 }}>{(result.strengths ?? []).map((s, i) => <li key={i} style={{ marginBottom: 6 }}>{s}</li>)}{!(result.strengths ?? []).length && <li style={{ color: "var(--text-3)" }}>-</li>}</ul></div>
          <div className="card card-pad"><div style={{ fontSize: 15, fontWeight: 700, color: "var(--orange)", marginBottom: 10 }}>Gaps</div><ul style={{ margin: 0, paddingLeft: 18 }}>{(result.gaps ?? []).map((g, i) => <li key={i} style={{ marginBottom: 6 }}>{g}</li>)}{!(result.gaps ?? []).length && <li style={{ color: "var(--text-3)" }}>-</li>}</ul></div>
        </div>
      )}

      {tab === "comments" && (
        <div className="card card-pad">
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
            {result.comments.map((c, i) => (
              <div key={i} style={{ display: "flex", gap: 10 }}>
                <div className="avatar" style={{ width: 30, height: 30, fontSize: 11, flexShrink: 0 }}>{(c.author || "U").slice(0, 2).toUpperCase()}</div>
                <div><div style={{ fontSize: 13 }}><b>{c.author}</b> <span style={{ color: "var(--text-3)" }}>· {c.created_at}</span></div><div style={{ fontSize: 14, marginTop: 2 }}>{c.comment_text}</div></div>
              </div>
            ))}
            {!result.comments.length && <div style={{ color: "var(--text-3)" }}>No comments yet</div>}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input className="field" style={{ flex: 1 }} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add a comment…" onKeyDown={(e) => e.key === "Enter" && onAddComment()} />
            <button className="btn" onClick={onAddComment} disabled={busy !== "" || !comment.trim()}>ส่งคอมเมนต์</button>
          </div>
        </div>
      )}
      {tab === "coach" && <PresentationCoach threadId={result.thread_id} />}
      </div>

      {confirmDelete && (
        <Modal title="ยืนยันการลบโปรเจค" width={460} onClose={() => setConfirmDelete(false)}>
            <div className="modal-head">
              <div style={{ fontSize: 18, fontWeight: 800, color: "var(--red)" }}>ลบโปรเจคนี้?</div>
              <div style={{ fontSize: 13.5, color: "var(--text-2)", marginTop: 3 }}>การลบไม่สามารถกู้คืนได้</div>
            </div>
            <div className="modal-body">
              <div style={{ fontSize: 14, lineHeight: 1.7 }}>
                <div><span style={{ color: "var(--text-2)" }}>Ticket:</span> <b className="num">{result.ticket_no}</b></div>
                <div><span style={{ color: "var(--text-2)" }}>Client / Project:</span> <b>{client || "-"}</b> / <b>{project || "-"}</b></div>
                <div style={{ marginTop: 8, color: "var(--text-2)" }}>
                  จะลบผลประเมินทั้ง {result.history.length} เวอร์ชัน ข้อมูล Library และคอมเมนต์ทั้งหมดของโปรเจคนี้
                </div>
              </div>
            </div>
            <div className="modal-foot">
              <button className="btn-ghost" onClick={() => setConfirmDelete(false)} disabled={busy !== ""}>ยกเลิก</button>
              <button className="btn" style={{ background: "var(--red)", boxShadow: "none" }}
                onClick={doDelete} disabled={busy !== ""}>{busy !== "" ? "กำลังลบ…" : "ลบถาวร"}</button>
            </div>
        </Modal>
      )}
    </>
  );
}
