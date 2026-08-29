/* ทดสอบว่าช่องค้นหาบนแถบบนกรองด้วยชื่อ Owner ได้จริง (บั๊กจาก code review 2026-08-15)
 *
 *   npx vite preview --port 4173 --host 127.0.0.1
 *   BASE=http://127.0.0.1:4173 node e2e-owner-search.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.BASE || "http://127.0.0.1:4173";
const ME = {
  user_id: "u-1", email: "owner@example.com", name: "Owner S.", role: "admin", authenticated: true,
  access: { evaluate: true, proposals: true, library: true, dashboard: true, settings: true, view_all: true, manage_proposals: true },
};
// owner ต่างกัน 3 คน — client/project จงใจไม่มีคำว่า "Erin" หรือ "Carlos" ปนอยู่
const PROPOSALS = [
  { thread_id: "t1", ticket_no: "PE-2026-00001", client_name: "Acme", project_name: "ACME-MY", owner_name: "Carlos P.", version_no: 1, version_count: 1, status: "Evaluated", overall_score: 7.7, verdict: "Strong", score_source: "evaluated", evaluated_at: "2026-08-15" },
  { thread_id: "t2", ticket_no: "PE-2026-00002", client_name: "Nova", project_name: "Data Platform", owner_name: "Erin R.", version_no: 1, version_count: 1, status: "Evaluated", overall_score: 6.1, verdict: "Adequate", score_source: "evaluated", evaluated_at: "2026-08-14" },
  { thread_id: "t3", ticket_no: "PE-2026-00003", client_name: "Thai Honda", project_name: "PCPACK", owner_name: "Carlos P.", version_no: 1, version_count: 1, status: "Evaluated", overall_score: 5.2, verdict: "Adequate", score_source: "evaluated", evaluated_at: "2026-08-13" },
];
const json = (b) => ({ status: 200, contentType: "application/json", body: JSON.stringify(b) });

const browser = await chromium.launch();
const page = await browser.newPage();
await page.route("**/api/**", (r) => {
  const u = new URL(r.request().url()).pathname;
  if (u.endsWith("/api/me")) return r.fulfill(json(ME));
  if (u.endsWith("/api/proposals")) return r.fulfill(json(PROPOSALS));
  return r.fulfill(json([]));
});

const out = [];
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  out.push([ok, `${ok ? "✅" : "❌"} ${label}\n     ได้  : ${JSON.stringify(got)}${ok ? "" : `\n     คาด : ${JSON.stringify(want)}`}`]);
};

await page.goto(`${BASE}/proposals`, { waitUntil: "networkidle" });
await page.locator("table.tbl tbody tr").first().waitFor();
const tickets = () => page.locator("table.tbl tbody tr td:first-child").allInnerTexts().then((v) => v.map((s) => s.trim()));
const search = page.locator('.search input');

check("เปิดมาเห็นครบ 3 รายการ", await tickets(), ["PE-2026-00001", "PE-2026-00002", "PE-2026-00003"]);

await search.fill("Erin");
await page.waitForTimeout(150);
check("ค้นชื่อ owner 'Erin' -> เจอเฉพาะของ Erin", await tickets(), ["PE-2026-00002"]);

await search.fill("Carlos");
await page.waitForTimeout(150);
check("ค้นชื่อ owner 'Carlos' -> เจอ 2 รายการของเขา", await tickets(), ["PE-2026-00001", "PE-2026-00003"]);

await search.fill("carlos");
await page.waitForTimeout(150);
check("ค้นแบบพิมพ์เล็ก (case-insensitive)", await tickets(), ["PE-2026-00001", "PE-2026-00003"]);

await search.fill("Nova");
await page.waitForTimeout(150);
check("ค้นด้วย client เดิมยังทำงาน (ไม่ทำของเก่าพัง)", await tickets(), ["PE-2026-00002"]);

await search.fill("ไม่มีคนนี้");
await page.waitForTimeout(150);
const empty = await page.getByText(/No proposals match/).count();
check("ค้นแล้วไม่เจอ -> ขึ้นข้อความว่าไม่พบ", empty > 0, true);

await page.screenshot({ path: "e2e-owner-search.png" });
console.log();
for (const [, l] of out) console.log(l);
const failed = out.filter(([ok]) => !ok);
console.log(`\n${failed.length ? `❌ ไม่ผ่าน ${failed.length} ข้อ` : "✅ ผ่านทั้งหมด"} (${out.length - failed.length}/${out.length})`);
await browser.close();
process.exitCode = failed.length ? 1 : 0;
