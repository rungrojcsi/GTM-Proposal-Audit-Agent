/* H01/H02 — สถานะที่ต้องใช้ข้ามหน้า: ตัวตนผู้ใช้, ข้อความแจ้งงานเบื้องหลัง, คำค้นบนแถบบน
   ที่เหลือให้แต่ละหน้าถือ state ของตัวเอง (ลดการผูกกันข้ามหน้า) */
import { createContext, useContext } from "react";
import type { Me } from "./api/client";

export interface AppCtx {
  me: Me | null;
  notice: string | null;
  setNotice: (v: string | null) => void;
  search: string;
  setSearch: (v: string) => void;
}

export const AppContext = createContext<AppCtx>({
  me: null, notice: null, setNotice: () => {}, search: "", setSearch: () => {},
});

export const useApp = () => useContext(AppContext);

/** ข้อความเดียวกันทุกที่ที่ยกเลิก poll เพราะผู้ใช้เปลี่ยนหน้า (E05) */
export const BG_NOTICE = "การประเมินยังทำงานอยู่เบื้องหลัง — กลับมาดูผลได้ที่หน้า Evaluation Results";
