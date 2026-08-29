// API client — เรียก Azure Functions ผ่าน SWA linked backend (/api relative)

/* ชนิดข้อมูลอยู่ใน ./types — re-export ไว้เพื่อความเข้ากันได้ย้อนหลัง (import เดิมไม่ต้องแก้) */
import type {
  AppSettings,
  AppUser,
  Audience,
  AuditRow,
  CoachStart,
  CommentRow,
  Dashboard,
  EvaluateResponse,
  EvaluationResult,
  Lang,
  LibraryItem,
  LibraryPatch,
  LibraryRow,
  LlmModelsResp,
  MasterDataRow,
  Me,
  PlaybookResp,
  PrepareResult,
  ProposalRow,
  Role,
  RolesResp,
} from "./types";
export type {
  AppSettings,
  AppUser,
  Audience,
  AuditRow,
  CoachStart,
  CommentRow,
  Confidence,
  DashActionRow,
  Dashboard,
  DealOutcome,
  EvalProcessing,
  EvaluateResponse,
  EvaluationResult,
  ExistingInfo,
  HistoryRow,
  Lang,
  LibraryItem,
  LibraryPatch,
  LibraryRow,
  LlmModelsResp,
  LlmProvider,
  ManpowerRow,
  MasterDataRow,
  Me,
  Milestone,
  PageKey,
  PlaybookFile,
  PlaybookResp,
  PrepareResult,
  ProposalRow,
  Recommendation,
  Role,
  RoleRow,
  RolesResp,
  ScoreDetail,
  ScoreSource,
  SyncStatus,
  Tier,
  Verdict,
  VerifyStatus,
} from "./types";

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

/** F22 — upload + extract + detect + lookup (ยังไม่ประเมิน) */
export async function prepare(file: File): Promise<PrepareResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/prepare", { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

/** F24/F25 — confirm client/project + เลือกภาษา output แล้วประเมิน (reuse=ทันที / LLM=async poll) */
export async function evaluate(p: PrepareResult, client_name: string, project_name: string, lang: Lang, threadId?: string, forceNew = false): Promise<EvaluateResponse> {
  return post<EvaluateResponse>("/api/evaluate", {
    client_name,
    project_name,
    lang,
    thread_id: threadId ?? "",   // R5 — เลือกโปรเจคเจาะจง (version ใหม่ของ thread นี้)
    force_new: forceNew,         // โปรเจคใหม่ -> ออก ticket ใหม่เสมอ ไม่จับคู่ชื่อเดิม
    text: p.text,
    content_hash: p.content_hash,
    blob_url: p.blob_url,
    filename: p.filename,
    content_type: p.content_type,
    file_size: p.file_size,
  });
}

/** poll สถานะ async eval — Evaluating|Evaluated|Failed */
export async function getSubmissionStatus(submissionId: string): Promise<{ status: string; thread_id: string }> {
  return get<{ status: string; thread_id: string }>(`/api/submissions/${submissionId}/status`);
}

/** F26 — add user comment. ชื่อผู้เขียนกำหนดโดย backend จาก SSO principal (D01) — ส่งมาไม่ได้ */
export async function addComment(thread_id: string, submission_id: string | undefined, comment_text: string) {
  return post<{ comments: CommentRow[] }>("/api/comments", { thread_id, submission_id: submission_id ?? null, comment_text });
}

async function get<T>(url: string): Promise<T> {
  // no-store: ข้อมูล dynamic (settings/me/lists) ต้อง fresh เสมอ กัน browser cache ค่าเก่า
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

/** F18/F19 — รายการทุก proposal (1 แถว/thread) */
export async function listProposals(scope?: "mine"): Promise<ProposalRow[]> {
  return get<ProposalRow[]>("/api/proposals" + (scope ? `?scope=${scope}` : ""));
}

/** F17 — ผลประเมินเต็มของ version ล่าสุดใน thread (shape เดียวกับ evaluate) */
export async function getThread(thread_id: string): Promise<EvaluationResult> {
  return get<EvaluationResult>(`/api/threads/${thread_id}`);
}

/** R8 — แก้ชื่อ client/project ของโปรเจค (permission manage_proposals) */
export async function updateThread(threadId: string, client_name: string, project_name: string): Promise<{ ok: boolean }> {
  const res = await fetch(`/api/threads/${threadId}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client_name, project_name }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}
/** R8 — ลบโปรเจค (permission manage_proposals) */
export async function deleteThread(threadId: string): Promise<{ ok: boolean }> {
  const res = await fetch(`/api/threads/${threadId}`, { method: "DELETE" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

/* ---------- Proposal Library (F31-F33) ---------- */

/* ---------- Dashboard (F42) ---------- */

/** F42 — สรุปภาพรวม Dashboard */
export async function getDashboard(): Promise<Dashboard> {
  return get<Dashboard>("/api/dashboard");
}

/* ---------- RBAC + Settings (F43-F46) ---------- */

/** F43 — ตัวตน + role + สิทธิ์เข้าหน้า */
export async function getMe(): Promise<Me> {
  return get<Me>("/api/me");
}

/** F44 — รายชื่อ user (admin) */
export async function listUsers(): Promise<AppUser[]> {
  return get<AppUser[]>("/api/users");
}

/** F44 — pre-add user ด้วย email + role */
export async function addUser(email: string, role: Role): Promise<{ ok: boolean; users: AppUser[] }> {
  return post<{ ok: boolean; users: AppUser[] }>("/api/users", { email, role });
}

/** F44 — เปลี่ยน role */
export async function setUserRole(userId: string, role: Role): Promise<{ ok: boolean; users: AppUser[] }> {
  const res = await fetch(`/api/users/${userId}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

/** F45 — master data (Solution Type / Industry) */
export async function listMasterData(category?: string): Promise<MasterDataRow[]> {
  return get<MasterDataRow[]>(`/api/masterdata${category ? `?category=${category}` : ""}`);
}
export async function addMasterData(category: string, value: string): Promise<MasterDataRow[]> {
  return post<MasterDataRow[]>("/api/masterdata", { category, value });
}
export async function deleteMasterData(id: string): Promise<{ ok: boolean; items: MasterDataRow[] }> {
  const res = await fetch(`/api/masterdata/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

export async function getSettings(): Promise<AppSettings> {
  return get<AppSettings>("/api/settings");
}
export async function putSettings(kv: Record<string, string>): Promise<AppSettings> {
  const res = await fetch("/api/settings", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(kv),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

export async function getLlmModels(): Promise<LlmModelsResp> {
  return get<LlmModelsResp>("/api/llm/models");
}

export async function getRoles(): Promise<RolesResp> {
  return get<RolesResp>("/api/roles");
}
export async function initRbac(): Promise<{ seeded_roles: string[]; pages: string[] }> {
  return post<{ seeded_roles: string[]; pages: string[] }>("/api/rbac-init", {});
}
export async function createRole(name: string): Promise<RolesResp> {
  return post<RolesResp>("/api/roles", { name });
}
export async function deleteRole(roleId: string): Promise<RolesResp> {
  const res = await fetch(`/api/roles/${roleId}`, { method: "DELETE" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}
export async function setRolePermissions(roleId: string, permissions: Record<string, boolean>): Promise<RolesResp> {
  const res = await fetch(`/api/roles/${roleId}/permissions`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ permissions }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

/** G01 — ตั้งงาน coach (preset: ส่ง audience key / custom: audience="" + custom_audience) */
export async function startPresentationCoach(
  thread_id: string, audience: Audience | "", custom_audience = "",
): Promise<CoachStart> {
  return post<CoachStart>("/api/presentation-coach", { thread_id, audience, custom_audience });
}

/** G01 — poll สถานะงาน coach */
export async function getCoachStatus(job_id: string): Promise<{ status: string; guideline: string; error: string }> {
  return get<{ status: string; guideline: string; error: string }>(`/api/presentation-coach/${job_id}`);
}

export async function listAudit(params: { thread_id?: string; actor?: string; limit?: number } = {}): Promise<{ ready: boolean; items: AuditRow[] }> {
  const q = new URLSearchParams();
  if (params.thread_id) q.set("thread_id", params.thread_id);
  if (params.actor) q.set("actor", params.actor);
  if (params.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return get<{ ready: boolean; items: AuditRow[] }>("/api/audit" + (qs ? `?${qs}` : ""));
}

/** F31 — รายการ Proposal Library (1 แถว/thread) */
export async function listLibrary(): Promise<LibraryRow[]> {
  return get<LibraryRow[]>("/api/library");
}

/** F32 — content เต็ม + ลิงก์ไฟล์ */
export async function getLibraryItem(thread_id: string): Promise<LibraryItem> {
  return get<LibraryItem>(`/api/library/${thread_id}`);
}

/** F33 — แก้/ยืนยัน project content */
export async function updateLibraryItem(thread_id: string, patch: LibraryPatch): Promise<LibraryItem> {
  const res = await fetch(`/api/library/${thread_id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

/** ตรวจ/สร้างตารางที่ Wave 1/3 ต้องใช้ (AuditLog / CoachJobs) — idempotent, สิทธิ์ settings */
export interface DbMigrateResult { ok: boolean; missing: string[]; created?: string[]; hint?: string }
export async function checkDbSchema(): Promise<DbMigrateResult> {
  return get<DbMigrateResult>("/api/db-migrate");
}
export async function runDbMigrate(): Promise<DbMigrateResult> {
  return post<DbMigrateResult>("/api/db-migrate", {});
}

/* ---------- Playbook (คู่มือการใช้งาน) ---------- */

/** รายการไฟล์คู่มือ + ลิงก์เปิด/ดาวน์โหลด — ทุก role เรียกได้ (ไม่ผูก page permission) */
export async function listPlaybook(): Promise<PlaybookResp> {
  return get<PlaybookResp>("/api/playbook");
}

/** อัปโหลด/แทนที่ไฟล์คู่มือ (สิทธิ์ settings) — ชื่อซ้ำ = ทับไฟล์เดิม */
export async function uploadPlaybook(file: File): Promise<PlaybookResp> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/playbook", { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}

/** ลบไฟล์คู่มือ (สิทธิ์ settings) */
export async function deletePlaybook(name: string): Promise<PlaybookResp> {
  const res = await fetch(`/api/playbook/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
  return res.json();
}
