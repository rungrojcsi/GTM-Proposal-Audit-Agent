/* ทดสอบบั๊ก "พิมพ์ได้ตัวเดียวแล้วโฟกัสเด้งไปปุ่มแรก" ด้วยเบราว์เซอร์จริง
 *
 * ทดสอบกับ dist/ (bundle ตัวเดียวกับที่ deploy ขึ้น production) ไม่ใช่ซอร์สใน dev mode
 * เพื่อให้ผลลัพธ์ตรงกับสิ่งที่ Boss เจอจริง
 *
 *   node e2e-modal-focus.mjs            -> ใช้ dist/ ที่ build ไว้
 *   BASE=http://localhost:4173 node ... -> ชี้ไป server ที่รันไว้แล้ว
 *
 * ดัก /api/* ทั้งหมดด้วย playwright route (ไม่แตะ Azure จริง ไม่ต้อง login)
 */
import { chromium } from "playwright";

const BASE = process.env.BASE || "http://localhost:4173";
const TYPE_TEXT = "Acme ACME-MY Project";

const ME = {
  user_id: "u-1", email: "owner@example.com", name: "Owner S.",
  role: "admin", authenticated: true,
  access: { evaluate: true, proposals: true, library: true, dashboard: true, settings: true, view_all: true, manage_proposals: true },
};

const PREPARE = {
  blob_url: "https://example/blob/x.pdf", filename: "x.pdf", content_type: "application/pdf",
  file_size: 1234, content_hash: "a".repeat(64), text: "proposal text",
  suggested_client: "Acme", suggested_project: "Acme ACME-MY Projec",
  existing: null,   // null -> modal เปิดโหมด "โปรเจคใหม่" = มีช่อง Client/Project name
};

const json = (body) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

const browser = await chromium.launch();
const page = await browser.newPage();

await page.route("**/api/**", (route) => {
  const u = new URL(route.request().url()).pathname;
  if (u.endsWith("/api/me")) return route.fulfill(json(ME));
  if (u.endsWith("/api/prepare")) return route.fulfill(json(PREPARE));
  if (u.endsWith("/api/proposals")) return route.fulfill(json([]));
  if (u.endsWith("/api/settings")) return route.fulfill(json({ default_lang: "th", active_model: "gpt-5.4-mini", llm_provider: "azure" }));
  return route.fulfill(json({}));
});

const fail = (msg) => { console.log(`\n❌ FAIL — ${msg}`); process.exitCode = 1; };

await page.goto(`${BASE}/evaluate`, { waitUntil: "networkidle" });

// อัปโหลดไฟล์ปลอม -> ปุ่ม Upload -> modal เปิด
await page.setInputFiles('input[type="file"]', {
  name: "x.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 fake"),
});
await page.getByRole("button", { name: "อัปโหลดและตรวจหาชื่อ" }).click();
await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
console.log("✔ modal เปิดแล้ว");

const projectInput = page.locator('[role="dialog"] input.field').nth(1);
await projectInput.waitFor();
await projectInput.click();
await projectInput.fill("");

// พิมพ์ทีละตัว แล้วเช็คหลังทุกตัวว่าโฟกัสยังอยู่ที่ input เดิมไหม
const focusTrail = [];
for (const ch of TYPE_TEXT) {
  await page.keyboard.type(ch, { delay: 25 });
  focusTrail.push(await page.evaluate(() => {
    const a = document.activeElement;
    return a?.tagName === "INPUT" ? "INPUT" : `${a?.tagName}:${(a?.textContent || "").trim().slice(0, 20)}`;
  }));
}

// ช่อง input อาจหายไปเลยระหว่างพิมพ์: โฟกัสเด้งไปปุ่ม -> เคาะ space -> ปุ่มถูกกด
// -> projectMode สลับเป็น "select" -> ช่อง Client/Project ถูก unmount
const value = await projectInput.inputValue({ timeout: 3000 }).catch(() => null);
const lost = focusTrail.findIndex((f) => f !== "INPUT");

console.log(`\nพิมพ์ไป      : "${TYPE_TEXT}" (${TYPE_TEXT.length} ตัว)`);
console.log(`ค่าในช่อง    : ${value === null ? "‹ช่องหายไปจากหน้าจอ›" : `"${value}" (${value.length} ตัว)`}`);
console.log(`โฟกัสหลุดที่ : ${lost === -1 ? "ไม่หลุดเลย" : `ตัวที่ ${lost + 1} -> ${focusTrail[lost]}`}`);

if (value === null) fail("ช่อง Project name หายไประหว่างพิมพ์ (โฟกัสเด้งไปปุ่ม แล้ว space ไปกดปุ่มนั้น)");
else if (value !== TYPE_TEXT) fail(`ค่าในช่องไม่ตรงกับที่พิมพ์ — ตัวอักษรหาย ${TYPE_TEXT.length - value.length} ตัว`);
if (lost !== -1) fail(`โฟกัสเด้งออกจาก input ที่ตัวอักษรที่ ${lost + 1}`);
if (value === TYPE_TEXT && lost === -1) console.log("\n✅ PASS — พิมพ์ครบทุกตัว โฟกัสไม่เด้งเลย");

await page.screenshot({ path: "e2e-modal-focus.png" });
console.log("screenshot: frontend/e2e-modal-focus.png");
await browser.close();
