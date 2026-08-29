/* ============================================================
   Migration — CoachJobs (Wave 3 / G01)
   ============================================================
   ย้าย Presentation Coach จาก "เรียก LLM แบบ synchronous ใน HTTP request"
   มาเป็นงานคิวเบื้องหลัง เพราะ:
     - provider = local LLM ใช้เวลา 20-30 วินาทีขึ้นไปต่อ call
     - Azure Functions HTTP มีเพดานราว 230 วินาที -> เสี่ยง timeout เงียบ ๆ
   frontend จะได้ job_id กลับไปแล้ว poll สถานะ (แบบเดียวกับ /api/evaluate)

   content_hash เก็บไว้เพื่อ "ใช้ผลเดิมซ้ำ" เมื่อ thread + กลุ่มผู้ฟัง + เนื้อหา
   เหมือนเดิมเป๊ะ -> ไม่ต้องเรียก LLM ใหม่ (คุมต้นทุนโทเคน ตาม Business Goal G6)
   และจะไม่ใช้ผลเดิมโดยอัตโนมัติเมื่อมี version ใหม่ (hash เปลี่ยน)

   Idempotent — รันซ้ำได้ ไม่แตะตารางเดิม (Constraint C4 additive-only)
   ============================================================ */

IF OBJECT_ID('dbo.CoachJobs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.CoachJobs (
        job_id         UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
        thread_id      UNIQUEIDENTIFIER NOT NULL
                       REFERENCES dbo.ProposalThreads(thread_id),
        -- คำอธิบายกลุ่มผู้ฟัง (จาก preset map หรือข้อความที่ผู้ใช้พิมพ์เอง)
        audience_desc  NVARCHAR(500)    NOT NULL,
        -- sha256 ของเนื้อหา proposal ที่ใช้สร้าง -> ใช้ตัดสินว่า reuse ได้ไหม
        content_hash   NVARCHAR(64)     NULL,
        status         NVARCHAR(20)     NOT NULL DEFAULT 'Processing',  -- Processing|Done|Failed
        guideline      NVARCHAR(MAX)    NULL,
        error_message  NVARCHAR(500)    NULL,
        requested_by   NVARCHAR(256)    NULL,   -- อีเมลจาก SSO principal (ไม่รับจาก client)
        created_at     DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
        completed_at   DATETIME2        NULL
    );

    -- ใช้ค้นผลเดิมที่ reuse ได้: thread + ผู้ฟัง + เนื้อหา ตรงกันและ Done แล้ว
    CREATE INDEX IX_CoachJobs_reuse
        ON dbo.CoachJobs (thread_id, content_hash, status) INCLUDE (audience_desc);
END
GO
