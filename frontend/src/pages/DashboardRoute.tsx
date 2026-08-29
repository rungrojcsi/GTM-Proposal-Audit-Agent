/* F42 — ห่อ DashboardView ให้ใช้ router แทน callback ที่สลับ state เอง */
import { useNavigate } from "react-router-dom";
import DashboardView from "./DashboardPage";

export default function DashboardRoute() {
  const navigate = useNavigate();
  return (
    <DashboardView
      onOpen={(id) => navigate(`/library/${id}`)}
      onGoLibrary={() => navigate("/library")}
    />
  );
}
