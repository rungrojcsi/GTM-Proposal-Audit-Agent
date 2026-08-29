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
GO
