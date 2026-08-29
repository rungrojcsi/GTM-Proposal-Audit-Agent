/* =====================================================================
   Migration — RBAC + Settings (F43-F48, SA 2026-07-17)
   - เปลี่ยน role enum เป็น 4 ระดับสะสม: user < manager < management < admin
   - MasterData: รายการ Solution Type / Industry (dropdown ใน Library)
   - AppSettings: audit defaults (default lang, currency)
   - master admin คนแรก: hardcode email ของ Boss
   idempotent — รันซ้ำได้
   ===================================================================== */

/* ---------- Users.role: ขยายเป็น 4 ระดับ ---------- */
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE parent_object_id = OBJECT_ID('dbo.Users') AND definition LIKE '%submitter%')
BEGIN
    DECLARE @cn NVARCHAR(200) = (SELECT name FROM sys.check_constraints WHERE parent_object_id = OBJECT_ID('dbo.Users') AND definition LIKE '%submitter%');
    EXEC('ALTER TABLE dbo.Users DROP CONSTRAINT ' + @cn);
    -- map ค่าเดิม -> ใหม่
    UPDATE dbo.Users SET role = 'user'       WHERE role = 'submitter';
    UPDATE dbo.Users SET role = 'manager'    WHERE role = 'analyst';
END

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE parent_object_id = OBJECT_ID('dbo.Users') AND definition LIKE '%management%')
BEGIN
    ALTER TABLE dbo.Users ADD CONSTRAINT CK_Users_role
        CHECK (role IN ('user','manager','management','admin'));
END

-- default role ของ user ใหม่ = 'user'
IF EXISTS (SELECT 1 FROM sys.default_constraints WHERE parent_object_id = OBJECT_ID('dbo.Users') AND COL_NAME(parent_object_id, parent_column_id) = 'role')
BEGIN
    DECLARE @dn NVARCHAR(200) = (SELECT name FROM sys.default_constraints WHERE parent_object_id = OBJECT_ID('dbo.Users') AND COL_NAME(parent_object_id, parent_column_id) = 'role');
    EXEC('ALTER TABLE dbo.Users DROP CONSTRAINT ' + @dn);
END
ALTER TABLE dbo.Users ADD CONSTRAINT DF_Users_role DEFAULT 'user' FOR role;

/* ---------- MasterData (Solution Type / Industry) ---------- */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'MasterData' AND schema_id = SCHEMA_ID('dbo'))
BEGIN
CREATE TABLE dbo.MasterData (
    id          UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID() PRIMARY KEY,
    category    NVARCHAR(30)     NOT NULL CHECK (category IN ('solution_type','industry')),
    value       NVARCHAR(100)    NOT NULL,
    sort_order  INT              NOT NULL DEFAULT 0,
    active      BIT              NOT NULL DEFAULT 1,
    created_at  DATETIME2        NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_MasterData UNIQUE (category, value)
);
END

/* ---------- AppSettings (key-value: audit defaults) ---------- */
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'AppSettings' AND schema_id = SCHEMA_ID('dbo'))
BEGIN
CREATE TABLE dbo.AppSettings (
    setting_key    NVARCHAR(50)   NOT NULL PRIMARY KEY,
    setting_value  NVARCHAR(500)  NULL,
    updated_at     DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME()
);
INSERT INTO dbo.AppSettings (setting_key, setting_value) VALUES
    ('default_lang', 'th'),
    ('default_currency', 'THB');
END

/* ---------- Master Admin คนแรก (Boss) ---------- */
MERGE dbo.Users AS t
USING (SELECT 'owner@example.com' AS email) AS s
ON LOWER(t.email) = s.email
WHEN MATCHED THEN UPDATE SET role = 'admin'
WHEN NOT MATCHED THEN
    INSERT (entra_oid, email, display_name, role)
    VALUES ('bootstrap-admin', 'owner@example.com', 'Owner S.', 'admin');
