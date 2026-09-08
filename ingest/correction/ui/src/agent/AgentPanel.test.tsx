import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AgentPanel } from "./AgentPanel";

/** Makieta agenta: sedno testów jest w tym, CO widać w trakcie strumienia
 *  i po jego przerwaniu — bo to jest jedyne zachowanie, które ta wersja ma. */

function openPanel() {
  window.localStorage.setItem("correction.agentPanel.state.v1", "expanded");
}

/** Przewija strumień do końca. Zegar jest udawany, więc odpowiedź „pisze się"
 *  natychmiast, ale tą samą drogą co u człowieka: kawałek po kawałku. */
async function runStream(ms = 5000) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

describe("panel zwinięty i rozwinięty", () => {
  test("startuje zwinięty — korektor otwiera to narzędzie do skanu, nie do czatu", () => {
    render(<AgentPanel />);
    expect(screen.getByRole("button", { name: "Otwórz panel agenta" })).toBeDefined();
    expect(screen.queryByLabelText("Wiadomość do agenta")).toBeNull();
  });

  test("stan przeżywa przeładowanie strony", async () => {
    const user = userEvent.setup();
    const view = render(<AgentPanel />);
    await user.click(screen.getByRole("button", { name: "Otwórz panel agenta" }));
    view.unmount();

    render(<AgentPanel />);
    expect(screen.getByLabelText("Wiadomość do agenta")).toBeDefined();
  });
});

describe("rozmowa z makietą", () => {
  beforeEach(() => {
    openPanel();
    // `shouldAdvanceTime`: bez tego zegar stoi także dla `user-event`, które
    // czeka na własne mikrozadania — i test wisi, zanim cokolwiek sprawdzi.
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  test("pytanie ląduje w rozmowie, odpowiedź dopisuje się po strumieniu", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<AgentPanel />);

    await user.type(screen.getByLabelText("Wiadomość do agenta"), "ile progów ma to zadanie?");
    await user.click(screen.getByRole("button", { name: "Wyślij" }));

    expect(screen.getByText("ile progów ma to zadanie?")).toBeDefined();
    // Zanim przyjdzie pierwszy kawałek, panel mówi, że coś się dzieje — inaczej
    // wygląda to na kliknięcie, które nic nie zrobiło.
    expect(screen.getByText("Agent pisze…")).toBeDefined();

    await runStream();
    expect(screen.queryByText("Agent pisze…")).toBeNull();
    expect(document.querySelectorAll(".agent-turn.model").length).toBe(1);
  });

  test("odpowiedź jest markdownem, nie tekstem ze znakami składni", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<AgentPanel />);

    await user.type(screen.getByLabelText("Wiadomość do agenta"), "progi");
    await user.click(screen.getByRole("button", { name: "Wyślij" }));
    await runStream();

    const reply = document.querySelector(".agent-turn.model .agent-md");
    expect(reply).not.toBeNull();
    // Cokolwiek wylosuje makieta, ma to być SKŁADNIA zamieniona na znaczniki,
    // a nie gwiazdki i kreski w tekście.
    expect(reply?.querySelectorAll("strong, em, li, code, table").length).toBeGreaterThan(0);
    expect(reply?.textContent ?? "").not.toContain("**");
  });

  test("„Przerwij” zostawia w rozmowie to, co zdążyło przyjść", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<AgentPanel />);

    await user.type(screen.getByLabelText("Wiadomość do agenta"), "kryteria");
    await user.click(screen.getByRole("button", { name: "Wyślij" }));
    await runStream(200);
    await user.click(screen.getByRole("button", { name: "Przerwij" }));

    const turns = document.querySelectorAll(".agent-turn.model");
    expect(turns.length).toBe(1);
    expect((turns[0].textContent ?? "").length).toBeGreaterThan(0);

    // Urwana odpowiedź kończy turę: pole wraca do pisania, a nie zostaje zablokowane.
    await runStream();
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDefined();
    expect(document.querySelectorAll(".agent-turn.model").length).toBe(1);
  });

  test("puste pytanie nie idzie nigdzie", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<AgentPanel />);

    await user.type(screen.getByLabelText("Wiadomość do agenta"), "   ");
    const send = screen.getByRole("button", { name: "Wyślij" });
    expect(send.hasAttribute("disabled")).toBe(true);

    await runStream();
    expect(document.querySelectorAll(".agent-turn").length).toBe(0);
  });

  test("Enter wysyła, Shift+Enter łamie linię", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<AgentPanel />);
    const box = screen.getByLabelText("Wiadomość do agenta");

    await user.type(box, "pierwsza{Shift>}{Enter}{/Shift}druga");
    expect(document.querySelectorAll(".agent-turn").length).toBe(0);

    await user.type(box, "{Enter}");
    const said = document.querySelector(".agent-turn.operator");
    expect(said?.textContent).toContain("pierwsza");
    expect(said?.textContent).toContain("druga");
  });
});

describe("szerokość panelu", () => {
  beforeEach(openPanel);

  test("strzałki zmieniają szerokość i zostają w pamięci", async () => {
    const user = userEvent.setup();
    render(<AgentPanel />);
    const handle = screen.getByRole("separator", { name: "Zmien szerokosc panelu agenta" });
    const before = Number(handle.getAttribute("aria-valuenow"));

    handle.focus();
    await user.keyboard("{ArrowLeft}");

    expect(Number(handle.getAttribute("aria-valuenow"))).toBe(before + 16);
    expect(window.localStorage.getItem("correction.agentPanel.width.v1")).toBe(
      String(before + 16),
    );
  });

  test("nie schodzi poniżej progu czytelności", async () => {
    const user = userEvent.setup();
    render(<AgentPanel />);
    const handle = screen.getByRole("separator", { name: "Zmien szerokosc panelu agenta" });

    handle.focus();
    await user.keyboard("{Home}");
    const min = Number(handle.getAttribute("aria-valuemin"));
    expect(Number(handle.getAttribute("aria-valuenow"))).toBe(min);

    await user.keyboard("{ArrowRight}");
    expect(Number(handle.getAttribute("aria-valuenow"))).toBe(min);
  });
});

describe("panel w układzie strony", () => {
  test("rozwinięty ma etykietę, po której da się go znaleźć na każdym ekranie", () => {
    openPanel();
    render(<AgentPanel />);
    const panel = screen.getByRole("complementary", { name: "Agent" });
    expect(within(panel).getByLabelText("Wiadomość do agenta")).toBeDefined();
  });
});
