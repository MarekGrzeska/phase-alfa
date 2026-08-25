import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Osobno od `vite.config.ts`: tamten ładuje `.env` z korzenia repozytorium
// i wtyczkę PWA, a testy nie potrzebują ani jednego, ani drugiego.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["test/**/*.test.tsx"],
  },
});
