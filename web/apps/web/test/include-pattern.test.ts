/**
 * Strażnik wzorca `test.include`. Sam plik jest asercją — ma rozszerzenie
 * `.test.ts`, więc przy zawężonym wzorcu zniknie z wyniku vitesta. Asercja
 * treści jest drugą warstwą: mówi, CO poszło nie tak, zamiast milczeć.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// `process.cwd()`, nie `import.meta.url`: w jsdom to drugie nie jest adresem
// `file:`, więc `fileURLToPath` się na nim wywraca.
const CONFIG = join(process.cwd(), "vitest.config.ts");

describe("wzorzec plików testowych", () => {
  it("obejmuje `.test.ts` i `.test.tsx`", () => {
    const config = readFileSync(CONFIG, "utf8");

    expect(
      config,
      "wzorzec zawężony do jednego rozszerzenia gubi pliki po cichu",
    ).toContain("test/**/*.test.{ts,tsx}");
  });
});
