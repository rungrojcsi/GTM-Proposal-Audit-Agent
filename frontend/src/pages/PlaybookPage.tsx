/* หน้า Playbook — คู่มือการใช้งานสำหรับทุก role

   เมนูนี้ตั้งใจ "ไม่" ผ่าน RouteGuard และไม่มี page permission ให้ปิด: คนที่ login
   ครั้งแรกได้ role `user` ต้องหาวิธีใช้งานเองได้ทันที ไม่ต้องรอ admin เปิดสิทธิ์

   ไฟล์จริงเก็บใน Blob (prefix "playbook/") ไม่ได้ฝังไปกับ bundle — PDF+PPTX รวม ~36 MB
   admin เปลี่ยนไฟล์ใหม่ได้จาก Settings › Playbook files โดยไม่ต้อง redeploy

   ⚠️ ข้อความที่ผู้ใช้เห็นในหน้านี้เป็น "ภาษาอังกฤษทั้งหมด" โดยเจตนา (ต่างจากหน้าอื่น):
   หน้านี้เป็นหน้าเดียวที่ทุก role เห็นรวมถึงคนที่เพิ่ง login ครั้งแรก และผู้อ่านมีทั้ง
   ทีมไทยและทีมญี่ปุ่น -> ใช้อังกฤษเป็นภาษากลาง เพิ่มข้อความใหม่ที่นี่ให้ใช้อังกฤษด้วย */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listPlaybook, type PlaybookFile } from "../api/client";
import { useApp } from "../AppContext";
import { fmtBytes } from "../lib/format";

/** นามสกุล -> ป้ายสี + คำกริยาที่ปุ่มควรใช้ (เบราว์เซอร์เปิด PDF/MD ได้เอง ที่เหลือคือดาวน์โหลด) */
const KIND: Record<string, { label: string; color: string; verb: string }> = {
  pdf: { label: "PDF", color: "var(--red)", verb: "Open" },
  pptx: { label: "PPTX", color: "var(--amber)", verb: "Download" },
  docx: { label: "DOCX", color: "var(--primary)", verb: "Download" },
  md: { label: "MD", color: "var(--text-3)", verb: "Open" },
};

function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
}

function fmtDate(s: string): string {
  if (!s) return "";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" });
}

export default function PlaybookPage() {
  const { me } = useApp();
  const [items, setItems] = useState<PlaybookFile[] | null>(null);
  const [ready, setReady] = useState(true);
  const [hint, setHint] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [showGuide, setShowGuide] = useState(false);

  useEffect(() => {
    let alive = true;
    setErr(null);
    listPlaybook()
      .then((r) => { if (!alive) return; setItems(r.items); setReady(r.ready); setHint(r.hint ?? null); })
      .catch((e) => { if (alive) setErr(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [reload]);

  const isAdmin = !!me?.access?.settings;

  return (
    <>
      <div className="h-title">Playbook</div>
      <div className="h-sub">How to use Proposal Audit — for AU / PM / Sales. Open to everyone, no permission needed.</div>

      {err && (
        <div className="card card-pad" style={{ marginBottom: 18, color: "var(--red)", display: "flex", alignItems: "center", gap: 12 }}>
          <span>Error: {err}</span>
          <button className="btn-ghost" onClick={() => setReload((k) => k + 1)}>Retry</button>
        </div>
      )}

      {items === null && !err && <div className="state">Loading…</div>}

      {items !== null && (
        <div className="card card-pad" style={{ marginBottom: 22 }}>
          <div className="sec-title" style={{ marginBottom: 14 }}>
            Playbook files <span className="sec-count">({items.length}) — full documents to download</span>
          </div>

          {!ready && (
            <div className="note" style={{ marginBottom: 14, background: "var(--red-soft)", color: "var(--red)" }}>
              <span>{hint ?? "Cannot read the file store — please contact your administrator."}</span>
            </div>
          )}

          {ready && items.length === 0 && (
            <div className="note" style={{ display: "block", lineHeight: 1.7 }}>
              <b>No playbook files yet</b>
              <div className="t3" style={{ fontSize: 12.5, marginTop: 6 }}>
                {isAdmin
                  ? <>Upload them in <Link to="/settings">Settings › Playbook files</Link></>
                  : "Your administrator hasn't uploaded them yet — please reach the COS team on the support channel."}
              </div>
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {items.map((f) => {
              const k = KIND[extOf(f.name)] ?? { label: extOf(f.name).toUpperCase() || "FILE", color: "var(--text-3)", verb: "Download" };
              return (
                <div key={f.name} style={{
                  display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
                  padding: "12px 14px", borderRadius: 10, background: "var(--surface-2)",
                }}>
                  <span style={{
                    flexShrink: 0, minWidth: 52, textAlign: "center", padding: "5px 8px", borderRadius: 6,
                    fontSize: 11, fontWeight: 800, letterSpacing: ".02em", color: "#fff", background: k.color,
                  }}>{k.label}</span>
                  <div style={{ minWidth: 180, flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, wordBreak: "break-word" }}>{f.name}</div>
                    <div className="t3" style={{ fontSize: 12 }}>
                      {fmtBytes(f.size)}{f.updated_at ? ` · updated ${fmtDate(f.updated_at)}` : ""}
                    </div>
                  </div>
                  {f.url
                    ? <a className="btn" href={f.url} target="_blank" rel="noreferrer" style={{ textDecoration: "none", flexShrink: 0 }}>{k.verb}</a>
                    : <span className="t3" style={{ fontSize: 12.5, color: "var(--red)" }}>Could not create a link — press Retry</span>}
                </div>
              );
            })}
          </div>

          {items.length > 0 && (
            <div className="t3" style={{ fontSize: 11.5, marginTop: 12 }}>
              File links expire after 1 hour — reload this page to get a fresh one. Do not forward these links outside the company.
            </div>
          )}
        </div>
      )}

      {/* สรุปย่อในแอป — ให้คนที่ยังไม่อยากโหลดไฟล์ 16 MB เริ่มใช้งานได้ทันที
          เนื้อหาย่อจาก docs/GTM-ProposalAudit-UserPlaybook.md (ฉบับเต็มอยู่ในไฟล์ด้านบน) */}
      <div className="card card-pad">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: showGuide ? 16 : 0 }}>
          <span className="sec-title">Quick guide<span className="sec-count"> — read it here, no download needed</span></span>
          <button className="btn-ghost btn-sm" onClick={() => setShowGuide((v) => !v)}>{showGuide ? "Hide" : "Show"}</button>
        </div>
        {showGuide && (
          <div style={{ fontSize: 13.5, lineHeight: 1.8 }}>
            <div className="sec-title" style={{ fontSize: 13, marginBottom: 6 }}>Five steps to run an audit</div>
            <ol style={{ margin: "0 0 18px 20px", padding: 0 }}>
              <li>Click <b>New Evaluation</b> and drop your proposal file into the box (PDF up to 25 MB).</li>
              <li>The system reads the file and detects the client and project name — a confirmation dialog opens for you to check and correct them.</li>
              <li>Pick the project mode: existing project / choose from the list / new project — this decides the Ticket number and the version sequence.</li>
              <li>Choose the output language (Thai or English), then confirm.</li>
              <li>Results take 30 seconds to 2 minutes. Keep the page open and do not submit again while you wait.</li>
            </ol>

            <div className="sec-title" style={{ fontSize: 13, marginBottom: 6 }}>How to read the result</div>
            <ul style={{ margin: "0 0 18px 20px", padding: 0 }}>
              <li>Overall score 0–10 plus one of four verdicts: Strong (≥7) · Adequate (≥5) · Weak (≥3.5) · Critical (&lt;3.5)</li>
              <li>Per-section scores across 17 sections, each tagged Critical / Important / Optional</li>
              <li>Strengths &amp; Gaps · Recommendations · a suggested Skeleton outline</li>
              <li>Presentation Coach gives audience-specific guidance · History compares scores across versions</li>
              <li>Every project gets one Ticket number in the form PE-YYYY-NNNNN</li>
            </ul>

            <div className="sec-title" style={{ fontSize: 13, marginBottom: 6 }}>Limits you should know</div>
            <ul style={{ margin: "0 0 18px 20px", padding: 0 }}>
              <li>Scores near a boundary (~5.0 or ~7.0) can cross the line on a re-run — treat the gaps and recommendations as the real substance, not the number.</li>
              <li>Image-only scanned documents may score lower than they deserve, because the system cannot read all the content.</li>
              <li>The audit judges structure and business proposition — not technical accuracy or pricing.</li>
            </ul>

            <div className="sec-title" style={{ fontSize: 13, marginBottom: 6 }}>When to use it in the deal cycle</div>
            <ul style={{ margin: "0 0 0 20px", padding: 0 }}>
              <li>First draft ready → audit it straight away, so gaps surface early.</li>
              <li>At least 3 working days before the client deadline → run the final audit.</li>
              <li>Close Critical-section gaps first — they carry the heaviest weight.</li>
              <li>Before the presentation → use Presentation Coach with the audience that matches who will actually be in the room.</li>
            </ul>
          </div>
        )}
      </div>
    </>
  );
}
