import { describe, it, expect } from "vitest";
import { scoreVar, initials, fmtMoney, bySectionNo, evalStep, mmss, SCORE_THRESHOLD } from "./format";

describe("scoreVar", () => {
  it("matches backend scoring.map_verdict boundaries (7 / 5 / 3.5)", () => {
    expect(scoreVar(SCORE_THRESHOLD.strong)).toBe("var(--green)");
    expect(scoreVar(6.99)).toBe("var(--amber)");
    expect(scoreVar(SCORE_THRESHOLD.adequate)).toBe("var(--amber)");
    expect(scoreVar(4.99)).toBe("var(--orange)");
    expect(scoreVar(SCORE_THRESHOLD.weak)).toBe("var(--orange)");
    expect(scoreVar(3.49)).toBe("var(--red)");
  });
});

describe("initials", () => {
  it("returns GU for null/undefined/empty name", () => {
    expect(initials(null)).toBe("GU");
    expect(initials(undefined)).toBe("GU");
    expect(initials("   ")).toBe("GU");
  });

  it("returns first 2 chars uppercased and trimmed", () => {
    expect(initials("carlos")).toBe("SO");
    expect(initials("  ann  ")).toBe("AN");
  });
});

describe("fmtMoney", () => {
  it("returns dash for null value", () => {
    expect(fmtMoney(null, "THB")).toBe("-");
  });

  it("formats with locale grouping and currency suffix", () => {
    expect(fmtMoney(1000000, "THB")).toBe("1,000,000 THB");
  });

  it("trims trailing space when currency is null", () => {
    expect(fmtMoney(500, null)).toBe("500");
  });
});

describe("bySectionNo", () => {
  it("sorts by the leading number in slide_section ascending", () => {
    const rows = [{ slide_section: "10. Commercial" }, { slide_section: "2. Pain" }, { slide_section: "1. Hero" }];
    expect(bySectionNo(rows).map((r) => r.slide_section)).toEqual(["1. Hero", "2. Pain", "10. Commercial"]);
  });

  it("treats non-numeric prefix as 0 without crashing", () => {
    const rows = [{ slide_section: "3. Named" }, { slide_section: "Untitled Section" }];
    expect(bySectionNo(rows)[0].slide_section).toBe("Untitled Section");
  });

  it("does not mutate the original array", () => {
    const rows = [{ slide_section: "2. B" }, { slide_section: "1. A" }];
    const sorted = bySectionNo(rows);
    expect(sorted).not.toBe(rows);
    expect(rows[0].slide_section).toBe("2. B"); // ต้นฉบับไม่เปลี่ยน
  });
});

describe("evalStep", () => {
  it("returns the queued message under 15s", () => {
    expect(evalStep(0)).toContain("เข้าคิว");
    expect(evalStep(14)).toContain("เข้าคิว");
  });

  it("returns the scoring message between 15 and 75s", () => {
    expect(evalStep(15)).toContain("17 หัวข้อ");
    expect(evalStep(74)).toContain("17 หัวข้อ");
  });

  it("returns the summarizing message between 75 and 180s", () => {
    expect(evalStep(75)).toContain("จุดแข็ง");
    expect(evalStep(179)).toContain("จุดแข็ง");
  });

  it("returns the almost-done message at 180s and beyond", () => {
    expect(evalStep(180)).toContain("ใกล้เสร็จแล้ว");
    expect(evalStep(999)).toContain("ใกล้เสร็จแล้ว");
  });
});

describe("mmss", () => {
  it("pads minutes and seconds to 2 digits", () => {
    expect(mmss(5)).toBe("00:05");
    expect(mmss(65)).toBe("01:05");
  });

  it("handles exact minute boundaries", () => {
    expect(mmss(120)).toBe("02:00");
  });
});
