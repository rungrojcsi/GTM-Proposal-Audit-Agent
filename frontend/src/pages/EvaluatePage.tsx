/* F03/F22/F24/F25 — อัปโหลด -> ยืนยัน -> ประเมิน (งาน async + poll) */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  evaluate, getSettings, getSubmissionStatus, listProposals, prepare,
  type EvaluationResult, type Lang, type PrepareResult, type ProposalRow,
} from "../api/client";
import { BG_NOTICE, useApp } from "../AppContext";
import Modal from "../components/Modal";
import { evalStep, MAX_UPLOAD_BYTES, mmss, verdictSoft, verdictVar } from "../lib/format";

export default function EvaluatePage() {
  const { setNotice } = useApp();
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [prep, setPrep] = useState<PrepareResult | null>(null);
  const [client, setClient] = useState("");
  const [project, setProject] = useState("");
  const [busy, setBusy] = useState<"" | "prepare" | "evaluate">("");
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<Lang>("th");
  const [activeModel, setActiveModel] = useState("");
  const [projectMode, setProjectMode] = useState<"existing" | "select" | "new">("new");
  const [selectedTid, setSelectedTid] = useState("");
  const [modalProposals, setModalProposals] = useState<ProposalRow[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [evalSec, setEvalSec] = useState(0);

  // กัน browser เปิดไฟล์เมื่อ drop นอก dropzone (default = navigate ไปเปิดไฟล์)
  useEffect(() => {
    const prevent = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", prevent);
    return () => { window.removeEventListener("dragover", prevent); window.removeEventListener("drop", prevent); };
  }, []);

  // E05 — poll แบบยกเลิกได้: ออกจากหน้านี้แล้วต้องไม่ดึงผู้ใช้กลับมาเอง
  const pollRef = useRef<{ cancelled: boolean } | null>(null);
  useEffect(() => () => {
    if (pollRef.current) { pollRef.current.cancelled = true; }
  }, []);

  function cancelPoll(reason?: string) {
    if (!pollRef.current) return;
    pollRef.current.cancelled = true;
    pollRef.current = null;
    setBusy(""); setPrep(null);
    if (reason) setNotice(reason);
  }

  // E04 — ตรวจนามสกุล *และขนาด* ก่อนอัปโหลด (เดิมไฟล์ 30MB อัปโหลดจนเสร็จแล้วเพิ่งได้ 413)
  function pickFile(f: File | null | undefined) {
    if (!f) return;
    if (/\.pptx$/i.test(f.name)) {
      setError("PowerPoint ไม่รองรับแล้ว — ระบบอ่านตัวหนังสือที่อยู่ในรูปของสไลด์ไม่ได้ ทำให้ได้คะแนนต่ำกว่าความเป็นจริง กรุณา Save as PDF แล้วอัปโหลดใหม่");
      return;
    }
    if (!/\.pdf$/i.test(f.name)) { setError("รองรับเฉพาะไฟล์ .pdf"); return; }
    if (f.size > MAX_UPLOAD_BYTES) {
      setError(`ไฟล์ใหญ่เกิน — ${(f.size / 1048576).toFixed(1)} MB (จำกัด ${MAX_UPLOAD_BYTES / 1048576} MB)`);
      return;
    }
    setFile(f); setError(null);
  }

  async function onUpload() {
    if (!file) return;
    setBusy("prepare"); setError(null);
    try {
      const p = await prepare(file);
      setPrep(p); setClient(p.suggested_client); setProject(p.suggested_project);
      setProjectMode(p.existing ? "existing" : "new");
      setSelectedTid(p.existing?.thread_id ?? "");
      listProposals("mine").then(setModalProposals).catch(() => {});
      getSettings().then((s) => setActiveModel(s.active_model || "")).catch(() => {});
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  }

  async function pollEvaluation(submissionId: string, threadId: string, token: { cancelled: boolean }) {
    for (let i = 0; i < 200; i++) {
      await new Promise((res) => setTimeout(res, 3000));
      if (token.cancelled) return;
      setEvalSec((i + 1) * 3);   // E07 — ขยับตัวนับทุกรอบ poll (ทุก 3 วินาที)
      const st = await getSubmissionStatus(submissionId);
      if (token.cancelled) return;
      if (st.status === "Evaluated") {
        pollRef.current = null;
        setPrep(null); setNotice(null);
        navigate(`/proposals/${threadId}`);
        return;
      }
      if (st.status === "Failed") throw new Error("การประเมินล้มเหลว — ลองใหม่อีกครั้ง");
    }
    throw new Error("ประเมินใช้เวลานานผิดปกติ — ดูผลที่หน้า Evaluation Results ภายหลัง");
  }

  async function onConfirm() {
    if (!prep) return;
    let tid: string | undefined; let cn = client; let pn = project;
    if (projectMode === "existing" && prep.existing) {
      tid = prep.existing.thread_id; cn = prep.existing.client_name; pn = prep.existing.project_name;
    } else if (projectMode === "select") {
      if (!selectedTid) { setError("กรุณาเลือกโปรเจคจากรายชื่อ"); return; }
      tid = selectedTid;
      const sp = modalProposals.find((x) => x.thread_id === selectedTid);
      cn = sp?.client_name || client; pn = sp?.project_name || project;
    }
    if (!cn.trim() || !pn.trim()) { setError("ต้องมีชื่อ client และ project"); return; }
    setBusy("evaluate"); setError(null);
    try {
      const r = await evaluate(prep, cn, pn, lang, tid, projectMode === "new");
      if ("status" in r && r.status === "processing") {
        const token = { cancelled: false };
        pollRef.current = token;
        setEvalSec(0);
        await pollEvaluation(r.submission_id, r.thread_id, token);
      } else {
        const done = r as EvaluationResult;
        setPrep(null);
        navigate(`/proposals/${done.thread_id}`);   // cache hit -> ไปหน้าผลทันที
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  }

  return (
    <>
      <div className="h-title">New Proposal Audit</div>
      <div className="h-sub">Upload a PDF — the system auto-detects the client/project name, then asks you to confirm before evaluating.</div>
      <div className="card card-pad" style={{ marginBottom: 22 }}>
        <label className={"dropzone" + (dragOver ? " dragover" : "")} style={{ cursor: "pointer" }}
          onDragOver={(e) => { e.preventDefault(); if (!dragOver) setDragOver(true); }}
          onDragLeave={(e) => { e.preventDefault(); setDragOver(false); }}
          onDrop={(e) => {
            e.preventDefault(); setDragOver(false);
            pickFile(e.dataTransfer.files?.[0]);
          }}>
          <div className="dz-icon"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V7M8.5 10.5 12 7l3.5 3.5"/><path d="M5 18a4 4 0 0 1 .5-8 6 6 0 0 1 11.6 1.5A3.5 3.5 0 0 1 18 18"/></svg></div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>Drag &amp; drop a file here, or <span style={{ color: "var(--primary)" }}>browse</span></div>
          <div style={{ fontSize: 13, color: "var(--text-3)" }}>Supports .pdf only · up to 25 MB</div>
          <input type="file" accept=".pdf,application/pdf" style={{ display: "none" }} onChange={(e) => pickFile(e.target.files?.[0])} />
        </label>
        {file && (
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16 }}>
            <div className="file-chip" style={{ flex: 1 }}>
              <div className="file-badge">{"PDF"}</div>
              <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 14, fontWeight: 600 }}>{file.name}</div><div style={{ fontSize: 12, color: "var(--text-3)" }}>{(file.size / 1048576).toFixed(1)} MB · ready to upload</div></div>
              <button className="btn-ghost" style={{ padding: "4px 10px" }} aria-label="เอาไฟล์ที่เลือกออก"
                onClick={() => setFile(null)}>✕</button>
            </div>
            <button className="btn" onClick={onUpload} disabled={busy !== ""}>
              {busy === "prepare" ? "กำลังอ่านไฟล์…" : "อัปโหลดและตรวจหาชื่อ"}
            </button>
          </div>
        )}
        {error && <p style={{ color: "var(--red)" }}>Error: {error}</p>}
      </div>

      {prep && (
        <Modal title="ยืนยันก่อนประเมิน" onClose={() => (busy === "evaluate" ? cancelPoll(BG_NOTICE) : setPrep(null))}
          closeOnBackdrop={false}>
            <div className="modal-head">
              <div style={{ fontSize: 18, fontWeight: 800 }}>Confirm before evaluating</div>
              <div style={{ fontSize: 13.5, color: "var(--text-2)", marginTop: 3 }}>Detected the following from the file — you can edit before confirming.</div>
            </div>
            <div className="modal-body">
              <div>
                <div className="field-label">โปรเจค</div>
                <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                  {(([["existing", "โปรเจคเดิม (ที่ตรวจพบ)"], ["select", "เลือกจากรายชื่อ"], ["new", "โปรเจคใหม่"]] as [typeof projectMode, string][])
                    .filter(([m]) => m !== "existing" || prep.existing)).map(([m, lbl]) => (
                    <button key={m} onClick={() => setProjectMode(m)}
                      style={{ padding: "8px 14px", borderRadius: 9, cursor: "pointer", fontSize: 13, fontWeight: 700,
                        border: "1px solid " + (projectMode === m ? "var(--primary)" : "var(--border-strong)"),
                        background: projectMode === m ? "var(--primary-soft)" : "var(--surface)",
                        color: projectMode === m ? "var(--primary)" : "var(--text-2)" }}>{lbl}</button>
                  ))}
                </div>
                {projectMode === "existing" && prep.existing && (
                  <div style={{ fontSize: 13.5, color: "var(--text-2)", background: "var(--surface-2)", borderRadius: 9, padding: "10px 14px", lineHeight: 1.6 }}>
                    <b style={{ color: "var(--text)" }}>{prep.existing.client_name}</b> / <b style={{ color: "var(--text)" }}>{prep.existing.project_name}</b><br />
                    {prep.existing.ticket_no} · จะประเมินเป็นเวอร์ชัน v{prep.existing.next_version}
                  </div>
                )}
                {projectMode === "select" && (
                  <select className="field" value={selectedTid} onChange={(e) => setSelectedTid(e.target.value)}>
                    <option value="">— เลือกโปรเจคจากรายชื่อ —</option>
                    {modalProposals.map((pp) => (
                      <option key={pp.thread_id} value={pp.thread_id}>{pp.ticket_no} — {pp.client_name || "?"} / {pp.project_name || "?"}</option>
                    ))}
                  </select>
                )}
                {projectMode === "new" && (
                  <div className="grid grid-2 grid-tight">
                    <div><div className="field-label">Client name {prep.suggested_client && <span className="pill-detected">detected</span>}</div><input className="field" value={client} onChange={(e) => setClient(e.target.value)} placeholder="Client name" /></div>
                    <div><div className="field-label">Project name {prep.suggested_project && <span className="pill-detected">detected</span>}</div><input className="field" value={project} onChange={(e) => setProject(e.target.value)} placeholder="Project name" /></div>
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: 14 }}>
                <div className="tile"><div className="tile-k">Ticket</div><div className="tile-v num">{
                  projectMode === "existing" && prep.existing ? prep.existing.ticket_no
                  : projectMode === "select" ? (modalProposals.find((x) => x.thread_id === selectedTid)?.ticket_no ?? "—")
                  : "New (issued on confirm)"
                }</div></div>
                <div className="tile"><div className="tile-k">Version</div><div className="tile-v">{
                  projectMode === "existing" && prep.existing ? `v${prep.existing.next_version}`
                  : projectMode === "select" ? (selectedTid ? `v${(modalProposals.find((x) => x.thread_id === selectedTid)?.version_no ?? 0) + 1}` : "—")
                  : "v1"
                }</div></div>
                <div className="tile"><div className="tile-k">AI Model</div><div className="tile-v">{activeModel || "—"}</div></div>
              </div>
              <div>
                <div className="field-label">Audit output language</div>
                <div style={{ display: "flex", gap: 8 }}>
                  {(["th", "en"] as Lang[]).map((l) => (
                    <button key={l} onClick={() => setLang(l)}
                      style={{ flex: 1, padding: "9px 12px", borderRadius: 9, cursor: "pointer", fontSize: 14, fontWeight: 600,
                        border: "1px solid " + (lang === l ? "var(--primary)" : "var(--border-strong)"),
                        background: lang === l ? "var(--primary-soft)" : "var(--surface)",
                        color: lang === l ? "var(--primary)" : "var(--text-2)" }}>
                      {l === "th" ? "Thai" : "English"}
                    </button>
                  ))}
                </div>
              </div>
              {projectMode === "existing" && prep.existing && prep.existing.latest_score != null && (
                <div style={{ border: "1px solid var(--border)", borderRadius: 11, padding: "14px 16px", display: "flex", alignItems: "center", gap: 14, background: "var(--surface-2)" }}>
                  <div><div style={{ fontSize: 12, color: "var(--text-2)" }}>Previously submitted — latest score</div>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                      <span className="num" style={{ fontSize: 28, fontWeight: 800, color: verdictVar[prep.existing.latest_verdict ?? ""] }}>{prep.existing.latest_score.toFixed(2)}</span>
                      <span style={{ fontSize: 13, color: "var(--text-3)" }}>/ 10</span>
                      <span style={{ marginLeft: 4, background: verdictSoft[prep.existing.latest_verdict ?? ""], color: verdictVar[prep.existing.latest_verdict ?? ""], padding: "3px 10px", borderRadius: 999, fontSize: 12, fontWeight: 700 }}>{prep.existing.latest_verdict}</span>
                    </div>
                    {prep.existing.evaluated_at && <div style={{ fontSize: 11.5, color: "var(--text-3)", marginTop: 3 }}>ประเมินล่าสุด: {prep.existing.evaluated_at.slice(0, 16).replace("T", " ")}</div>}
                  </div>
                </div>
              )}
              <div className="note"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="1.9" style={{ flexShrink: 0, marginTop: 1 }}><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><circle cx="12" cy="7.6" r=".7" fill="var(--primary)" stroke="none"/></svg>
                <span>{prep.existing ? "If the content is unchanged or the recommendations aren't addressed, the previous score is reused — upload improved content to get a new score." : "New project — a new ticket will be issued and evaluated as version 1."}</span>
              </div>
              {error && <p style={{ color: "var(--red)", margin: 0 }}>Error: {error}</p>}
            </div>
            {busy === "evaluate" && (
              /* E07 — เดิมมีแค่ "อาจใช้เวลาสักครู่" ผู้ใช้แยกไม่ออกว่าค้างหรือยังทำงาน */
              <div style={{ padding: "0 24px 16px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 13, marginBottom: 8 }}>
                  <span style={{ color: "var(--text-2)" }}>⏳ {evalStep(evalSec)}</span>
                  <span className="num" style={{ color: "var(--text-3)", fontVariantNumeric: "tabular-nums" }}>{mmss(evalSec)}</span>
                </div>
                <div className="bar"><i style={{ width: "100%", background: "var(--primary)", opacity: 0.35 }} /></div>
                <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 8 }}>
                  ปิดหน้าต่างนี้ได้ — งานจะทำต่อเบื้องหลัง และผลจะขึ้นที่หน้า Evaluation Results
                </div>
              </div>
            )}
            <div className="modal-foot">
              <button className="btn-ghost" onClick={() => (busy === "evaluate" ? cancelPoll(BG_NOTICE) : setPrep(null))}>{busy === "evaluate" ? "ปิดหน้าต่าง (ประเมินต่อเบื้องหลัง)" : "ยกเลิก"}</button>
              <button className="btn" onClick={onConfirm} disabled={busy !== "" || (projectMode === "new" && (!client.trim() || !project.trim())) || (projectMode === "select" && !selectedTid)}>{busy === "evaluate" ? "กำลังประเมิน…" : "ยืนยันและประเมิน"}</button>
            </div>
        </Modal>
      )}
    </>
  );
}
