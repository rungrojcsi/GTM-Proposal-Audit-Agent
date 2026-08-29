import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node", // src/lib + src/api ไม่แตะ DOM — ไม่ต้องใช้ jsdom
    include: ["src/**/*.test.ts"],
  },
});
