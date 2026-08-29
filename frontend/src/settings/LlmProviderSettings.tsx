/* R2 — สลับ Azure OpenAI / Local LLM + เลือก model */
import { useEffect, useState } from "react";
import { getLlmModels, getSettings, putSettings, type LlmProvider } from "../api/client";

export function LlmProviderSettings() {
  const [provider, setProvider] = useState<LlmProvider>("azure");
  const [selectedModel, setSelectedModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [ready, setReady] = useState(false);        // endpoint local (base_url env) พร้อมไหม
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  const [loaded, setLoaded] = useState(false); // กัน save ก่อนรู้ค่าจริง (ไม่งั้น PUT azure default ทับ)

  useEffect(() => {
    if (!show) return;   // J04 — ดึงเมื่อกางกล่องเท่านั้น
    getSettings().then((s) => {
      setProvider(s.llm_provider ?? "azure");
      setSelectedModel(s.local_llm_model ?? "");
      setReady(!!s.local_llm_ready);
    }).catch((e) => setErr(e instanceof Error ? e.message : String(e))).finally(() => setLoaded(true));
  }, [show]);

  // โหลดรายชื่อ model จาก server เมื่อเลือก Local (ครั้งแรก)
  useEffect(() => {
    if (provider !== "local" || modelsLoaded) return;
    setLoadingModels(true);
    getLlmModels()
      .then((r) => { setReady(r.ready); setModels(r.models); setModelsLoaded(true); })
      .catch(() => {})
      .finally(() => setLoadingModels(false));
  }, [provider, modelsLoaded]);

  async function save() {
    setSaving(true); setMsg(null); setErr(null);
    try {
      const kv: Record<string, string> = { llm_provider: provider };
      if (provider === "local") kv.local_llm_model = selectedModel;
      const s = await putSettings(kv);
      setProvider(s.llm_provider ?? "azure"); setSelectedModel(s.local_llm_model ?? ""); setReady(!!s.local_llm_ready);
      setMsg("บันทึกแล้ว — มีผลทั้งระบบทันที");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setSaving(false); }
  }

  return (
    <div className="card card-pad">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: show ? 14 : 0 }}>
        <span className="sec-title">LLM Provider</span>
        <button className="btn-ghost btn-sm" onClick={() => setShow((v) => !v)}>{show ? "ซ่อน" : "แสดง"}</button>
      </div>
      {show && (
        <>
          <div style={{ fontSize: 12.5, color: "var(--text-3)", marginBottom: 14 }}>เครื่องมือ AI ที่ใช้ประเมิน proposal — สลับแล้วมีผลทั้งระบบทันที (endpoint/token ของ Local ตั้งที่ env ของ Function App)</div>
      <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
        {(["azure", "local"] as LlmProvider[]).map((p) => (
          <button key={p} onClick={() => setProvider(p)} disabled={!loaded}
            style={{ flex: 1, padding: "12px", borderRadius: 10, cursor: loaded ? "pointer" : "default", fontSize: 14, fontWeight: 700, opacity: loaded ? 1 : 0.5,
              border: "1px solid " + (provider === p ? "var(--primary)" : "var(--border-strong)"),
              background: provider === p ? "var(--surface-2)" : "var(--surface)",
              color: provider === p ? "var(--primary)" : "var(--text-2)" }}>
            {p === "azure" ? "Azure OpenAI" : "Local LLM"}
          </button>
        ))}
      </div>
      {provider === "local" && (() => {
        // แสดง selectedModel เสมอแม้โหลด list ใหม่ไม่ได้ (network) -> Boss เห็น/save ค่าที่ตั้งไว้ได้
        const modelOptions = models.length > 0
          ? (selectedModel && !models.includes(selectedModel) ? [selectedModel, ...models] : models)
          : (selectedModel ? [selectedModel] : []);
        return (
          <div style={{ marginBottom: 14 }}>
            {loadingModels ? (
              <div style={{ fontSize: 12.5, color: "var(--text-3)" }}>กำลังโหลดรายการ model จาก server…</div>
            ) : !ready ? (
              <div style={{ fontSize: 12.5, color: "var(--red)" }}>⚠ Local endpoint ไม่พร้อม — ตั้ง env LOCAL_LLM_BASE_URL บน Function App</div>
            ) : modelOptions.length === 0 ? (
              <div style={{ fontSize: 12.5, color: "var(--red)" }}>⚠ โหลดรายการ model ไม่ได้ — Azure ต่อ server ไม่ถึง (ตรวจ firewall)</div>
            ) : (
              <>
                <div className="field-label" style={{ marginBottom: 8 }}>เลือก Model (เลือกได้ตัวเดียว)</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {modelOptions.map((m) => (
                    <button key={m} onClick={() => setSelectedModel(m)}
                      style={{ padding: "8px 14px", borderRadius: 999, cursor: "pointer", fontSize: 13, fontWeight: 700,
                        border: "1px solid " + (selectedModel === m ? "var(--primary)" : "var(--border-strong)"),
                        background: selectedModel === m ? "var(--surface-2)" : "var(--surface)",
                        color: selectedModel === m ? "var(--primary)" : "var(--text-2)" }}>{m}</button>
                  ))}
                </div>
                {models.length === 0 && (
                  <div style={{ fontSize: 12, color: "var(--orange)", marginTop: 8 }}>
                    โหลด list model ใหม่จาก server ไม่ได้ (Azure ต่อไม่ถึง — ตรวจ firewall) · แสดงค่าที่ตั้งไว้เดิม
                  </div>
                )}
              </>
            )}
          </div>
        );
      })()}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button className="btn" onClick={save} disabled={!loaded || saving || (provider === "local" && !selectedModel)}>{saving ? "กำลังบันทึก…" : "บันทึก provider"}</button>
        {msg && <span style={{ fontSize: 13, color: "var(--green)" }}>{msg}</span>}
        {err && <span style={{ fontSize: 13, color: "var(--red)" }}>{err}</span>}
      </div>
        </>
      )}
    </div>
  );
}

export default LlmProviderSettings;
