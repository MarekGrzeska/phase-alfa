import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Panel pamięta stan w `localStorage`, więc test, który go rozwinie, ustawiłby
// warunki początkowe następnemu. Sprzątanie tutaj, a nie w każdym pliku z osobna.
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});
