import { useState } from "react";

import { MessageBody } from "./MessageBody";
import { formatUsd, shortArgs } from "./items";
import type { Item } from "./items";

/** Elementy rozmowy: dymki, chipy narzędzi, karty zgody, chipy nawigacji. */

export function TranscriptItem({
  item,
  onDecide,
  busy,
}: {
  item: Item;
  onDecide: (confirmationId: number, decision: "accept" | "reject") => void;
  busy: boolean;
}) {
  switch (item.kind) {
    case "operator":
      return (
        <div className="agent-turn operator">
          <p className="agent-said">{item.text}</p>
        </div>
      );
    case "agent":
      return (
        <div className="agent-turn model">
          <MessageBody text={item.text} />
        </div>
      );
    case "tool":
      return <ToolChip item={item} />;
    case "confirm":
      return <ConfirmCard item={item} onDecide={onDecide} busy={busy} />;
    case "ui":
      return <UiChip action={item.action} />;
    case "error":
      return (
        <div className="agent-turn model">
          <p className="agent-error">{item.text}</p>
        </div>
      );
  }
}

function ToolChip({ item }: { item: Extract<Item, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const state = item.result === null ? "running" : item.result.isError ? "error" : "done";
  return (
    <div className={`agent-tool ${state}`} data-tool={item.name}>
      <button type="button" className="agent-tool-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="agent-tool-name">{item.name}</span>
        <span className="agent-tool-args">{shortArgs(item.args)}</span>
        <span className="agent-tool-state">
          {state === "running" ? "…" : state === "error" ? "błąd" : "ok"}
        </span>
      </button>
      {open && (
        <pre className="agent-tool-body">
          {JSON.stringify(item.args, null, 1)}
          {item.result !== null ? `\n→ ${item.result.text}` : ""}
        </pre>
      )}
    </div>
  );
}

function ConfirmCard({
  item,
  onDecide,
  busy,
}: {
  item: Extract<Item, { kind: "confirm" }>;
  onDecide: (confirmationId: number, decision: "accept" | "reject") => void;
  busy: boolean;
}) {
  const c = item.confirmation;
  return (
    <div className={`agent-confirm ${item.state}`} data-confirmation={c.id}>
      <strong>{c.title}</strong>
      <span className="small">
        {c.tool}
        {c.cost_usd !== null && c.cost_usd !== undefined ? ` · szacunek ${formatUsd(c.cost_usd)}` : ""}
      </span>
      {c.preview && <pre className="agent-confirm-preview">{c.preview}</pre>}
      {item.state === "pending" && (
        <div className="row">
          <button
            type="button"
            className="primary"
            disabled={busy}
            onClick={() => onDecide(c.id, "accept")}
          >
            Wykonaj
          </button>
          <button type="button" className="danger" disabled={busy} onClick={() => onDecide(c.id, "reject")}>
            Odrzuć
          </button>
        </div>
      )}
      {item.state === "deciding" && <p className="small">Wznawiam…</p>}
      {item.state === "accepted" && <p className="small">Wykonane za zgodą.</p>}
      {item.state === "rejected" && <p className="small">Odrzucone — agent nie wykonał.</p>}
    </div>
  );
}

function UiChip({ action }: { action: Extract<Item, { kind: "ui" }>["action"] }) {
  if (action.action === "focus") {
    return <span className="agent-ui">pole {action.name}</span>;
  }
  return (
    <a className="agent-ui" href={action.url}>
      {action.action === "open" ? "otwórz" : "→"} {action.url}
    </a>
  );
}
