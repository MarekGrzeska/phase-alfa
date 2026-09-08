import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AgentPanel } from "./agent/AgentPanel";
import { Overview } from "./overview/Overview";
import { TaskForm } from "./task/TaskForm";
import "./app/screen.css";
import "./agent/panel.css";

// Migracja idzie ekranami, więc paczka musi umieć oba stany naraz: panel agenta
// doklejany do stron Jinja i widok, który Jinja już oddała Reactowi. Który to
// widok, mówi `data-view` na kontenerze — routing zostaje po stronie serwera,
// bo adresy tego narzędzia są w notatkach i w zakładkach.
const VIEWS = {
  overview: Overview,
  task: TaskForm,
};

const page = document.getElementById("root");
const view = page?.dataset.view;
if (page && view !== undefined && view in VIEWS) {
  const View = VIEWS[view as keyof typeof VIEWS];
  createRoot(page).render(
    <StrictMode>
      <View />
    </StrictMode>,
  );
}

const panel = document.getElementById("agent-root");
if (panel) {
  createRoot(panel).render(
    <StrictMode>
      <AgentPanel />
    </StrictMode>,
  );
}
