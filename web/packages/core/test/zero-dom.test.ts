/**
 * Zero-DOM, warstwy 2 i 3. Warstwą 1 — właściwą — jest `tsconfig.json`:
 * `lib` bez `"DOM"` i `types: []` sprawiają, że `document` NIE KOMPILUJE SIĘ
 * w `src`. Te testy łapią to, czego kompilator nie widzi: pakiet dopisany do
 * `package.json`, zanim ktokolwiek go zawoła, oraz sięgnięcie do globalnego
 * obiektu przez `any`.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const ROOT = fileURLToPath(new URL("..", import.meta.url));

/** Wszystko, co ciągnie za sobą DOM albo framework widoku. */
const FORBIDDEN = [
  "react",
  "react-dom",
  "react-native",
  "mathlive",
  "jsdom",
  "happy-dom",
  "@vitejs/plugin-react",
  "@testing-library/react",
  "@testing-library/dom",
  "@types/react",
];

const DOM_GLOBALS = /\b(?:document|window|navigator|localStorage|sessionStorage)\s*[.[]/;

function readJson(path: string): Record<string, unknown> {
  // Komentarze `//` są w tsconfigach celowo, więc goły `JSON.parse` by się na nich wywrócił.
  const text = readFileSync(path, "utf8").replace(/^\s*\/\/.*$/gm, "");
  return JSON.parse(text) as Record<string, unknown>;
}

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      return sourceFiles(path);
    }
    return entry.name.endsWith(".ts") ? [path] : [];
  });
}

describe("packages/core nie widzi DOM-u", () => {
  it("nie deklaruje zależności DOM-owych", () => {
    const manifest = readJson(join(ROOT, "package.json"));
    const declared = ["dependencies", "peerDependencies", "devDependencies"].flatMap((section) =>
      Object.keys((manifest[section] ?? {}) as Record<string, string>),
    );

    const found = declared.filter((name) => FORBIDDEN.includes(name));

    expect(found, `zabronione zależności w packages/core: ${found.join(", ")}`).toEqual([]);
  });

  it("tsconfig produktu nie wpuszcza `lib: DOM` ani domyślnych @types", () => {
    const config = readJson(join(ROOT, "tsconfig.json")) as {
      compilerOptions: { lib: string[]; types: string[] };
      include: string[];
    };

    expect(config.compilerOptions.lib).not.toContain("DOM");
    expect(config.compilerOptions.types).toEqual([]);
    // Gdyby `include` objęło `test`, produkt zacząłby dziedziczyć typy testów.
    expect(config.include).toEqual(["src"]);
  });

  it("źródła nie sięgają do globalnych obiektów przeglądarki", () => {
    const offenders = sourceFiles(join(ROOT, "src")).filter((path) =>
      DOM_GLOBALS.test(readFileSync(path, "utf8")),
    );

    expect(
      offenders,
      `packages/core nie może dotykać DOM — przenieś to do apps/web: ${offenders.join(", ")}`,
    ).toEqual([]);
  });
});
