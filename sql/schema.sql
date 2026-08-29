/* =====================================================================
   Proposal Evaluator — Azure SQL schema (T-SQL)
   Data model จาก SA Phase 3
   Entities: Users -> ProposalThreads -> Submissions -> EvaluationResults
             -> (ScoreDetails, Recommendations)
   ===================================================================== */

/* ---------- Users (F01/F02) ---------- */
CREATE TABLE dbo.Users (
    user_id        UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    entra_oid      NVARCHAR(100)    NOT NULL UNIQUE,   -- Entra ID object id
    email          NVARCHAR(256)    NOT NULL,
    display_name   NVARCHAR(200)    NULL,
    role           NVARCHAR(20)     NOT NULL DEFAULT 'submitter'
                   CHECK (role IN ('submitter','analyst','admin')),
    created_at     DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
);

/* ---------- ProposalThreads (F05 — จัดกลุ่ม version) ---------- */
CREATE TABLE dbo.ProposalThreads (
    thread_id      UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    ticket_no      NVARCHAR(20)     NULL UNIQUE,        -- PE-YYYY-NNNNN (1 ต่อ project)
    client_name    NVARCHAR(200)    NULL,
    project_name   NVARCHAR(200)    NULL,
    -- nullable จนกว่าจะ wire Entra auth (F02) -> owner_id มาจาก claim; ตอนนี้ยอม NULL
    owner_id       UNIQUEIDENTIFIER NULL
                   REFERENCES dbo.Users(user_id),
    created_at     DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
);

/* ticket running number — ยาวไม่ reset (year เป็น prefix ตอน format) */
CREATE SEQUENCE dbo.seq_ticket AS INT START WITH 1 INCREMENT BY 1;

/* ---------- Submissions (F03/F04) — 1 record ต่อ 1 upload/version ---------- */
CREATE TABLE dbo.Submissions (
    submission_id  UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    thread_id      UNIQUEIDENTIFIER NOT NULL
                   REFERENCES dbo.ProposalThreads(thread_id),
    version_no     INT              NOT NULL,
    filename       NVARCHAR(400)    NOT NULL,
    content_type   NVARCHAR(100)    NOT NULL,          -- application/pdf | .pptx
    blob_url       NVARCHAR(1000)   NOT NULL,          -- ไฟล์ต้นฉบับใน Blob
    file_size      BIGINT           NULL,
    content_hash   CHAR(64)         NULL,              -- SHA-256 ของ normalized text (F24 cache)
    text_content   NVARCHAR(MAX)    NULL,              -- extracted text (ใช้ทำ improvement-gate F25)
    lang           CHAR(2)          NULL               -- ภาษา output ของ audit: 'th' | 'en'
                   CHECK (lang IN ('th','en')),
    score_source   NVARCHAR(20)     NULL               -- 'evaluated' | 'reused' (F24/F25)
                   CHECK (score_source IN ('evaluated','reused')),
    status         NVARCHAR(20)     NOT NULL DEFAULT 'Evaluating'
                   CHECK (status IN ('Evaluating','Evaluated','Accepted','Failed')),
    created_at     DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_thread_version UNIQUE (thread_id, version_no)
);

/* ---------- EvaluationResults (F10/F11/F12) ---------- */
CREATE TABLE dbo.EvaluationResults (
    eval_id        UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    submission_id  UNIQUEIDENTIFIER NOT NULL
                   REFERENCES dbo.Submissions(submission_id),
    overall_score  DECIMAL(4,2)     NULL,              -- 0.00-10.00 (คำนวณใน backend)
    verdict        NVARCHAR(20)     NULL
                   CHECK (verdict IN ('Strong','Adequate','Weak','Critical')),
    skeleton_md    NVARCHAR(MAX)    NULL,              -- Skeleton structure ที่แนะนำ
    raw_llm_json   NVARCHAR(MAX)    NULL,              -- JSON ดิบจาก GPT (audit)
    model_name     NVARCHAR(100)    NULL,              -- e.g. gpt-4o
    created_at     DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
);

/* ---------- ScoreDetails (per slide/section) ---------- */
CREATE TABLE dbo.ScoreDetails (
    detail_id      UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    eval_id        UNIQUEIDENTIFIER NOT NULL
                   REFERENCES dbo.EvaluationResults(eval_id) ON DELETE CASCADE,
    slide_section  NVARCHAR(200)    NOT NULL,          -- e.g. "4. Pain Statement"
    tier           NVARCHAR(20)     NOT NULL CHECK (tier IN ('Critical','Important','Optional')),
    score_1_10     INT              NOT NULL CHECK (score_1_10 BETWEEN 0 AND 10),
    coverage       NVARCHAR(1000)   NULL               -- submitted coverage note
);

/* ---------- Recommendations (F13) ---------- */
CREATE TABLE dbo.Recommendations (
    rec_id         UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    eval_id        UNIQUEIDENTIFIER NOT NULL
                   REFERENCES dbo.EvaluationResults(eval_id) ON DELETE CASCADE,
    priority       NVARCHAR(20)     NOT NULL CHECK (priority IN ('Critical','Important','Optional')),
    rec_text       NVARCHAR(2000)   NOT NULL,
    slide_ref      NVARCHAR(100)    NULL
);

/* ---------- Comments (F26) — user-entered comments ต่อ version/thread ---------- */
CREATE TABLE dbo.Comments (
    comment_id     UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    thread_id      UNIQUEIDENTIFIER NOT NULL
                   REFERENCES dbo.ProposalThreads(thread_id),
    submission_id  UNIQUEIDENTIFIER NULL          -- ผูก version (NULL = comment ระดับ thread)
                   REFERENCES dbo.Submissions(submission_id),
    author         NVARCHAR(200)    NULL,
    comment_text   NVARCHAR(2000)   NOT NULL,
    created_at     DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
);

/* ---------- ProposalContent (F30-F41 Proposal Library) — 1:1 ต่อ thread ---------- */
CREATE TABLE dbo.ProposalContent (
    content_id       UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    thread_id        UNIQUEIDENTIFIER NOT NULL UNIQUE
                     REFERENCES dbo.ProposalThreads(thread_id),
    submission_id    UNIQUEIDENTIFIER NULL             -- version ล่าสุดที่ extract
                     REFERENCES dbo.Submissions(submission_id),
    price_amount     DECIMAL(18,2)    NULL,
    price_currency   NVARCHAR(10)     NULL,
    cost_amount      DECIMAL(18,2)    NULL,             -- ต้นทุนภายใน — proposal คู่แข่งมักไม่มี
    cost_currency    NVARCHAR(10)     NULL,
    duration_months  DECIMAL(6,1)     NULL,
    milestones       NVARCHAR(MAX)    NULL,             -- JSON: [{"name","timeframe"}]
    manpower         NVARCHAR(MAX)    NULL,             -- JSON: [{"role","count","man_days"}]
    solution_type    NVARCHAR(100)    NULL,
    industry         NVARCHAR(100)    NULL,
    deal_outcome     NVARCHAR(20)     NOT NULL DEFAULT 'Pending'
                     CHECK (deal_outcome IN ('Won','Lost','Pending')),
    source           NVARCHAR(20)     NOT NULL DEFAULT 'extracted'
                     CHECK (source IN ('extracted','manual','pm_system')),
    field_confidence NVARCHAR(MAX)    NULL,             -- JSON: {"price":"high|medium|low",...}
    extracted_hash   CHAR(64)         NULL,             -- content_hash ของ text ที่ extract ล่าสุด
    content_stale    BIT              NOT NULL DEFAULT 0, -- verified แล้วแต่มี version ใหม่ยังไม่ทบทวน
    verify_status    NVARCHAR(20)     NOT NULL DEFAULT 'pending_verify'
                     CHECK (verify_status IN ('pending_verify','verified')),
    verified_by      NVARCHAR(200)    NULL,
    verified_at      DATETIME2        NULL,
    /* SharePoint sync state (M3 — worker มาเสียบทีหลังเมื่อ admin consent พร้อม) */
    sharepoint_url   NVARCHAR(1000)   NULL,
    sync_status      NVARCHAR(20)     NOT NULL DEFAULT 'pending'
                     CHECK (sync_status IN ('pending','synced','failed')),
    metadata_dirty   BIT              NOT NULL DEFAULT 1,
    retry_count      INT              NOT NULL DEFAULT 0,
    synced_at        DATETIME2        NULL,
    last_error       NVARCHAR(2000)   NULL,
    created_at       DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at       DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME()
);

/* ---------- Indexes for dashboard/history (F17/F18/F19) ---------- */
CREATE INDEX IX_Submissions_thread   ON dbo.Submissions(thread_id, version_no);
CREATE INDEX IX_Submissions_hash     ON dbo.Submissions(thread_id, content_hash);
CREATE INDEX IX_Eval_submission      ON dbo.EvaluationResults(submission_id);
CREATE INDEX IX_Eval_created         ON dbo.EvaluationResults(created_at);
CREATE INDEX IX_Threads_owner        ON dbo.ProposalThreads(owner_id);
CREATE INDEX IX_Threads_clientproj   ON dbo.ProposalThreads(client_name, project_name);
CREATE INDEX IX_Comments_thread      ON dbo.Comments(thread_id, created_at);
CREATE INDEX IX_Content_outcome      ON dbo.ProposalContent(deal_outcome, verify_status);
CREATE INDEX IX_Content_sync         ON dbo.ProposalContent(sync_status, metadata_dirty);

/* ---------- View: version comparison (F17) ---------- */
GO
CREATE VIEW dbo.vw_ThreadScores AS
SELECT  t.thread_id,
        t.ticket_no,
        t.client_name,
        t.project_name,
        s.submission_id,
        s.version_no,
        s.status,
        s.score_source,
        e.overall_score,
        e.verdict,
        e.created_at AS evaluated_at
FROM        dbo.ProposalThreads   t
JOIN        dbo.Submissions       s ON s.thread_id = t.thread_id
LEFT JOIN   dbo.EvaluationResults e ON e.submission_id = s.submission_id;
GO
