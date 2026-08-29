/* R4/G01 — Presentation Coach (งานคิว + poll สถานะ) */
import { useEffect, useRef, useState } from "react";
import { getCoachStatus, startPresentationCoach, type Audience } from "../api/client";
import { AUDIENCES } from "../lib/format";

export function PresentationCoach({ threadId }: { threadId: string }) {
  const [audience, setAudience] = useState<Audience | "custom" | "">("");
  const [customText, setCustomText] = useState("");
  const [guideline, setGuideline] = useState("");
  const [busy, setBusy] = useState(false);
  const [reused, setReused] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // G01 — coach เป็นงานคิวแล้ว: ต้อง poll และต้องยกเลิกได้เมื่อผู้ใช้เปลี่ยน tab/ผู้ฟัง
  const jobRef = useRef<{ cancelled: boolean } | null>(null);
  useEffect(() => () => { if (jobRef.current) jobRef.current.cancelled = true; }, []);

  async function run(label: Audience | "custom", a: Audience | "", custom = "") {
    if (jobRef.current) jobRef.current.cancelled = true;   // ยกเลิกงานก่อนหน้า
    const token = { cancelled: false };
    jobRef.current = token;
    setAudience(label); setBusy(true); setErr(null); setGuideline(""); setReused(false);
    try {
      const started = await startPresentationCoach(threadId, a, custom);
      if (token.cancelled) return;
      if (started.status === "done") {                     // ผลเดิมใช้ซ้ำได้ -> ไม่เรียก LLM
        setGuideline(started.guideline); setReused(!!started.reused); return;
      }
      for (let i = 0; i < 120; i++) {                       // ~6 นาที (3 วิ x 120)
        await new Promise((res) => setTimeout(res, 3000));
        if (token.cancelled) return;
        const st = await getCoachStatus(started.job_id);
        if (token.cancelled) return;
        if (st.status === "Done") { setGuideline(st.guideline); return; }
        if (st.status === "Failed") throw new Error(st.error || "สร้าง guideline ไม่สำเร็จ");
      }
      throw new Error("ใช้เวลานานผิดปกติ — ลองใหม่อีกครั้ง");
    } catch (e) {
      if (!token.cancelled) setErr(e instanceof Error ? e.message : String(e));
    } finally {
      if (!token.cancelled) setBusy(false);
    }
  }
  const gen = (a: Audience) => run(a, a);
  const genCustom = () => { if (customText.trim()) run("custom", "", customText.trim()); };
  return (
    <div className="card card-pad">
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>Presentation Coach</div>
      <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 14 }}>เลือกกลุ่มผู้ฟัง เพื่อรับ guideline การนำเสนอที่เจาะจงระดับผู้ฟัง (อิงเนื้อหา proposal จริง)</div>
      <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
        {AUDIENCES.map((a) => (
          <button key={a.k} onClick={() => gen(a.k)} disabled={busy}
            style={{ padding: "10px 18px", borderRadius: 10, cursor: busy ? "default" : "pointer", fontSize: 14, fontWeight: 700,
              border: "1px solid " + (audience === a.k ? "var(--primary)" : "var(--border-strong)"),
              background: audience === a.k ? "var(--surface-2)" : "var(--surface)",
              color: audience === a.k ? "var(--primary)" : "var(--text-2)" }}>{a.label}</button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input className="field" style={{ flex: 1 }} value={customText} disabled={busy}
          placeholder="หรือพิมพ์กลุ่มผู้ฟังเอง เช่น คณะกรรมการจัดซื้อภาครัฐ, ทีมกฎหมาย…"
          onChange={(e) => setCustomText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && genCustom()} />
        <button className="btn" onClick={genCustom} disabled={busy || !customText.trim()}
          style={audience === "custom" ? { outline: "2px solid var(--primary)" } : undefined}>Generate</button>
      </div>
      {busy && (
        <div style={{ color: "var(--text-3)", padding: "20px 0", textAlign: "center" }}>
          กำลังสร้าง guideline เบื้องหลัง… (อาจใช้เวลา 1–2 นาที · เปลี่ยนกลุ่มผู้ฟังได้เลยถ้าต้องการยกเลิก)
        </div>
      )}
      {err && <div style={{ color: "var(--red)" }}>Error: {err}</div>}
      {reused && guideline && !busy && (
        <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 8 }}>
          ใช้ผลเดิมที่สร้างไว้แล้ว (เนื้อหา proposal และกลุ่มผู้ฟังไม่เปลี่ยน) — ไม่เรียก AI ซ้ำ
        </div>
      )}
      {guideline && !busy && (
        <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "'IBM Plex Sans Thai', Inter, sans-serif", fontSize: 14, lineHeight: 1.6, color: "var(--text)" }}>{guideline}</pre>
      )}
      {!guideline && !busy && !err && <div style={{ color: "var(--text-3)", fontSize: 13 }}>ยังไม่ได้เลือกกลุ่มผู้ฟัง — กดปุ่มด้านบนเพื่อสร้าง guideline</div>}
    </div>
  );
}

export default PresentationCoach;
