import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { mockApi } from "./mock/api";

/* VITE_MOCK_API=1 -> ใช้ mock backend (ดู UI ได้โดยไม่ต้องมี Azure/func) — `npm run dev:mock`
   ไม่ตั้ง          -> proxy /api ไป Azure Functions ที่ localhost:7071 — `npm run dev`
   mockApi() ตั้ง apply:"serve" ไว้ จึงไม่มีผลกับ `npm run build` เด็ดขาด */
const useMock = process.env.VITE_MOCK_API === "1";

export default defineConfig({
  plugins: [react(), ...(useMock ? [mockApi()] : [])],
  server: useMock ? {} : {
    proxy: {
      // proxy /api -> Azure Functions local (func start :7071)
      "/api": "http://localhost:7071",
    },
  },
});
