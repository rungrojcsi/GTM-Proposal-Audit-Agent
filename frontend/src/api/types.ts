/* ชนิดข้อมูลของ API — แยกจาก client.ts เพื่อให้แต่ละไฟล์ไม่เกิน 400 บรรทัด (NFR N8)
   client.ts ยัง re-export ทุกชนิดให้ ดังนั้น import เดิมทั้งโปรเจคใช้ได้เหมือนเดิม */

export type Tier = "Critical" | "Important" | "Optional";

export type Verdict = "Strong" | "Adequate" | "Weak" | "Critical";

export type ScoreSource = "evaluated" | "reused";

export type Lang = "th" | "en";

export interface ScoreDetail {
  slide_section: string;
  tier: Tier;
  score_1_10: number;
  coverage: string;
}

export interface Recommendation {
  priority: Tier;
  rec_text: string;
  slide_ref: string;
}

export interface HistoryRow {
  ticket_no: string;
  version_no: number;
  status: string;
  score_source: ScoreSource | null;
  overall_score: number | null;
  verdict: Verdict | null;
  evaluated_at: string | null;
}

export interface CommentRow {
  submission_id: string | null;
  author: string;
  comment_text: string;
  created_at: string;
}

export interface ExistingInfo {
  thread_id: string;
  ticket_no: string;
  client_name: string;
  project_name: string;
  latest_version: number;
  next_version: number;
  latest_score: number | null;
  latest_verdict: Verdict | null;
  evaluated_at: string | null;
}

export interface PrepareResult {
  blob_url: string;
  filename: string;
  content_type: string;
  file_size: number;
  content_hash: string;
  text: string;
  suggested_client: string;
  suggested_project: string;
  existing: ExistingInfo | null; // null = โปรเจคใหม่
}

export interface EvaluationResult {
  thread_id: string;
  ticket_no: string;
  history: HistoryRow[];
  comments: CommentRow[];
  /** false = ทุก version ของ thread นี้ยังไม่เคยประเมินสำเร็จ (Failed/Evaluating ทั้งหมด)
      -> field ด้านล่างทั้งหมดจะไม่มีมาจาก backend เลย (thread_detail คืน shape สั้น) */
  evaluated?: boolean;
  version_no?: number;
  submission_id?: string;
  score_source?: ScoreSource;
  gate_note?: string;
  lang?: Lang;
  overall_score?: number;
  verdict?: Verdict;
  score_details?: ScoreDetail[];
  recommendations?: Recommendation[];
  skeleton_md?: string;
  strengths?: string[];
  gaps?: string[];
  client_name?: string; // มาจาก /threads/{id} (เปิดจากหน้า list)
  project_name?: string;
  filename?: string;    // ไฟล์ต้นฉบับที่อัพโหลด (version ล่าสุด)
  file_url?: string;    // SAS URL เปิดไฟล์ต้นฉบับ (หมดอายุ ~4 ชม.)
  model_name?: string;  // LLM model ที่ใช้ประเมินผลนี้
}

export interface ProposalRow {
  thread_id: string;
  ticket_no: string;
  client_name: string | null;
  project_name: string | null;
  version_no: number;
  version_count: number;
  /** E06 — สถานะ version ล่าสุด: Evaluating = กำลังประเมิน (คะแนนยังว่าง) | Failed | Evaluated | Accepted */
  status: string | null;
  overall_score: number | null;
  verdict: Verdict | null;
  score_source: ScoreSource | null;
  evaluated_at: string | null;
  /** ชื่อคนที่ upload (owner_id ของ thread) — null = thread เก่าที่ยังไม่มี owner */
  owner_name: string | null;
}

/** async eval — cache hit คืน status:"done" + result เต็ม; ต้องเรียก LLM คืน status:"processing" ให้ poll */
export interface EvalProcessing {
  status: "processing";
  submission_id: string;
  thread_id: string;
  ticket_no: string;
  version_no: number;
  lang: Lang;
}

export type EvaluateResponse = (EvaluationResult & { status?: "done" }) | EvalProcessing;

export type DealOutcome = "Won" | "Lost" | "Pending";

export type VerifyStatus = "pending_verify" | "verified";

export type SyncStatus = "pending" | "synced" | "failed";

export type Confidence = "high" | "medium" | "low";

export interface Milestone { name: string; timeframe: string }

export interface ManpowerRow { role: string; count: number | null; man_days: number | null }

export interface LibraryRow {
  thread_id: string;
  ticket_no: string;
  client_name: string | null;
  project_name: string | null;
  price_amount: number | null;
  price_currency: string | null;
  cost_amount: number | null;
  cost_currency: string | null;
  duration_months: number | null;
  solution_type: string | null;
  industry: string | null;
  deal_outcome: DealOutcome | null;    // null = ยังไม่มี content record
  verify_status: VerifyStatus | null;
  content_stale: boolean | null;
  sync_status: SyncStatus | null;
  updated_at: string | null;
  version_no: number;
  overall_score: number | null;
  verdict: Verdict | null;
  /** ชื่อคนที่ upload (owner_id ของ thread) — null = thread เก่าที่ยังไม่มี owner */
  owner_name: string | null;
}

export interface LibraryItem {
  thread_id: string;
  ticket_no: string;
  client_name: string | null;
  project_name: string | null;
  price_amount: number | null;
  price_currency: string | null;
  cost_amount: number | null;
  cost_currency: string | null;
  duration_months: number | null;
  milestones: Milestone[];
  manpower: ManpowerRow[];
  solution_type: string | null;
  industry: string | null;
  deal_outcome: DealOutcome | null;
  source: "extracted" | "manual" | "pm_system" | null;
  field_confidence: Partial<Record<string, Confidence>>;
  content_stale: boolean | null;
  verify_status: VerifyStatus | null;
  verified_by: string | null;
  verified_at: string | null;
  sharepoint_url: string | null;
  sync_status: SyncStatus | null;
  updated_at: string | null;
  has_content: boolean;
  filename: string;
  file_url: string;
}

/** field ที่ PATCH ได้ (F33) */
export interface LibraryPatch {
  price_amount?: number | null;
  price_currency?: string | null;
  cost_amount?: number | null;
  cost_currency?: string | null;
  duration_months?: number | null;
  milestones?: Milestone[];
  manpower?: ManpowerRow[];
  solution_type?: string | null;
  industry?: string | null;
  deal_outcome?: DealOutcome;
  verify?: boolean;
  // ไม่มี author — verified_by กำหนดโดย backend จาก SSO principal (D02)
}

export interface DashActionRow {
  thread_id: string;
  ticket_no: string;
  client_name: string | null;
  project_name: string | null;
  overall_score: number | null;
  verdict: Verdict | null;
  deal_outcome: DealOutcome | null;
  verify_status: VerifyStatus | null;
  content_stale: boolean;
  price_amount: number | null;
  price_currency: string | null;
}

export interface Dashboard {
  kpi: {
    total_proposals: number;
    avg_score: number | null;
    win_rate: number | null;   // 0-1
    won: number;
    lost: number;
    pending_deals: number;
    pipeline: { currency: string; amount: number }[];
    pending_verify: number;
  };
  verdict_breakdown: Record<Verdict, number>;
  score_trend: { month: string; avg_score: number; count: number; won: number; lost: number; win_rate: number | null }[];
  needs_attention: DashActionRow[];
  low_score: DashActionRow[];
}

export type Role = string;  // dynamic (R3) — role ใดๆ จาก dbo.Roles (ไม่ fix 4 ตัวแล้ว)
export type PageKey = "evaluate" | "proposals" | "library" | "dashboard" | "settings";

/* ไฟล์คู่มือการใช้งาน (Playbook) — เก็บใน Blob prefix "playbook/" ไม่ผูกกับ PageKey
   เพราะเมนูนี้เปิดให้ทุก role โดยเจตนา (ไม่มีสิทธิ์ให้ปิด) */
export interface PlaybookFile {
  name: string;
  size: number;
  content_type: string;
  updated_at: string;
  url: string;            // ลิงก์ SAS อายุ 1 ชม. — "" ถ้าสร้างไม่สำเร็จ
}

export interface PlaybookResp {
  ready: boolean;         // false = อ่านคลังไฟล์ไม่ได้ (env/Blob ไม่พร้อม)
  items: PlaybookFile[];
  hint?: string;
}

export interface Me {
  user_id: string | null;
  email: string | null;
  name: string;
  role: Role;
  authenticated: boolean;
  access: Record<string, boolean>;   // 5 nav pages + view_all + manage_proposals
}

export interface AppUser {
  user_id: string;
  email: string;
  display_name: string | null;
  role: Role;
  created_at: string;
}

export interface MasterDataRow {
  id: string;
  category: "solution_type" | "industry";
  value: string;
  sort_order: number;
  active: boolean;
}

/** F46/R2 — audit defaults + LLM provider (local config ฝัง env ฝั่ง backend ไม่ส่งค่ากลับ) */
export type LlmProvider = "azure" | "local";

export interface AppSettings {
  default_lang: string;
  default_currency: string;
  llm_provider: LlmProvider;
  active_model?: string;       // ชื่อ model ปัจจุบันที่ใช้ประเมิน (ทุก role เห็น)
  local_llm_ready?: boolean;   // admin-only — env (base_url+model) ตั้งครบไหม
  local_llm_model?: string;    // admin-only — model จาก env (read-only)
  // S02 admin-only — จำกัดการเข้าถึงตามเครือข่าย (แทนการพึ่ง VPN); ค่าเริ่มต้น = ปิด
  ip_restriction_enabled?: boolean;
  ip_allowlist?: string;       // CIDR คั่น comma เช่น "203.0.113.0/24, 10.0.0.0/8"
  ip_kill_switch?: boolean;    // env IP_RESTRICTION_OFF=1 ปิดการตรวจไว้ (read-only)
}

/** R2 — รายชื่อ model จาก local LLM server ให้เลือกใน Settings (admin) */
export interface LlmModelsResp { ready: boolean; models: string[]; }

/* ---------- Roles & Permissions (R3 — dynamic RBAC) ---------- */
export interface RoleRow {
  role_id: string;
  name: string;
  is_system: boolean;
  permissions: Record<string, boolean>;  // {page: canAccess}
  user_count: number;
}

export interface RolesResp { roles: RoleRow[]; pages: string[]; }

/* ---------- Presentation Coach (R4 / G01 async) ---------- */
export type Audience = "c_level" | "users" | "it" | "purchase" | "technical" | "non_technical";

/** ผลเดิมที่ใช้ซ้ำได้ -> done ทันที; ต้องเรียก LLM -> processing ให้ poll ต่อ */
export type CoachStart =
  | { status: "done"; job_id: string; guideline: string; reused?: boolean }
  | { status: "processing"; job_id: string };

/** C05 — ร่องรอยการตรวจสอบ (สิทธิ์ settings). ready:false = ยังไม่ได้รัน migration */
export interface AuditRow {
  audit_id: string;
  occurred_at: string;
  actor_email: string | null;
  actor_role: string | null;
  actor_ip: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  target_label: string | null;
  before_json: string | null;
  after_json: string | null;
}
