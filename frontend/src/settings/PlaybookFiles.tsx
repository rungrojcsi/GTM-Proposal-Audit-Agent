/* แผงจัดการไฟล์คู่มือ (Playbook) — สิทธิ์ settings เท่านั้น

   เหตุผลที่ต้องมี: ไฟล์คู่มืออยู่ใน Blob ไม่ได้อยู่ใน bundle -> ถ้าไม่มีที่อัปโหลด
   ก็ต้องพึ่ง az CLI ทุกครั้งที่คู่มือมีเวอร์ชันใหม่. ที่นี่แทนที่ไฟล์ได้เลย ไม่ต้อง redeploy */
import { useEffect, useRef, useState } from "react";
import { deletePlaybook, listPlaybook, uploadPlaybook, type PlaybookFile } from "../api/client";
import { fmtBytes } from "../lib/format";

const ACCEPT = ".pdf,.pptx,.docx,.md";

export function PlaybookFiles() {
  const [items, setItems] = useState<PlaybookFile[]>([]);
  const [ready, setReady] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // J04 — ดึงเมื่อกางกล่องเท่านั้น (หน้า Settings มีหลายแผง ไม่ควรยิงทุกตัวพร้อมกัน)
  useEffect(() => {
    if (!show || loaded) return;
    listPlaybook()
      .then((r) => { setItems(r.items); setReady(r.ready); setLoaded(true); })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [show, loaded]);

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await uploadPlaybook(file);
      setItems(r.items); setReady(r.ready);
      setMsg(`อัปโหลดแล้ว: ${file.name}`);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";   // เลือกไฟล์ชื่อเดิมซ้ำได้
    }
  }

  async function del(name: string) {
    if (!window.confirm(`ลบไฟล์ "${name}" ออกจากคู่มือ? ทุกคนจะไม่เห็นไฟล์นี้ในเมนู Playbook`)) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await deletePlaybook(name);
      setItems(r.items); setReady(r.ready);
      setMsg(`ลบแล้ว: ${name}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: show ? 14 : 0 }}>
        <span className="sec-title">
          Playbook files
          <span className="sec-count">{loaded ? ` (${items.length})` : ""} — ไฟล์ที่ทุก role เห็นในเมนู Playbook</span>
        </span>
        <button className="btn-ghost btn-sm" onClick={() => setShow((v) => !v)}>{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
          <div className="t3" style={{ fontSize: 12.5, marginBottom: 14, lineHeight: 1.6 }}>
            ไฟล์ที่อัปโหลดที่นี่จะขึ้นในเมนู <b>Playbook</b> ให้ <b>ทุก role</b> เห็นและเปิดได้ (ไม่มีสิทธิ์ให้ปิด)
            · รองรับ PDF / PPTX / DOCX / MD ไม่เกิน 30 MB · ชื่อไฟล์ซ้ำ = ทับไฟล์เดิม
          </div>

          {!ready && (
            <div className="note" style={{ marginBottom: 14, background: "var(--red-soft)", color: "var(--red)" }}>
              <span>อ่านคลังไฟล์ไม่ได้ — ตรวจ <code>BLOB_CONNECTION_STRING</code> บน Function App</span>
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
            {items.map((f) => (
              <div key={f.name} style={{
                display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
                padding: "9px 12px", borderRadius: 8, background: "var(--surface-2)", fontSize: 13,
              }}>
                <span style={{ flex: 1, minWidth: 160, fontWeight: 600, wordBreak: "break-word" }}>{f.name}</span>
                <span className="t3" style={{ fontSize: 12 }}>{fmtBytes(f.size)}</span>
                {f.url && <a className="btn-ghost btn-sm" href={f.url} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>เปิด</a>}
                <button className="btn-ghost btn-sm" onClick={() => del(f.name)} disabled={busy}
                  style={{ color: "var(--red)" }} aria-label={`ลบ ${f.name}`}>ลบ</button>
              </div>
            ))}
            {loaded && ready && items.length === 0 && (
              <span className="t3" style={{ fontSize: 13 }}>ยังไม่มีไฟล์ — เมนู Playbook จะแสดงเฉพาะสรุปย่อในแอป</span>
            )}
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <input ref={fileRef} type="file" accept={ACCEPT} onChange={onPick} disabled={busy}
              aria-label="เลือกไฟล์คู่มือเพื่ออัปโหลด" style={{ fontSize: 13 }} />
            {busy && <span className="t3" style={{ fontSize: 13 }}>กำลังอัปโหลด…</span>}
            {msg && <span style={{ fontSize: 13, color: "var(--green)" }}>{msg}</span>}
          </div>
          {err && <p style={{ color: "var(--red)", margin: "10px 0 0", fontSize: 13 }}>Error: {err}</p>}
        </>
      )}
    </div>
  );
}

export default PlaybookFiles;
