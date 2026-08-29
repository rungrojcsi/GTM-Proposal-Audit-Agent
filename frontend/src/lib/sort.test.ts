import { describe, it, expect } from "vitest";
import { sortProposals, sortLibrary } from "./sort";
import type { ProposalRow, LibraryRow } from "../api/client";

function proposal(overrides: Partial<ProposalRow>): ProposalRow {
  return {
    thread_id: "t1", ticket_no: "PE-1", client_name: "A", project_name: "P",
    version_no: 1, version_count: 1, status: "Evaluated",
    overall_score: null, verdict: null, score_source: null, evaluated_at: null, owner_name: null,
    ...overrides,
  };
}

function libraryRow(overrides: Partial<LibraryRow>): LibraryRow {
  return {
    thread_id: "t1", ticket_no: "PE-1", client_name: "A", project_name: "P",
    price_amount: null, price_currency: null, cost_amount: null, cost_currency: null,
    duration_months: null, solution_type: null, industry: null, deal_outcome: null,
    verify_status: null, content_stale: null, sync_status: null, updated_at: null,
    version_no: 1, overall_score: null, verdict: null, owner_name: null,
    ...overrides,
  };
}

describe("sortProposals", () => {
  it("sorts by overall_score ascending, missing score treated as -1 (sorts first)", () => {
    const rows = [proposal({ ticket_no: "PE-2", overall_score: 6 }), proposal({ ticket_no: "PE-1", overall_score: null })];
    const sorted = sortProposals(rows, "overall_score", "asc");
    expect(sorted.map((r) => r.ticket_no)).toEqual(["PE-1", "PE-2"]);
  });

  it("sorts by verdict using VERDICT_RANK not alphabetically", () => {
    const rows = [proposal({ ticket_no: "PE-weak", verdict: "Weak" }), proposal({ ticket_no: "PE-strong", verdict: "Strong" })];
    const sorted = sortProposals(rows, "verdict", "desc");
    expect(sorted.map((r) => r.ticket_no)).toEqual(["PE-strong", "PE-weak"]);
  });

  it("falls back to case-insensitive string comparison for text columns", () => {
    const rows = [proposal({ client_name: "bravo" }), proposal({ client_name: "Alpha" })];
    const sorted = sortProposals(rows, "client_name", "asc");
    expect(sorted.map((r) => r.client_name)).toEqual(["Alpha", "bravo"]);
  });

  it("does not mutate the input array", () => {
    const rows = [proposal({ ticket_no: "B" }), proposal({ ticket_no: "A" })];
    const sorted = sortProposals(rows, "ticket_no", "asc");
    expect(sorted).not.toBe(rows);
    expect(rows[0].ticket_no).toBe("B");
  });
});

describe("sortLibrary", () => {
  it("keeps null numeric values last regardless of sort direction", () => {
    const rows = [libraryRow({ ticket_no: "has-price", price_amount: 100 }), libraryRow({ ticket_no: "no-price", price_amount: null })];
    expect(sortLibrary(rows, "price_amount", "asc").map((r) => r.ticket_no)).toEqual(["has-price", "no-price"]);
    expect(sortLibrary(rows, "price_amount", "desc").map((r) => r.ticket_no)).toEqual(["has-price", "no-price"]);
  });

  it("sorts numeric keys correctly when both present", () => {
    const rows = [libraryRow({ ticket_no: "big", price_amount: 500 }), libraryRow({ ticket_no: "small", price_amount: 100 })];
    expect(sortLibrary(rows, "price_amount", "asc").map((r) => r.ticket_no)).toEqual(["small", "big"]);
  });

  it("sorts text columns case-insensitively", () => {
    const rows = [libraryRow({ industry: "banking" }), libraryRow({ industry: "Automotive" })];
    const sorted = sortLibrary(rows, "industry", "asc");
    expect(sorted.map((r) => r.industry)).toEqual(["Automotive", "banking"]);
  });
});
