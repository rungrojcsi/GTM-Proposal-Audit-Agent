/* =====================================================================
   Migration — Proposal Library (F30-F41, SA Phase 3-4 2026-07-17)
   เพิ่ม dbo.ProposalContent: project content ต่อ thread (1:1)
   + โครง SharePoint sync state (M3 — deploy ทีหลังเมื่อ admin พร้อม)
   รันกับ live DB ได้เลย (idempotent ผ่าน IF NOT EXISTS)
   ===================================================================== */

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'ProposalContent' AND schema_id = SCHEMA_ID('dbo'))
BEGIN
CREATE TABLE dbo.ProposalContent (
    content_id       UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    thread_id        UNIQUEIDENTIFIER NOT NULL UNIQUE
                     REFERENCES dbo.ProposalThreads(thread_id),
    submission_id    UNIQUEIDENTIFIER NULL             -- version ล่าสุดที่ extract
                     REFERENCES dbo.Submissions(submission_id),

    /* ---- project content (F30 extract / F33 edit) ---- */
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

    /* ---- extraction/verify state ---- */
    source           NVARCHAR(20)     NOT NULL DEFAULT 'extracted'
                     CHECK (source IN ('extracted','manual','pm_system')),
    field_confidence NVARCHAR(MAX)    NULL,             -- JSON: {"price":"high|medium|low",...}
    extracted_hash   CHAR(64)         NULL,             -- content_hash ของ text ที่ extract ล่าสุด
    content_stale    BIT              NOT NULL DEFAULT 0, -- verified แล้วแต่มี version ใหม่ยังไม่ทบทวน
    verify_status    NVARCHAR(20)     NOT NULL DEFAULT 'pending_verify'
                     CHECK (verify_status IN ('pending_verify','verified')),
    verified_by      NVARCHAR(200)    NULL,
    verified_at      DATETIME2        NULL,

    /* ---- SharePoint sync state (M3 — worker มาเสียบทีหลัง) ---- */
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
CREATE INDEX IX_Content_outcome ON dbo.ProposalContent(deal_outcome, verify_status);
CREATE INDEX IX_Content_sync    ON dbo.ProposalContent(sync_status, metadata_dirty);
END
