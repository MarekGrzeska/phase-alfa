import type { ModelInfo } from "./agentClient";

/** Wybór modelu w nagłówku panelu — trzy pozycje z cennika; model jest cechą sesji. */
export function ModelPicker({
  models,
  value,
  onChange,
  disabled,
}: {
  models: readonly ModelInfo[];
  value: string;
  onChange: (model: string) => void;
  disabled: boolean;
}) {
  return (
    <select
      className="agent-model"
      aria-label="Model agenta"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      {models.map((model) => (
        <option key={model.id} value={model.id} disabled={model.unavailable !== null}>
          {model.label} · ${model.input_usd}/${model.output_usd}
          {model.unavailable !== null ? " (niedostępny)" : ""}
        </option>
      ))}
    </select>
  );
}
