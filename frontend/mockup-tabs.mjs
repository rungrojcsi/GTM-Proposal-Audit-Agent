/* mockup ชั่วคราว — เทียบ 4 แบบของแถบแท็บในหน้าผลประเมิน (ยังไม่แตะโค้ดจริง)
   ใช้ token จาก src/theme.css ตัวจริง เพื่อให้สีและระยะตรงกับแอป
   รัน: node mockup-tabs.mjs  ->  ได้ mockup-tabs-light.png / mockup-tabs-dark.png */
import { readFileSync } from "node:fs";
import { chromium } from "playwright";

const theme = readFileSync("src/theme.css", "utf-8");
const TABS = ["History", "Section Scores", "Strengths & Gaps", "Recommendations", "Skeleton", "Presentation Coach", "Comments"];
const ACTIVE = 1;                     // Section Scores = แท็บที่เลือกอยู่
const COUNT = { "Section Scores": 17, Recommendations: 8, Comments: 3 };

const css = `
${theme}
body { padding: 34px 40px 44px; }
.wrap { max-width: 1000px; }
.variant { margin-bottom: 46px; }
.vname { font-size: 13px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); margin-bottom: 4px; }
.vdesc { font-size: 13px; color: var(--text-2); margin-bottom: 14px; }
.body-card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 18px 20px; font-size: 13.5px; color: var(--text-2); }

/* ---------- A · ปัจจุบัน (ของจริงวันนี้) ---------- */
.a-tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--border); margin-bottom: 18px; overflow-x: auto; }
.a-tab { padding: 11px 16px; border: none; border-bottom: 2px solid transparent; background: transparent; font-size: 14px; font-weight: 500; color: var(--text-2); white-space: nowrap; margin-bottom: -1px; }
.a-tab.on { color: var(--primary); font-weight: 700; border-bottom-color: var(--primary); }

/* ---------- B · Segmented control ---------- */
.b-tabs { display: inline-flex; gap: 4px; padding: 4px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px; margin-bottom: 18px; max-width: 100%; overflow-x: auto; }
.b-tab { display: flex; align-items: center; gap: 7px; padding: 8px 14px; border: 1px solid transparent; border-radius: 9px; background: transparent; font-size: 13.5px; font-weight: 600; color: var(--text-2); white-space: nowrap; }
.b-tab.on { background: var(--surface); border-color: var(--border-strong); color: var(--primary); box-shadow: 0 1px 2px rgba(16,24,40,.06), 0 2px 8px rgba(16,24,40,.08); }
.b-badge { font-size: 11px; font-weight: 800; padding: 1px 6px; border-radius: 999px; background: var(--surface-2); color: var(--text-3); }
.b-tab.on .b-badge { background: var(--primary-soft); color: var(--primary); }

/* ---------- C · Folder tabs (แผ่นซ้อน) ---------- */
.c-wrap { margin-bottom: 0; }
.c-tabs { display: flex; gap: 3px; align-items: flex-end; padding-left: 10px; overflow-x: auto; }
.c-tab { padding: 10px 15px 11px; border: 1px solid var(--border); border-bottom: none; border-radius: 10px 10px 0 0; background: var(--surface-2); font-size: 13.5px; font-weight: 600; color: var(--text-2); white-space: nowrap; position: relative; top: 1px; }
.c-tab.on { background: var(--surface); color: var(--primary); font-weight: 700; padding-top: 13px; padding-bottom: 12px; top: 0; box-shadow: 0 -2px 6px rgba(16,24,40,.05); }
.c-tab.on::after { content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: var(--surface); }
.c-body { background: var(--surface); border: 1px solid var(--border); border-radius: 0 14px 14px 14px; box-shadow: var(--shadow); padding: 18px 20px; font-size: 13.5px; color: var(--text-2); position: relative; }

/* ---------- D · Underline หนา + badge (ต่อยอดของเดิม) ---------- */
.d-tabs { display: flex; gap: 4px; border-bottom: 2px solid var(--border); margin-bottom: 18px; overflow-x: auto; }
.d-tab { display: flex; align-items: center; gap: 7px; padding: 11px 15px 12px; border: none; border-bottom: 3px solid transparent; border-radius: 8px 8px 0 0; background: transparent; font-size: 14px; font-weight: 600; color: var(--text-2); white-space: nowrap; margin-bottom: -2px; }
.d-tab.on { color: var(--primary); font-weight: 800; border-bottom-color: var(--primary); background: var(--primary-soft); }
.d-badge { font-size: 11px; font-weight: 800; padding: 1px 6px; border-radius: 999px; background: var(--surface-2); color: var(--text-3); }
.d-tab.on .d-badge { background: var(--surface); color: var(--primary); }
`;

function tabsHtml(cls, { badge = false } = {}) {
  return TABS.map((t, i) => {
    const on = i === ACTIVE ? " on" : "";
    const n = COUNT[t];
    const b = badge && n ? `<span class="${cls[0]}-badge">${n}</span>` : "";
    return `<button class="${cls}${on}">${t}${b}</button>`;
  }).join("");
}

const bodyText = "17 หัวข้อ · เรียงได้ตาม Section / Tier / Score";

const html = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head>
<body><div id="root"><div class="wrap">

  <div class="variant">
    <div class="vname">A · ปัจจุบัน (ของจริงวันนี้)</div>
    <div class="vdesc">ขีดใต้บาง 2px พื้นโปร่ง — ปัญหาที่ Boss เจอ: อ่านเหมือนหัวข้อ ไม่เหมือนปุ่มกดได้</div>
    <div class="a-tabs">${tabsHtml("a-tab")}</div>
    <div class="body-card">${bodyText}</div>
  </div>

  <div class="variant">
    <div class="vname">B · Segmented control</div>
    <div class="vdesc">กล่องพื้นเทาครอบทั้งชุด + ตัวที่เลือกเป็นการ์ดขาวยกลอย — สื่อ “นี่คือชุดตัวเลือกให้กด” ทันที · มี badge จำนวน</div>
    <div class="b-tabs">${tabsHtml("b-tab", { badge: true })}</div>
    <div class="body-card">${bodyText}</div>
  </div>

  <div class="variant c-wrap">
    <div class="vname">C · Folder tabs (แผ่นซ้อน)</div>
    <div class="vdesc">แท็บที่เลือกเชื่อมเป็นแผ่นเดียวกับการ์ดเนื้อหา ตัวที่ไม่เลือกจมลงไปด้านหลัง — ตรงความหมาย “แท็บ” ที่สุด</div>
    <div class="c-tabs">${tabsHtml("c-tab")}</div>
    <div class="c-body">${bodyText}</div>
  </div>

  <div class="variant" style="margin-top:46px">
    <div class="vname">D · Underline หนา + พื้นจาง + badge</div>
    <div class="vdesc">ต่อยอดของเดิม: ขีดใต้ 3px, ตัวที่เลือกมีพื้นสีจาง, เพิ่ม badge จำนวน — เปลี่ยนน้อยสุด</div>
    <div class="d-tabs">${tabsHtml("d-tab", { badge: true })}</div>
    <div class="body-card">${bodyText}</div>
  </div>

</div></div></body></html>`;

const browser = await chromium.launch();
for (const theme of ["light", "dark"]) {
  const page = await browser.newPage({ viewport: { width: 1120, height: 1180 }, deviceScaleFactor: 2 });
  await page.setContent(html);
  await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
  await page.evaluate((t) => { document.body.style.background = t === "dark" ? "#0c1626" : "#eef1f6"; }, theme);
  await page.screenshot({ path: `mockup-tabs-${theme}.png`, fullPage: true });
  console.log(`เขียนแล้ว: mockup-tabs-${theme}.png`);
}
await browser.close();
