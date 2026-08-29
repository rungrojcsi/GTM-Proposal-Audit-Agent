/* F44-F46 / R2 / R3 / S02 / C05 — หน้า Settings (ประกอบแผงย่อย) */
import { useApp } from "../AppContext";
import AuditTrail from "../components/AuditTrail";
import AuditDefaults from "../settings/AuditDefaults";
import DbSchema from "../settings/DbSchema";
import LlmProviderSettings from "../settings/LlmProviderSettings";
import MasterList from "../settings/MasterList";
import NetworkAccessSettings from "../settings/NetworkAccessSettings";
import PlaybookFiles from "../settings/PlaybookFiles";
import RolesPermissions from "../settings/RolesPermissions";
import UserManagement from "../settings/UserManagement";

export function SettingsView() {
  const { me } = useApp();
  if (!me) return null;
  return (
    <>
      <div className="h-title">Settings</div>
      <div className="h-sub">Master data, audit defaults, and user access — Master Admin only.</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        <DbSchema />
        <NetworkAccessSettings />
        <AuditTrail />
        <LlmProviderSettings />
        <PlaybookFiles />
        <UserManagement myEmail={me.email} />
        <RolesPermissions />
        <div className="grid grid-2">
          <MasterList category="solution_type" title="Solution Type" />
          <MasterList category="industry" title="Industry" />
        </div>
        <AuditDefaults />
      </div>
    </>
  );
}

/* E07 — บอกขั้นตอนตามเวลาที่ผ่านไป ให้ผู้ใช้รู้ว่าระบบยังทำงาน ไม่ใช่ค้าง */

export default SettingsView;
