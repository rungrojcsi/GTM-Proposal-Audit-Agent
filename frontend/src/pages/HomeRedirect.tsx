/* H04 — เข้า "/" แล้วพาไปหน้าแรกที่ role นี้เข้าได้จริง
   (เดิม App ตั้งค่า nav เริ่มต้นเป็น "evaluate" แล้วค่อยย้ายถ้าไม่มีสิทธิ์ — ตอนนี้ทำที่ router) */
import { Navigate } from "react-router-dom";
import type { PageKey } from "../api/client";
import { useApp } from "../AppContext";

const ORDER: PageKey[] = ["evaluate", "proposals", "library", "dashboard", "settings"];

export default function HomeRedirect() {
  const { me } = useApp();
  if (!me) return <div className="state">Loading…</div>;
  const first = ORDER.find((p) => me.access?.[p]);
  // ไม่มีสิทธิ์หน้าใดเลย -> พาไป Playbook (เมนูที่เปิดให้ทุกคน) แทนหน้า Forbidden ที่ไม่มีทางออก
  return <Navigate to={first ? `/${first}` : "/playbook"} replace />;
}
