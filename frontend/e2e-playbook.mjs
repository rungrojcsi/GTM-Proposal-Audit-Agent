/* e2e — เมนู Playbook ต้องเห็นและใช้ได้ "ทุก role" รวมถึง role ที่ไม่มีสิทธิ์หน้าใดเลย
   รันคู่กับ mock server: VITE_MOCK_API=1 npx vite --port 5199 --strictPort
   แล้ว node e2e-playbook.mjs */
import { chromium } from "playwright";

const BASE = process.env.BASE ?? "http://localhost:5199";
const fails = [];
const ok = (cond, label) => { console.log(`${cond ? "✔" : "✘"} ${label}`); if (!cond) fails.push(label); };

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("pageerror", (e) => fails.push(`pageerror: ${e.message}`));

/* ---------- 1) admin: หน้า Playbook แสดงไฟล์จาก /api/playbook ---------- */
await page.goto(`${BASE}/playbook`, { waitUntil: "networkidle" });
await page.waitForSelector("text=Playbook files", { timeout: 10000 });

ok(await page.locator('nav.nav a[href="/playbook"]').count() === 1, "nav มีเมนู Playbook");
ok(await page.locator('nav.nav a[href="/playbook"].active').count() === 1, "เมนู Playbook ถูก highlight ตอนอยู่หน้านี้");
ok((await page.locator("h1, .h-title").first().innerText()).includes("Playbook"), "หัวข้อหน้าเป็น Playbook");
ok(await page.getByText("ProposalAudit-Playbook-TH.pdf").count() === 1, "แสดงไฟล์ PDF");
ok(await page.getByText("ProposalAudit-Playbook-TH.pptx").count() === 1, "แสดงไฟล์ PPTX");
ok(await page.getByText("15.8 MB").count() === 1, "แปลงขนาดไฟล์เป็น MB (16592102 -> 15.8 MB)");
ok(await page.getByRole("link", { name: "Open" }).count() === 1, "PDF ได้ปุ่ม 'Open'");
ok(await page.getByRole("link", { name: "Download" }).count() === 1, "PPTX ได้ปุ่ม 'Download'");

const pdfHref = await page.getByRole("link", { name: "Open" }).getAttribute("href");
ok(pdfHref === "https://example.invalid/mock-playbook.pdf", "ปุ่มชี้ไป url ที่ backend ส่งมา (SAS)");
ok(await page.getByRole("link", { name: "Open" }).getAttribute("target") === "_blank", "เปิดในแท็บใหม่");

/* ---------- 2) สรุปย่อในแอป กางได้ ---------- */
ok(await page.getByText("Five steps to run an audit").count() === 0, "สรุปย่อถูกพับไว้ตอนแรก");
await page.locator(".card", { hasText: "Quick guide" }).getByRole("button", { name: "Show" }).click();
await page.waitForSelector("text=Five steps to run an audit", { timeout: 5000 });
ok(await page.getByText("New Evaluation").count() > 0, "สรุปย่อกางแล้วเห็นขั้นตอน");
ok(await page.getByText("Limits you should know").count() === 1, "สรุปย่อมีหัวข้อข้อจำกัด");
await page.screenshot({ path: "e2e-playbook.png", fullPage: true });

/* ---------- 3) role ที่ไม่มีสิทธิ์หน้าใดเลย ยังต้องเข้า Playbook ได้ ---------- */
const noAccess = await browser.newPage({ viewport: { width: 1280, height: 900 } });
noAccess.on("pageerror", (e) => fails.push(`pageerror(noAccess): ${e.message}`));
await noAccess.route("**/api/me", (route) => route.fulfill({
  status: 200, contentType: "application/json",
  body: JSON.stringify({
    user_id: "u-new", email: "new.joiner@example.com", name: "New Joiner",
    role: "guest-like", authenticated: true,
    access: { evaluate: false, proposals: false, library: false, dashboard: false, settings: false, view_all: false, manage_proposals: false },
  }),
}));
await noAccess.goto(`${BASE}/`, { waitUntil: "networkidle" });
await noAccess.waitForSelector('nav.nav a[href="/playbook"]', { timeout: 10000 });
ok(new URL(noAccess.url()).pathname === "/playbook", `เข้า / แล้วเด้งไป /playbook (ได้ ${new URL(noAccess.url()).pathname})`);
ok(await noAccess.locator("nav.nav a").count() === 1, "role นี้เห็นเมนูเดียวคือ Playbook");
ok(await noAccess.getByText("ProposalAudit-Playbook-TH.pdf").count() === 1, "role ไม่มีสิทธิ์ยังเปิดไฟล์คู่มือได้");
await noAccess.screenshot({ path: "e2e-playbook-noaccess.png", fullPage: true });

/* ---------- 4) deep link ที่ไม่มีสิทธิ์ ต้องมีทางออกไปคู่มือ ---------- */
await noAccess.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
await noAccess.waitForSelector("text=ไม่มีสิทธิ์เข้าถึงหน้านี้", { timeout: 10000 });
ok(await noAccess.getByRole("link", { name: "เปิดคู่มือการใช้งาน" }).count() === 1, "หน้า Forbidden มีปุ่มไปคู่มือ");

/* ---------- 5) แผงจัดการไฟล์ใน Settings (admin) ----------
   หมายเหตุ: หน้า Playbook เป็นอังกฤษทั้งหน้า แต่แผงนี้อยู่ในหน้า Settings
   ซึ่งยังเป็นไทยตามหน้าอื่น -> ปุ่ม "แสดง"/"ลบ" ที่นี่จึงยังเป็นไทย */
await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
const panel = page.locator(".card", { hasText: "Playbook files" }).first();
await panel.getByRole("button", { name: "แสดง" }).click();
await page.waitForSelector('input[type="file"][accept=".pdf,.pptx,.docx,.md"]', { timeout: 5000 });
await panel.getByText("ProposalAudit-Playbook-TH.pdf").waitFor({ timeout: 5000 });   // mock หน่วง 120ms
ok(await panel.getByText("ProposalAudit-Playbook-TH.pptx").count() === 1, "Settings แสดงไฟล์ที่มีอยู่");
ok(await panel.getByRole("button", { name: /^ลบ/ }).count() === 2, "มีปุ่มลบทุกไฟล์");
await page.screenshot({ path: "e2e-playbook-settings.png", fullPage: true });

await browser.close();
console.log(fails.length ? `\n❌ FAIL ${fails.length}: ${fails.join(" | ")}` : "\n✅ ผ่านทั้งหมด");
process.exit(fails.length ? 1 : 0);
