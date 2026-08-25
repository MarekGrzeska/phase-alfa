import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // `node`, nie `jsdom` — druga warstwa ochrony przed DOM-em. Gdyby ktoś obszedł
    // typy, `document` i tak nie istnieje tu w czasie wykonania.
    environment: "node",
    // Oba rozszerzenia, tak samo jak w `apps/web`: wzorzec zawężony do jednego
    // gubi pliki po cichu.
    include: ["test/**/*.test.{ts,tsx}"],
  },
});
