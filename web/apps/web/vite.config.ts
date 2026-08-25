import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// `fileURLToPath`, nie `URL.pathname`: to drugie daje na Windows „/C:/…", a spacje
// zostawia zakodowane jako %20 — czyli ścieżkę, pod którą nie ma żadnego pliku.
const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

export default defineConfig(({ mode }) => {
  // Port API z `.env` z korzenia repozytorium, tak samo jak bierze go Taskfile.
  // Zaszyty tutaj rozjeżdżałby się z `API_PORT` przy pierwszej kolizji portów.
  const env = loadEnv(mode, REPO_ROOT, "");
  const apiPort = env.API_PORT ?? "5014";
  const webPort = Number(env.WEB_PORT ?? "5173");

  return {
    plugins: [
      react(),
      VitePWA({
        registerType: "autoUpdate",
        // Service worker WYŁĄCZONY w developmencie: trzymający stary build to
        // ostatnia rzecz, jakiej trzeba przy iteracji co kilka minut.
        devOptions: { enabled: false },
        // Bez runtime caching — w alfie PWA ma dawać manifest i instalowalność,
        // a nie serwować nieświeże dane z cache'u.
        workbox: { globPatterns: ["**/*.{js,css,html,svg}"], runtimeCaching: [] },
        manifest: {
          name: "Klucz",
          short_name: "Klucz",
          description: "Ocenianie odpowiedzi według zasad oceniania CKE",
          lang: "pl",
          start_url: "/",
          display: "standalone",
          background_color: "#ffffff",
          theme_color: "#1f2933",
          // Bez `icons` przeglądarka nie proponuje instalacji — i nie mówi o tym
          // ani słowa. `maskable` osobno: Android przycina ikonę do swojego kształtu.
          icons: [
            { src: "icon-192.png", sizes: "192x192", type: "image/png" },
            { src: "icon-512.png", sizes: "512x512", type: "image/png" },
            { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
          ],
        },
      }),
    ],
    server: {
      // Port z `.env`, tak samo jak `API_PORT` — jedna wartość rządzi serwerem
      // i komunikatem `task dev` naraz.
      port: webPort,
      // Bez `strictPort` Vite przy zajętym porcie po cichu wstaje na następnym,
      // a komunikat `task dev` obiecuje adres, pod którym nic nie stoi.
      strictPort: true,
      // Proxy zamiast CORS-u: przeglądarka widzi jeden origin, więc backend
      // nie musi znać adresu dev servera ani wystawiać nagłówków tylko dla niego.
      proxy: {
        "/api": {
          target: `http://localhost:${apiPort}`,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
