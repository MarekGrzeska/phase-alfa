/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `fileURLToPath`, nie `URL.pathname`: to drugie daje na Windows „/C:/…", a spacje
// zostawia zakodowane jako %20 — czyli ścieżkę, pod którą nie ma żadnego pliku.
const STATIC_DIR = fileURLToPath(new URL("../static", import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    // Wynik ląduje w katalogu, który FastAPI wystawia pod `/static` — jeden
    // artefakt o stałej nazwie, bo odwołuje się do niego szablon Jinja,
    // a szablon nie umie odczytać manifestu z hashami.
    outDir: STATIC_DIR,
    emptyOutDir: true,
    // Zwykły build z własnym wejściem, a NIE `build.lib`: tryb biblioteki
    // zostawia wynik nieskrócony (1,2 MB zamiast ~350 kB), a to jest paczka
    // dla przeglądarki, nie paczka do npm-a.
    rollupOptions: {
      input: fileURLToPath(new URL("./src/main.tsx", import.meta.url)),
      output: {
        format: "es",
        // Stałe nazwy bez hasza: odwołuje się do nich szablon Jinja,
        // a szablon nie umie odczytać manifestu.
        entryFileNames: "correction.js",
        chunkFileNames: "correction-[name].js",
        assetFileNames: "correction.[ext]",
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
