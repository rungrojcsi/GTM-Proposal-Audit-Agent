/* ============================================================
   รวม migration ที่ยังค้าง — วางทั้งไฟล์นี้ครั้งเดียวได้เลย
   ============================================================
   ใช้เมื่อ Managed Identity ของ Function App ไม่มีสิทธิ์ CREATE TABLE
   (ปุ่ม Settings > Database schema จะขึ้น "CREATE TABLE permission denied")

   วิธีรัน (ไม่ต้องติดตั้งอะไร):
     Azure Portal > SQL databases > proposal_evaluator > Query editor (preview)
     > Login ด้วย Entra ID (บัญชีที่เป็น SQL admin) > วางไฟล์นี้ > Run

   ไม่มีคำสั่ง GO -> วางได้ทั้ง Portal Query editor และ SSMS / Azure Data Studio
   idempotent — รันซ้ำได้ ไม่แตะข้อมูลเดิม
   ตรวจผลหลังรัน: กลับไปที่ Settings > Database schema > "ตรวจใหม่" ต้องขึ้น "ครบ"
   ============================================================ */

/* ============================================================
   Migration — AuditLog (Wave 1 / C01)
   ============================================================
   บันทึกร่องรอยการตรวจสอบ (audit trail) ของการกระทำที่ "เขียน" ข้อมูลสำคัญ
   ครอบ 5 การกระทำตามขอบเขต D2:
     content.update  — แก้ราคา/ต้นทุน/ตาราง/กำลังคน
     content.verify  — กดยืนยันข้อมูลการเงิน
     thread.rename   — แก้ชื่อ client/project
     thread.delete   — ลบโปรเจค
     user.role       — เปลี่ยน role ของผู้ใช้
     role.perms      — แก้ matrix สิทธิ์ของ role
   ไม่บันทึกการอ่าน (ปริมาณ 30-50 request/เดือน — บันทึกแล้วไม่ช่วยอะไร)

   ออกแบบสำคัญ: ไม่ผูก FK ไปตารางเป้าหมาย และเก็บ target_label ซ้ำไว้
   เพื่อให้ audit ของ "การลบ" ยังอ่านรู้เรื่องหลังข้อมูลต้นทางหายไปแล้ว
   (ถ้าผูก FK แข็ง แถว audit จะถูกลบตามไปด้วย = ไร้ประโยชน์)

   Idempotent — รันซ้ำได้ ไม่แตะตารางเดิม (Constraint C4 additive-only)
   ============================================================ */

IF OBJECT_ID('dbo.AuditLog', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.AuditLog (
        audit_id       UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
        occurred_at    DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),

        -- ผู้กระทำ: มาจาก x-ms-client-principal ฝั่ง server เท่านั้น (ห้ามรับจาก client body)
        -- ไม่ผูก FK ไป Users เพื่อให้ audit รอดเมื่อ user ถูกลบ
        actor_user_id  UNIQUEIDENTIFIER NULL,
        actor_email    NVARCHAR(256)    NULL,
        actor_role     NVARCHAR(50)     NULL,
        -- S03 — IP ผู้เรียก (ตัวขวาสุดของ x-forwarded-for). สำคัญขึ้นเมื่อระบบเปิดสาธารณะ
        -- ไม่พึ่ง VPN แล้ว: ใช้สืบว่าการแก้ข้อมูลมาจากที่ไหน
        actor_ip       NVARCHAR(45)     NULL,   -- 45 = ความยาวสูงสุดของ IPv6 แบบข้อความ

        action         NVARCHAR(50)     NOT NULL,   -- content.update | content.verify | thread.rename | ...
        target_type    NVARCHAR(30)     NOT NULL,   -- thread | user | role
        target_id      NVARCHAR(100)    NULL,       -- id ของเป้าหมาย (string เพื่อรับได้ทุกชนิด key)
        target_label   NVARCHAR(300)    NULL,       -- ticket_no / email — อ่านรู้เรื่องหลังเป้าหมายถูกลบ

        before_json    NVARCHAR(MAX)    NULL,       -- ค่าเดิม (NULL = สร้างใหม่)
        after_json     NVARCHAR(MAX)    NULL        -- ค่าใหม่ (NULL = ลบ)
    );

    CREATE INDEX IX_AuditLog_target   ON dbo.AuditLog (target_type, target_id, occurred_at DESC);
    CREATE INDEX IX_AuditLog_actor    ON dbo.AuditLog (actor_email, occurred_at DESC);
    CREATE INDEX IX_AuditLog_occurred ON dbo.AuditLog (occurred_at DESC);
END

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

/* ---- ตรวจผล ---- */
SELECT name AS created_table FROM sys.tables
WHERE name IN ('AuditLog','CoachJobs') ORDER BY name;
