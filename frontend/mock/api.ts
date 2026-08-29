/* Mock backend สำหรับ "ดูหน้าจอตอน dev" เท่านั้น — ไม่เคยถูกรวมเข้า production bundle
   (ไฟล์นี้ถูกโหลดโดย vite.config.ts ซึ่งรันตอน build/dev ฝั่ง Node ไม่ใช่โค้ดที่ส่งให้ browser)

   เปิดใช้: `npm run dev:mock`  (ตั้ง VITE_MOCK_API=1)
   ปิดใช้: `npm run dev`        (proxy ไป Azure Functions ที่ localhost:7071 ตามปกติ)

   จุดประสงค์: ตรวจ UI/UX ครบทุกหน้าโดยไม่ต้องมี Azure SQL / Document Intelligence / OpenAI
   ข้อมูลเป็นของปลอมทั้งหมด แต่รูปร่าง (shape) ตรงกับ api/shared/models.py + api/client.ts
*/
import type { Connect, Plugin } from "vite";

const SECTIONS: [string, string][] = [
  ["1. Hero Cover", "Important"], ["2. Agenda", "Optional"], ["3. Client Context", "Important"],
  ["4. Pain Statement", "Critical"], ["5. Cost of Inaction", "Important"],
  ["6. Hero Moat (Track Record)", "Critical"], ["7. Solution Architecture", "Critical"],
  ["8. Delivery Narrative (3-Wave)", "Critical"], ["9. Master Schedule", "Critical"],
  ["10. Commercial Summary & TCO", "Important"], ["11. Differentiation Grid", "Optional"],
  ["12. The Ask & Next 30 Days", "Optional"], ["13. Named Team & Organization", "Optional"],
  ["14. Governance Fit", "Important"], ["15. Quality Management & Risk", "Important"],
  ["16. Post Go-Live Support (MA)", "Important"], ["17. Reference Case", "Important"],
];

const T1 = "00000000-0000-0000-0000-000000000000";
const T2 = "00000000-0000-0000-0000-000000000000";
const T3 = "00000000-0000-0000-0000-000000000000";
const T4 = "00000000-0000-0000-0000-000000000000";

/** สร้างผลประเมินปลอมที่ครบทุก field ที่หน้าจอใช้ */
function evaluation(threadId: string, score: number, verdict: string, versions: number) {
  return {
    thread_id: threadId,
    ticket_no: `PE-2026-${threadId.slice(0, 5)}`,
    version_no: versions,
    submission_id: `sub-${threadId}`,
    score_source: "evaluated",
    gate_note: versions > 1 ? "เนื้อหาเปลี่ยนและแก้ตามคำแนะนำ — ประเมินใหม่" : "",
    lang: "th",
    overall_score: score,
    verdict,
    client_name: threadId === T1 ? "Acme Malaysia" : "Thai Summit Group",
    project_name: threadId === T1 ? "ERP Modernization" : "Smart Factory Phase 2",
    filename: "proposal_v" + versions + ".pdf",
    file_url: "",
    model_name: "gpt-4o (mock)",
    score_details: SECTIONS.map(([name, tier], i) => ({
      slide_section: name,
      tier,
      score_1_10: [8, 6, 7, 9, 5, 8, 7, 6, 4, 7, 3, 5, 6, 7, 8, 6, 7][i],
      coverage: i === 10 ? "missing" : "ครอบคลุมพอใช้ — ยังขาดตัวเลขอ้างอิงจากโครงการจริง",
    })),
    recommendations: [
      { priority: "Critical", rec_text: "เพิ่ม Master Schedule ที่ระบุ milestone และผู้รับผิดชอบต่อ wave", slide_ref: "slide 9" },
      { priority: "Critical", rec_text: "อ้างอิง track record โครงการ automotive ที่ปิดจบแล้วอย่างน้อย 2 ราย", slide_ref: "slide 6" },
      { priority: "Important", rec_text: "แยก TCO 3 ปีออกจากราคาติดตั้ง ให้ฝ่ายจัดซื้อเทียบได้", slide_ref: "slide 10" },
      { priority: "Optional", rec_text: "เพิ่มตารางเทียบคู่แข่งแบบ 5 เกณฑ์", slide_ref: "slide 11" },
    ],
    skeleton_md: `# โครงร่างที่แนะนำ\n\n## 1. Hero Cover\nชื่อลูกค้า + ผลลัพธ์เชิงตัวเลขที่จะได้\n\n## 4. Pain Statement\nระบุความเสียหายต่อเดือนเป็นตัวเลข\n\n## 9. Master Schedule\nGantt 3 wave + gate การตรวจรับแต่ละช่วง\n\n## 16. Post Go-Live Support\nSLA + ทีมที่รับผิดชอบหลังส่งมอบ`,
    strengths: [
      "อธิบายสถาปัตยกรรมระบบชัดเจน แยกชั้นข้อมูลกับชั้นแอปได้ดี",
      "มีแผนอบรมผู้ใช้แยกตามกลุ่มงาน",
    ],
    gaps: [
      "ไม่มี Master Schedule ที่ผูกกับผู้รับผิดชอบ",
      "ไม่มีตัวเลขความเสียหายของสถานะปัจจุบัน (cost of inaction)",
      "Differentiation Grid หายไปทั้งหัวข้อ",
    ],
    history: Array.from({ length: versions }, (_, i) => ({
      ticket_no: `PE-2026-${threadId.slice(0, 5)}`,
      version_no: i + 1,
      status: "Evaluated",
      score_source: i === 0 ? "evaluated" : "evaluated",
      overall_score: +(score - (versions - 1 - i) * 0.8).toFixed(2),
      verdict: i === versions - 1 ? verdict : "Adequate",
      evaluated_at: `2026-07-${String(10 + i * 3).padStart(2, "0")}T09:20:00`,
    })),
    comments: [
      { submission_id: null, author: "carlos@example.com", comment_text: "ฝ่ายขายขอให้เน้น TCO มากกว่านี้", created_at: "2026-07-28T14:02:00" },
    ],
  };
}

const PROPOSALS = [
  { thread_id: T1, ticket_no: "PE-2026-00001", client_name: "Acme Malaysia", project_name: "ERP Modernization", owner_name: "Carlos P.", version_no: 3, version_count: 3, status: "Evaluated", overall_score: 7.45, verdict: "Strong", score_source: "evaluated", evaluated_at: "2026-07-28T09:20:00" },
  { thread_id: T2, ticket_no: "PE-2026-00002", client_name: "Thai Summit Group", project_name: "Smart Factory Phase 2", owner_name: "Erin R.", version_no: 2, version_count: 2, status: "Evaluated", overall_score: 5.6, verdict: "Adequate", score_source: "reused", evaluated_at: "2026-07-25T16:40:00" },
  { thread_id: T3, ticket_no: "PE-2026-00003", client_name: "Siam Cement", project_name: "Warehouse Automation", owner_name: "Carlos P.", version_no: 2, version_count: 2, status: "Evaluating", overall_score: null, verdict: null, score_source: null, evaluated_at: null },
  { thread_id: T4, ticket_no: "PE-2026-00004", client_name: "PTT Digital", project_name: "Data Platform", owner_name: null, version_no: 1, version_count: 1, status: "Failed", overall_score: null, verdict: null, score_source: null, evaluated_at: null },
];

const LIBRARY = [
  { thread_id: T1, ticket_no: "PE-2026-00001", client_name: "Acme Malaysia", project_name: "ERP Modernization", owner_name: "Carlos P.", price_amount: 12500000, price_currency: "THB", cost_amount: 8200000, cost_currency: "THB", duration_months: 8, solution_type: "ERP Implementation", industry: "Automotive", deal_outcome: "Won", verify_status: "verified", content_stale: false, sync_status: "pending", updated_at: "2026-07-29T10:00:00", version_no: 3, overall_score: 7.45, verdict: "Strong" },
  { thread_id: T2, ticket_no: "PE-2026-00002", client_name: "Thai Summit Group", project_name: "Smart Factory Phase 2", owner_name: "Erin R.", price_amount: 7800000, price_currency: "THB", cost_amount: null, cost_currency: null, duration_months: 6, solution_type: "IIoT", industry: "Manufacturing", deal_outcome: "Pending", verify_status: "pending_verify", content_stale: true, sync_status: "pending", updated_at: "2026-07-26T11:00:00", version_no: 2, overall_score: 5.6, verdict: "Adequate" },
];

function libraryItem(id: string) {
  const row = LIBRARY.find((r) => r.thread_id === id) ?? LIBRARY[0];
  return {
    ...row,
    milestones: [{ name: "Kick-off + Blueprint", timeframe: "Month 1" }, { name: "UAT", timeframe: "Month 6" }],
    manpower: [{ role: "Project Manager", count: 1, man_days: 120 }, { role: "ABAP Developer", count: 3, man_days: 300 }],
    source: "extracted",
    field_confidence: { price: "high", cost: "low", duration: "medium", milestones: "medium", manpower: "low", solution_type: "high", industry: "high" },
    verified_by: row.verify_status === "verified" ? "manager@example.com" : null,
    verified_at: row.verify_status === "verified" ? "2026-07-29T10:00:00" : null,
    sharepoint_url: null,
    has_content: true,
    filename: "proposal_v3.pdf",
    file_url: "",
  };
}

const AUDIT = [
  { audit_id: "a1", occurred_at: "2026-07-29T10:00:12", actor_email: "manager@example.com", actor_role: "manager", actor_ip: "203.0.113.24", action: "content.verify", target_type: "thread", target_id: T1, target_label: "PE-2026-00001", before_json: '{"verify_status":"pending_verify","price_amount":12000000}', after_json: '{"verify_status":"verified","price_amount":12500000}' },
  { audit_id: "a2", occurred_at: "2026-07-28T09:15:40", actor_email: "admin@example.com", actor_role: "admin", actor_ip: "10.10.4.8", action: "role.perms", target_type: "role", target_id: "r-manager", target_label: "manager", before_json: '{"library":false}', after_json: '{"library":true}' },
  { audit_id: "a3", occurred_at: "2026-07-27T18:31:02", actor_email: "admin@example.com", actor_role: "admin", actor_ip: "10.10.4.8", action: "settings.network", target_type: "settings", target_id: "network", target_label: "ip_restriction", before_json: '{"ip_restriction_enabled":"1"}', after_json: '{"ip_restriction_enabled":"0"}' },
];

/** สถานะงานประเมินปลอม: ตอบ Evaluating 4 รอบ (~12 วิ) แล้วค่อย Evaluated เพื่อดูแถบความคืบหน้า E07 */
const evalTicks = new Map<string, number>();
const coachTicks = new Map<string, number>();

const PLAYBOOK = [
  { name: "ProposalAudit-Playbook-TH.pdf", size: 16592102, content_type: "application/pdf", updated_at: "2026-08-16T23:19:00Z", url: "https://example.invalid/mock-playbook.pdf" },
  { name: "ProposalAudit-Playbook-TH.pptx", size: 19678986, content_type: "application/vnd.openxmlformats-officedocument.presentationml.presentation", updated_at: "2026-08-16T23:19:00Z", url: "https://example.invalid/mock-playbook.pptx" },
];

function route(url: string, method: string, body: any): unknown | undefined {
  const p = url.split("?")[0];
  const seg = p.split("/").filter(Boolean);          // ["api", ...]
  const id = seg[2] ?? "";

  if (p === "/api/health") return { status: "ok" };
  if (p === "/api/me") {
    return {
      user_id: "u-dev", email: "dev.admin@example.com", name: "Dev Admin",
      role: "admin", authenticated: true,
      access: { evaluate: true, proposals: true, library: true, dashboard: true, settings: true, view_all: true, manage_proposals: true },
    };
  }
  if (p === "/api/settings" && method === "GET") {
    return { default_lang: "th", default_currency: "THB", llm_provider: "azure", active_model: "gpt-4o (mock)", local_llm_ready: false, local_llm_model: "", ip_restriction_enabled: false, ip_allowlist: "", ip_kill_switch: false };
  }
  if (p === "/api/settings" && method === "PUT") {
    return { default_lang: body?.default_lang ?? "th", default_currency: body?.default_currency ?? "THB", llm_provider: body?.llm_provider ?? "azure", active_model: "gpt-4o (mock)", local_llm_ready: false, local_llm_model: "", ip_restriction_enabled: body?.ip_restriction_enabled === "1", ip_allowlist: body?.ip_allowlist ?? "", ip_kill_switch: false };
  }
  if (p === "/api/proposals") return PROPOSALS;
  if (p === "/api/library" && method === "GET") return LIBRARY;
  if (p.startsWith("/api/library/") && method === "GET") return libraryItem(id);
  if (p.startsWith("/api/library/") && method === "PATCH") return { ...libraryItem(id), ...body, verify_status: body?.verify ? "verified" : libraryItem(id).verify_status };
  if (p.startsWith("/api/threads/") && seg[3] === "history") {
    const e = evaluation(id, 7.45, "Strong", 3);
    return { thread_id: id, versions: e.history, comments: e.comments };
  }
  if (p.startsWith("/api/threads/") && method === "GET") {
    if (id === T2) return evaluation(T2, 5.6, "Adequate", 2);
    return evaluation(id, 7.45, "Strong", 3);
  }
  if (p.startsWith("/api/threads/") && (method === "PATCH" || method === "DELETE")) return { ok: true };
  if (p === "/api/comments") {
    return { thread_id: body?.thread_id, comments: [
      ...evaluation(body?.thread_id ?? T1, 7.45, "Strong", 3).comments,
      { submission_id: null, author: "dev.admin@example.com", comment_text: body?.comment_text, created_at: new Date().toISOString().slice(0, 19) },
    ] };
  }
  if (p === "/api/dashboard") {
    return {
      kpi: { total_proposals: 4, avg_score: 6.52, win_rate: 0.5, won: 1, lost: 1, pending_deals: 2, pipeline: [{ currency: "THB", amount: 7800000 }], pending_verify: 1 },
      verdict_breakdown: { Strong: 1, Adequate: 1, Weak: 1, Critical: 1 },
      score_trend: [
        { month: "2026-05", avg_score: 5.1, count: 2, won: 0, lost: 1, win_rate: 0 },
        { month: "2026-06", avg_score: 6.3, count: 3, won: 1, lost: 1, win_rate: 0.5 },
        { month: "2026-07", avg_score: 7.0, count: 4, won: 2, lost: 1, win_rate: 0.67 },
      ],
      needs_attention: [{ thread_id: T2, ticket_no: "PE-2026-00002", client_name: "Thai Summit Group", project_name: "Smart Factory Phase 2", overall_score: 5.6, verdict: "Adequate", deal_outcome: "Pending", verify_status: "pending_verify", content_stale: true, price_amount: 7800000, price_currency: "THB" }],
      low_score: [{ thread_id: T4, ticket_no: "PE-2026-00004", client_name: "PTT Digital", project_name: "Data Platform", overall_score: 3.2, verdict: "Weak", deal_outcome: "Lost", verify_status: "verified", content_stale: false, price_amount: null, price_currency: null }],
    };
  }
  if (p === "/api/audit") return { ready: true, items: AUDIT };
  if (p === "/api/users" && method === "GET") {
    return [
      { user_id: "u-dev", email: "dev.admin@example.com", display_name: "Dev Admin", role: "admin", created_at: "2026-06-01T09:00:00" },
      { user_id: "u-2", email: "carlos@example.com", display_name: "Carlos", role: "user", created_at: "2026-06-10T09:00:00" },
      { user_id: "u-3", email: "manager@example.com", display_name: "Manager", role: "manager", created_at: "2026-06-12T09:00:00" },
    ];
  }
  if (p === "/api/users") return { ok: true, users: route("/api/users", "GET", null) };
  if (p.startsWith("/api/users/")) return { ok: true, users: route("/api/users", "GET", null) };
  if (p === "/api/roles" || p.startsWith("/api/roles/")) {
    const pages = ["evaluate", "proposals", "library", "dashboard", "settings", "view_all", "manage_proposals"];
    const mk = (name: string, sys: boolean, on: string[], n: number) =>
      ({ role_id: "r-" + name, name, is_system: sys, permissions: Object.fromEntries(pages.map((g) => [g, on.includes(g)])), user_count: n });
    return { pages, roles: [
      mk("admin", true, pages, 1),
      mk("manager", false, ["evaluate", "proposals", "library", "view_all"], 1),
      mk("management", false, ["evaluate", "proposals", "library", "dashboard", "view_all"], 0),
      mk("user", false, ["evaluate", "proposals"], 1),
    ] };
  }
  if (p === "/api/rbac-init") return { seeded_roles: [], pages: [] };
  if (p === "/api/masterdata" && method === "GET") {
    return [
      { id: "m1", category: "solution_type", value: "ERP Implementation", sort_order: 0, active: true },
      { id: "m2", category: "solution_type", value: "IIoT", sort_order: 1, active: true },
      { id: "m3", category: "industry", value: "Automotive", sort_order: 0, active: true },
      { id: "m4", category: "industry", value: "Manufacturing", sort_order: 1, active: true },
    ];
  }
  if (p.startsWith("/api/masterdata")) {
    const items = route("/api/masterdata", "GET", null);
    return method === "DELETE" ? { ok: true, items } : items;
  }
  if (p === "/api/llm/models") return { ready: false, models: [] };

  // ---- flow ประเมิน (ให้เห็นแถบความคืบหน้า E07 + modal ยืนยัน) ----
  if (p === "/api/prepare") {
    return {
      blob_url: "", filename: "mock-proposal.pdf", content_type: "application/pdf",
      file_size: 1234567, content_hash: "mockhash", text: "เนื้อหา proposal ตัวอย่าง",
      suggested_client: "Acme Malaysia", suggested_project: "ERP Modernization",
      existing: { thread_id: T1, ticket_no: "PE-2026-00001", client_name: "Acme Malaysia", project_name: "ERP Modernization", latest_version: 3, next_version: 4, latest_score: 7.45, latest_verdict: "Strong", evaluated_at: "2026-07-28T09:20:00" },
    };
  }
  if (p === "/api/evaluate") {
    const sid = "sub-" + Date.now();
    evalTicks.set(sid, 0);
    return { status: "processing", submission_id: sid, thread_id: T1, ticket_no: "PE-2026-00001", version_no: 4, lang: body?.lang ?? "th" };
  }
  if (seg[1] === "submissions" && seg[3] === "status") {
    const n = (evalTicks.get(id) ?? 0) + 1;
    evalTicks.set(id, n);
    return { status: n >= 5 ? "Evaluated" : "Evaluating", thread_id: T1 };
  }
  // ---- Presentation Coach (งานคิว) ----
  if (p === "/api/presentation-coach" && method === "POST") {
    const job = "job-" + Date.now();
    coachTicks.set(job, 0);
    return { status: "processing", job_id: job };
  }
  if (p.startsWith("/api/presentation-coach/")) {
    const n = (coachTicks.get(id) ?? 0) + 1;
    coachTicks.set(id, n);
    if (n < 3) return { status: "Processing", guideline: "", error: "" };
    return { status: "Done", error: "", guideline: "## โฟกัสหลัก\n- ผลลัพธ์เชิงธุรกิจใน 12 เดือนแรก\n- ความเสี่ยงที่ควบคุมได้และแผนรับมือ\n- TCO 3 ปีเทียบกับสถานะปัจจุบัน\n\n## ประเด็นที่ควรชู\n- สถาปัตยกรรมแยกชั้นชัดเจน (slide 7)\n- แผนอบรมแยกตามกลุ่มผู้ใช้\n\n## สิ่งที่ควรเลี่ยงหรือระวัง\n- ยังไม่มี Master Schedule ที่ผูกผู้รับผิดชอบ — เตรียมคำตอบไว้\n- ไม่มีตัวเลข cost of inaction\n\n## คำถามที่อาจโดนถาม + แนวตอบ\n1. **ถ้าเลื่อน go-live จะกระทบอะไร** — อธิบาย gate การตรวจรับแต่ละ wave\n2. **ทีมที่ดูแลหลังส่งมอบคือใคร** — ชี้ไปที่หัวข้อ MA และ SLA" };
  }
  if (p === "/api/library/backfill") return { total: 0, done: 0, failed: [] };
  if (p === "/api/playbook" && method === "GET") {
    return { ready: true, items: PLAYBOOK };
  }
  if (p === "/api/playbook" && method === "POST") return { ready: true, items: PLAYBOOK };
  if (p.startsWith("/api/playbook/") && method === "DELETE") {
    return { ready: true, items: PLAYBOOK.filter((f) => f.name !== decodeURIComponent(id)) };
  }
  return undefined;
}

export function mockApi(): Plugin {
  return {
    name: "proposal-evaluator-mock-api",
    apply: "serve",   // dev เท่านั้น — ไม่มีผลกับ build
    configureServer(server) {
      const handler: Connect.NextHandleFunction = (req, res, next) => {
        if (!req.url?.startsWith("/api/")) return next();
        let raw = "";
        req.on("data", (c) => { raw += c; });
        req.on("end", () => {
          let body: any = null;
          try { body = raw && raw.trim().startsWith("{") ? JSON.parse(raw) : null; } catch { body = null; }
          const out = route(req.url!, req.method ?? "GET", body);
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          if (out === undefined) {
            res.statusCode = 404;
            res.end(JSON.stringify({ error: `mock: ยังไม่รองรับ ${req.method} ${req.url}` }));
            return;
          }
          // หน่วงเล็กน้อยให้เห็นสถานะ loading จริง
          setTimeout(() => res.end(JSON.stringify(out)), 120);
        });
      };
      server.middlewares.use(handler);
      server.config.logger.info("\n  [35m➜  MOCK API เปิดใช้งาน[0m — ข้อมูลปลอมทั้งหมด ไม่ต่อ Azure\n");
    },
  };
}
