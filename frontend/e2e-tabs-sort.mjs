/* e2e — 2 งานรอบนี้ในหน้าผลประเมิน
   (1) แถบแท็บเป็น segmented control จริง + เป็น tablist ตามแบบแผน ARIA (เดินด้วยปุ่มลูกศรได้)
   (2) ตาราง Section Scores เรียงได้ตาม Section / Tier / Score

   รันคู่กับ mock server: VITE_MOCK_API=1 npx vite --port 5199 --strictPort
   แล้ว node e2e-tabs-sort.mjs */
import { chromium } from "playwright";

const BASE = process.env.BASE ?? "http://localhost:5199";
const fails = [];
const ok = (cond, label) => { console.log(`${cond ? "✔" : "✘"} ${label}`); if (!cond) fails.push(label); };

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } });
page.on("pageerror", (e) => fails.push(`pageerror: ${e.message}`));

await page.goto(`${BASE}/proposals`, { waitUntil: "networkidle" });
await page.locator("table.tbl tbody tr").first().click();
await page.waitForSelector('[role="tablist"]', { timeout: 10000 });

/* ---------- 1) แถบแท็บ: โครงสร้าง + หน้าตา ---------- */
const tablist = page.locator('[role="tablist"]');
ok(await tablist.count() === 1, 'แถบแท็บประกาศตัวเป็น role="tablist"');
ok(await page.locator('[role="tab"]').count() === 7, 'มี role="tab" ครบ 7 อัน');
ok(await page.locator('[role="tabpanel"]').count() === 1, 'เนื้อหาอยู่ใน role="tabpanel"');

const activeTab = page.locator('[role="tab"][aria-selected="true"]');
ok(await activeTab.count() === 1, "มีแท็บที่เลือกอยู่ 1 อันเท่านั้น");
ok((await activeTab.innerText()).trim() === "History", "แท็บเริ่มต้นคือ History");

// segmented control = กล่องมีพื้น + ขอบ + มุมโค้ง (เดิมเป็นเส้นใต้บาง ไม่มีพื้น)
const box = await tablist.evaluate((el) => {
  const s = getComputedStyle(el);
  return { bg: s.backgroundColor, radius: s.borderTopLeftRadius, border: s.borderTopWidth, display: s.display };
});
ok(box.display === "inline-flex", `กล่องเป็น inline-flex (ได้ ${box.display})`);
ok(box.bg !== "rgba(0, 0, 0, 0)", `กล่องมีสีพื้น (ได้ ${box.bg})`);
ok(parseFloat(box.radius) >= 8, `กล่องมุมโค้ง ${box.radius}`);
ok(parseFloat(box.border) >= 1, `กล่องมีขอบ ${box.border}`);

// ตัวที่เลือกต้อง "ยกลอย" = มีพื้น + เงา ต่างจากตัวที่ไม่เลือก
const onStyle = await activeTab.evaluate((el) => { const s = getComputedStyle(el); return { bg: s.backgroundColor, shadow: s.boxShadow }; });
const offStyle = await page.locator('[role="tab"][aria-selected="false"]').first()
  .evaluate((el) => { const s = getComputedStyle(el); return { bg: s.backgroundColor, shadow: s.boxShadow }; });
ok(onStyle.bg !== offStyle.bg, `แท็บที่เลือกพื้นต่างจากตัวที่ไม่เลือก (${onStyle.bg} vs ${offStyle.bg})`);
ok(onStyle.shadow !== "none", "แท็บที่เลือกมีเงา (ยกลอย)");
ok(offStyle.shadow === "none", "แท็บที่ไม่เลือกไม่มีเงา");

/* ---------- 2) เดินแท็บด้วยปุ่มลูกศร ---------- */
await activeTab.focus();
await page.keyboard.press("ArrowRight");
ok((await page.locator('[role="tab"][aria-selected="true"]').innerText()).trim() === "Section Scores",
  "ลูกศรขวา -> ไปแท็บถัดไป (Section Scores)");
await page.keyboard.press("ArrowLeft");
ok((await page.locator('[role="tab"][aria-selected="true"]').innerText()).trim() === "History",
  "ลูกศรซ้าย -> กลับแท็บก่อนหน้า");
await page.keyboard.press("End");
// แท็บ Comments ต่อท้ายจำนวนคอมเมนต์ไว้ (เช่น "Comments (2)") จึงเทียบด้วย startsWith
ok((await page.locator('[role="tab"][aria-selected="true"]').innerText()).trim().startsWith("Comments"),
  "End -> แท็บสุดท้าย (Comments)");

/* ---------- 3) ตาราง Section Scores: เรียงได้ ---------- */
await page.getByRole("tab", { name: "Section Scores" }).click();
await page.waitForSelector("table.tbl th button", { timeout: 5000 });

const col = (i) => page.locator("table.tbl tbody tr").evaluateAll((rows, idx) =>
  rows.map((r) => r.children[idx].innerText.trim()), i);
const th = (name) => page.locator("table.tbl thead th", { hasText: name }).locator("button");

const secDefault = await col(0);
ok(secDefault.length === 17, `ตารางมี 17 แถว (ได้ ${secDefault.length})`);
const noOf = (s) => parseInt(s, 10);
ok(secDefault.every((v, i) => i === 0 || noOf(secDefault[i - 1]) <= noOf(v)),
  "ค่าเริ่มต้นเรียงตามเลขหัวข้อ 1→17 (พฤติกรรมเดิมไม่เปลี่ยน)");

await th("Section").click();
const secDesc = await col(0);
ok(noOf(secDesc[0]) === 17 && noOf(secDesc[16]) === 1, `กด Section -> กลับหัว 17→1 (ได้ ${noOf(secDesc[0])}→${noOf(secDesc[16])})`);
ok(await page.locator('table.tbl th[aria-sort="descending"]').count() === 1, 'หัวคอลัมน์ประกาศ aria-sort="descending"');

await th("Tier").click();
const tiers = await col(1);
const RANK = { Critical: 0, Important: 1, Optional: 2 };
ok(tiers.every((v, i) => i === 0 || RANK[tiers[i - 1]] <= RANK[v]),
  `กด Tier -> Critical ก่อน Important ก่อน Optional (ได้ ${tiers.slice(0, 3).join(",")}…)`);

await th("Score").click();
const scores = (await col(2)).map((s) => parseInt(s, 10));
ok(scores.every((v, i) => i === 0 || scores[i - 1] <= v), `กด Score -> คะแนนต่ำก่อน (ได้ ${scores.slice(0, 5).join(",")}…)`);
await th("Score").click();
const scoresDesc = (await col(2)).map((s) => parseInt(s, 10));
ok(scoresDesc.every((v, i) => i === 0 || scoresDesc[i - 1] >= v), `กด Score ซ้ำ -> สลับเป็นคะแนนสูงก่อน (ได้ ${scoresDesc.slice(0, 5).join(",")}…)`);

// Coverage ไม่ควรเรียงได้ (เป็นข้อความยาว เรียงแล้วไม่มีความหมาย)
ok(await page.locator("table.tbl thead th", { hasText: "Coverage" }).locator("button").count() === 0,
  "คอลัมน์ Coverage ไม่มีปุ่มเรียง (ตั้งใจ)");

await page.screenshot({ path: "e2e-tabs-sort.png", fullPage: false });
await page.evaluate(() => document.querySelector('[data-theme]')?.setAttribute("data-theme", "dark"));
await page.screenshot({ path: "e2e-tabs-sort-dark.png", fullPage: false });

await browser.close();
console.log(fails.length ? `\n❌ FAIL ${fails.length}: ${fails.join(" | ")}` : "\n✅ ผ่านทั้งหมด");
process.exit(fails.length ? 1 : 0);
