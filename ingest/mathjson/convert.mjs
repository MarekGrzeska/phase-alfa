#!/usr/bin/env node
// Konwerter zapisów równoważnych na MathJSON (G2.6).
//
// stdin  : NDJSON, po jednym rekordzie w linii — {"id": 12, "latex": "..."}
// stdout : NDJSON — {"id": 12, "mathjson": [...]} albo {"id": 12, "error": "..."}
//
// Node, a nie Python, z JEDNEGO powodu: `@cortex-js/compute-engine` jest
// referencyjną implementacją MathJSON i tym samym silnikiem, którego użyje
// EvaluateClosed w A3. Parsowanie tą samą biblioteką eliminuje dryf dialektu
// między ingestem a silnikiem oceniania.
//
// Wejściem jest LaTeX, bo `ce.parse()` innego nie zna. Zamiana tekstu CKE
// na LaTeX stoi po stronie Pythona (`mathjson/normalize.py`) — tam da się ją
// przetestować bez Node'a, a to ona jest miejscem, w którym rodzą się pomyłki.

import { createInterface } from "node:readline";
import { ComputeEngine } from "@cortex-js/compute-engine";

const engine = new ComputeEngine();

/** Czy w drzewie MathJSON siedzi węzeł błędu — CE nie rzuca, tylko go wstawia. */
function findError(node) {
  if (Array.isArray(node)) {
    if (node[0] === "Error") {
      return node.slice(1).map((part) => JSON.stringify(part)).join(" ");
    }
    for (const child of node) {
      const found = findError(child);
      if (found !== null) return found;
    }
  }
  return null;
}

function convert(latex) {
  // `canonical: false` — zapisujemy to, co NAPISAŁ klucz, a nie postać po
  // uporządkowaniu przez silnik. Kanonizacja jest odwracalna i robi ją
  // konsument (EvaluateClosed w A3), a ekran korekty ma pokazać zapis
  // rozpoznawalny dla człowieka, który go właśnie czyta z PDF-a.
  const parsed = engine.parse(latex, { canonical: false });
  const json = parsed.json;
  const error = findError(json);
  if (error !== null) return { error };
  // Symbol `Nothing` to wynik parsowania pustego wejścia — nie jest wyrażeniem.
  if (json === "Nothing" || json === undefined) return { error: "puste wyrazenie" };
  return { mathjson: json };
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of lines) {
  const text = line.trim();
  if (!text) continue;
  let record;
  try {
    record = JSON.parse(text);
  } catch (e) {
    process.stdout.write(JSON.stringify({ id: null, error: `zly JSON: ${e.message}` }) + "\n");
    continue;
  }
  let result;
  try {
    result = convert(String(record.latex ?? ""));
  } catch (e) {
    result = { error: `${e.name}: ${e.message}` };
  }
  process.stdout.write(JSON.stringify({ id: record.id, ...result }) + "\n");
}
