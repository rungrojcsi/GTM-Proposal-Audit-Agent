/* ทดสอบ 2 อย่างที่เพิ่มในหน้า Settings > User Management ด้วยเบราว์เซอร์จริง
 *   1) คลิกหัวคอลัมน์แล้วเรียงลำดับจริง (asc -> คลิกซ้ำ desc)
 *   2) ปุ่มชิปของแต่ละ role ซ่อน/แสดงผู้ใช้ของ role นั้นได้
 *
 *   npx vite preview --port 4173 --host 127.0.0.1
 *   BASE=http://127.0.0.1:4173 node e2e-users-panel.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.BASE || "http://127.0.0.1:4173";

const ME = {
  user_id: "u-1", email: "owner@example.com", name: "Owner S.",
  role: "admin", authenticated: true,
  access: { evaluate: true, proposals: true, library: true, dashboard: true, settings: true, view_all: true, manage_proposals: true },
};

// จงใจใส่ลำดับสลับ เพื่อให้รู้ว่า "เรียงแล้ว" ต่างจาก "ลำดับที่ API ส่งมา"
const USERS = [
  { user_id: "u-3", email: "dan@example.com", display_name: "Dan N.", role: "user" },
  { user_id: "u-1", email: "owner@example.com", display_name: "Owner S.", role: "admin" },
  { user_id: "u-4", email: "beth@example.com", display_name: "Beth P.", role: "management" },
  { user_id: "u-2", email: "alice@example.com", display_name: "Alice W.", role: "management" },
];
const ROLES = { roles: [{ name: "user" }, { name: "manager" }, { name: "management" }, { name: "admin" }] };

const json = (b) => ({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
const browser = await chromium.launch();
const page = await browser.newPage();

await page.route("**/api/**", (route) => {
  const u = new URL(route.request().url()).pathname;
  if (u.endsWith("/api/me")) return route.fulfill(json(ME));
  if (u.endsWith("/api/users")) return route.fulfill(json(USERS));
  if (u.endsWith("/api/roles")) return route.fulfill(json(ROLES));
  if (u.endsWith("/api/settings")) return route.fulfill(json({ default_lang: "th", active_model: "gpt-5.4-mini", llm_provider: "azure" }));
  if (u.endsWith("/api/audit")) return route.fulfill(json([]));
  if (u.endsWith("/api/llm/models")) return route.fulfill(json({ ready: false, models: [] }));
  return route.fulfill(json([]));
});

const out = [];
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  out.push([ok, `${ok ? "✅" : "❌"} ${label}\n     ได้  : ${JSON.stringify(got)}${ok ? "" : `\n     คาด : ${JSON.stringify(want)}`}`]);
};

await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });

// กางกล่อง User Management
const card = page.locator('.card', { has: page.getByText("User Management") });
await card.getByRole("button", { name: "แสดง" }).click();
await card.locator("table.tbl tbody tr").first().waitFor();

const namesShown = () => card.locator("table.tbl tbody tr td:first-child").allInnerTexts()
  .then((v) => v.map((s) => s.replace(/\s*\(you\)\s*/, "").trim()));
// ปุ่มหัวคอลัมน์มีลูกศรบอกทิศต่อท้าย ("User ▾") จึง anchor แค่หัวข้อความ
const th = (label) => card.locator("table.tbl thead button", { hasText: new RegExp(`^${label}`) });
const chip = (label) => card.locator("button", { hasText: new RegExp(`^${label} \\(\\d+\\)$`) });
const rolesShown = () => card.locator("table.tbl tbody tr td:nth-child(3) select").evaluateAll((els) => els.map((e) => e.value));

console.log("แถวตอนเปิด (ยังไม่คลิกอะไร):", await namesShown());

// ── 1) เรียงลำดับ ──
await th("User").click();
check("คลิก 'User' -> เรียงชื่อ A→Z", await namesShown(), ["Alice W.", "Beth P.", "Owner S.", "Dan N."]);

await th("User").click();
check("คลิก 'User' ซ้ำ -> กลับด้าน Z→A", await namesShown(), ["Dan N.", "Owner S.", "Beth P.", "Alice W."]);

await th("Email").click();
check("คลิก 'Email' -> เรียงอีเมล A→Z", await namesShown(), ["Alice W.", "Beth P.", "Owner S.", "Dan N."]);

await th("Role").click();
check("คลิก 'Role' -> เรียงตาม role", await rolesShown(), ["admin", "management", "management", "user"]);

// ── 2) ชิปซ่อน/แสดงตาม role ──
await chip("Management").click();
check("ซ่อน role management -> เหลือ 2 คน", await rolesShown(), ["admin", "user"]);

await chip("User").click();
check("ซ่อน role user ด้วย -> เหลือแต่ admin", await rolesShown(), ["admin"]);

const counter = (await card.locator(".sec-count").innerText()).trim();
check("ตัวนับหัวข้อบอกว่ากรองอยู่", counter, "(1/4)");

await card.getByRole("button", { name: "แสดงทั้งหมด" }).click();
check("กด 'แสดงทั้งหมด' -> กลับมาครบ 4 คน", (await rolesShown()).length, 4);

await page.screenshot({ path: "e2e-users-panel.png", fullPage: false });
console.log();
for (const [, line] of out) console.log(line);
const failed = out.filter(([ok]) => !ok);
console.log(`\n${failed.length ? `❌ ไม่ผ่าน ${failed.length} ข้อ` : "✅ ผ่านทั้งหมด"} (${out.length - failed.length}/${out.length})`);
await browser.close();
process.exitCode = failed.length ? 1 : 0;
