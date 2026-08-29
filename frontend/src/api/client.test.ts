import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  addComment, listProposals, getThread, updateThread, deleteThread,
  prepare, evaluate, listAudit, setUserRole,
} from "./client";

function fakeResponse(body: unknown, ok = true, statusText = "Error") {
  return {
    ok,
    statusText,
    json: async () => body,
  } as Response;
}

describe("post()-based wrappers (via addComment)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("sends POST with JSON content-type and body", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ comments: [] }));
    await addComment("t1", "s1", "hello");
    const [url, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/comments");
    expect(opts.method).toBe("POST");
    expect(opts.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(opts.body)).toEqual({ thread_id: "t1", submission_id: "s1", comment_text: "hello" });
  });

  it("throws the backend error message when response is not ok", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ error: "thread not found" }, false));
    await expect(addComment("t1", "s1", "hello")).rejects.toThrow("thread not found");
  });

  it("falls back to statusText when error body cannot be parsed", async () => {
    const badJsonResponse = {
      ok: false,
      statusText: "Internal Server Error",
      json: async () => { throw new Error("not json"); },
    } as unknown as Response;
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(badJsonResponse);
    await expect(addComment("t1", "s1", "hello")).rejects.toThrow("Internal Server Error");
  });
});

describe("get()-based wrappers (via listProposals / getThread)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("requests cache: no-store to avoid stale dynamic data", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse([]));
    await listProposals();
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(opts.cache).toBe("no-store");
  });

  it("appends scope query param only when provided", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse([]));
    await listProposals("mine");
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/proposals?scope=mine");

    await listProposals();
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[1][0]).toBe("/api/proposals");
  });

  it("getThread hits the correct thread-scoped endpoint", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({}));
    await getThread("t1");
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/threads/t1");
  });
});

describe("PATCH/DELETE wrappers", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("updateThread sends PATCH with client/project body", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ ok: true }));
    await updateThread("t1", "ACME", "ERP");
    const [url, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/threads/t1");
    expect(opts.method).toBe("PATCH");
    expect(JSON.parse(opts.body)).toEqual({ client_name: "ACME", project_name: "ERP" });
  });

  it("deleteThread sends DELETE with no body", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ ok: true }));
    await deleteThread("t1");
    const [url, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/threads/t1");
    expect(opts.method).toBe("DELETE");
  });

  it("setUserRole PATCHes the role onto the user-scoped endpoint", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ ok: true, users: [] }));
    await setUserRole("u1", "manager");
    const [url, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/users/u1");
    expect(JSON.parse(opts.body)).toEqual({ role: "manager" });
  });
});

describe("prepare()", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("uploads the file as multipart form data without a JSON content-type header", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ filename: "f.pdf" }));
    const file = new File([new Blob(["data"])], "f.pdf", { type: "application/pdf" });
    await prepare(file);
    const [url, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/prepare");
    expect(opts.method).toBe("POST");
    expect(opts.body).toBeInstanceOf(FormData);
    expect(opts.body.get("file")).toBe(file);
  });
});

describe("evaluate()", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  const prep = {
    blob_url: "blob://x", filename: "f.pdf", content_type: "application/pdf", file_size: 100,
    content_hash: "hash1", text: "text", suggested_client: "", suggested_project: "", existing: null,
  };

  it("defaults thread_id to empty string and force_new to false when omitted", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ status: "processing" }));
    await evaluate(prep, "ACME", "ERP", "en");
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(opts.body);
    expect(body.thread_id).toBe("");
    expect(body.force_new).toBe(false);
    expect(body.client_name).toBe("ACME");
  });

  it("passes through an explicit thread_id and force_new flag", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ status: "processing" }));
    await evaluate(prep, "ACME", "ERP", "th", "t1", true);
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(opts.body);
    expect(body.thread_id).toBe("t1");
    expect(body.force_new).toBe(true);
    expect(body.lang).toBe("th");
  });
});

describe("listAudit()", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("builds no query string when no filters given", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ ready: true, items: [] }));
    await listAudit();
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/audit");
  });

  it("includes only the filters that were provided", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(fakeResponse({ ready: true, items: [] }));
    await listAudit({ thread_id: "t1", limit: 50 });
    const url = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(url).toContain("thread_id=t1");
    expect(url).toContain("limit=50");
    expect(url).not.toContain("actor=");
  });
});
