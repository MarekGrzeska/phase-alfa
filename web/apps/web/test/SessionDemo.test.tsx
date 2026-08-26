import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SessionDemo } from "../src/SessionDemo";

afterEach(cleanup);

describe("SessionDemo", () => {
  it("startuje na pierwszym zadaniu, bez odpowiedzi", () => {
    render(<SessionDemo />);

    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("Zadanie 1");
    expect(screen.getByText("Odpowiedzi: 0 z 3")).toBeDefined();
  });

  it("odpowiedź z pola wchodzi do modelu sesji", () => {
    render(<SessionDemo />);

    fireEvent.change(screen.getByLabelText("Odpowiedź"), { target: { value: "BD" } });

    expect(screen.getByText("Odpowiedzi: 1 z 3")).toBeDefined();
    expect(screen.getByText(/Bez odpowiedzi: 16, 20/)).toBeDefined();
  });

  // Model kasuje odpowiedź złożoną z samych białych znaków — pole ma jej mimo to
  // nie zabierać spod palców. Bez rozdzielenia stanu spacja znikała w locie.
  it("spacja zostaje w polu, ale nie liczy się jako odpowiedź", () => {
    render(<SessionDemo />);

    const field = screen.getByLabelText("Odpowiedź") as HTMLInputElement;
    fireEvent.change(field, { target: { value: " " } });

    expect(field.value).toBe(" ");
    expect(screen.getByText("Odpowiedzi: 0 z 3")).toBeDefined();
  });

  it("„Następne” przechodzi na kolejne zadanie i wraca", () => {
    render(<SessionDemo />);

    fireEvent.click(screen.getByRole("button", { name: "Następne" }));
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("Zadanie 16");

    fireEvent.click(screen.getByRole("button", { name: "Poprzednie" }));
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("Zadanie 1");
  });
});
