/* H01 — เส้นทางของแอป (react-router) ทำให้แชร์ลิงก์ผลประเมินได้และปุ่ม Back ของ browser ทำงาน
   ทุกเส้นทางห่อด้วย RouteGuard ที่เช็กสิทธิ์จาก /api/me (H04) และแสดงหน้าอธิบายถ้าไม่มีสิทธิ์ (H05) */
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import App from "./App";
import RouteGuard from "./components/RouteGuard";
import DashboardRoute from "./pages/DashboardRoute";
import EvaluatePage from "./pages/EvaluatePage";
import HomeRedirect from "./pages/HomeRedirect";
import LibraryDetailRoute from "./pages/LibraryDetailRoute";
import LibraryPage from "./pages/LibraryPage";
import PlaybookPage from "./pages/PlaybookPage";
import ProposalDetailPage from "./pages/ProposalDetailPage";
import ProposalsPage from "./pages/ProposalsPage";
import SettingsPage from "./pages/SettingsPage";
import "./theme.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<HomeRedirect />} />
          <Route path="evaluate" element={<RouteGuard page="evaluate" label="New Evaluation"><EvaluatePage /></RouteGuard>} />
          <Route path="proposals" element={<RouteGuard page="proposals" label="Evaluation Results"><ProposalsPage /></RouteGuard>} />
          <Route path="proposals/:threadId" element={<RouteGuard page="proposals" label="Evaluation Results"><ProposalDetailPage /></RouteGuard>} />
          <Route path="library" element={<RouteGuard page="library" label="Proposal Library"><LibraryPage /></RouteGuard>} />
          <Route path="library/:threadId" element={<RouteGuard page="library" label="Proposal Library"><LibraryDetailRoute /></RouteGuard>} />
          <Route path="dashboard" element={<RouteGuard page="dashboard" label="COS Dashboard"><DashboardRoute /></RouteGuard>} />
          {/* Playbook — เปิดให้ทุกคน ไม่ห่อ RouteGuard โดยเจตนา (ไม่มี page permission ให้ปิด) */}
          <Route path="playbook" element={<PlaybookPage />} />
          <Route path="settings" element={<RouteGuard page="settings" label="Settings"><SettingsPage /></RouteGuard>} />
          {/* URL ที่ไม่รู้จัก -> กลับหน้าแรกที่ผู้ใช้เข้าได้ */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
