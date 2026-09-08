import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AgentPanel } from "./agent/AgentPanel";
import "./agent/panel.css";

// Wyspa, a nie aplikacja: ekrany korekty są na razie renderowane przez Jinja,
// a React siedzi w jednym kontenerze obok nich. Kolejne kroki migracji będą
// zabierać stąd kolejne ekrany, aż zostanie sam React.
const container = document.getElementById("agent-root");
if (container) {
  createRoot(container).render(
    <StrictMode>
      <AgentPanel />
    </StrictMode>,
  );
}
