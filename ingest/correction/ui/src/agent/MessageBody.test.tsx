import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { MessageBody } from "./MessageBody";

describe("formatowanie odpowiedzi", () => {
  test("markdown staje się znacznikami, nie tekstem", () => {
    const { container } = render(
      <MessageBody text={"**waga** progu\n\n- pierwszy\n- drugi"} />,
    );
    expect(container.querySelector("strong")?.textContent).toBe("waga");
    expect(container.querySelectorAll("li").length).toBe(2);
  });

  test("tabela GFM się renderuje — bez `remark-gfm` byłaby ciągiem kresek", () => {
    const { container } = render(
      <MessageBody text={"| próg | pkt |\n| --- | --- |\n| metoda | 1 |"} />,
    );
    expect(container.querySelectorAll("th").length).toBe(2);
    expect(container.querySelectorAll("td").length).toBe(2);
  });

  test("nagłówek spłaszczony do pogrubionego akapitu", () => {
    // Prawdziwy `h1` w panelu przebiłby nagłówek strony, na której panel stoi.
    const { container } = render(<MessageBody text="# Kryteria" />);
    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector(".agent-md-heading")?.textContent).toBe("Kryteria");
  });

  test("surowy HTML z odpowiedzi nie jest renderowany", () => {
    // Bez `rehype-raw` — i to jest cały argument o bezpieczeństwie tego widoku.
    const { container } = render(
      <MessageBody text={'<img src="x" onerror="alert(1)">tekst'} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("tekst");
  });

  test("link inny niż http(s) zostaje tekstem", () => {
    const { container } = render(
      <MessageBody text={"[kliknij](javascript:alert(1))"} />,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("kliknij");
  });

  test("link http otwiera się w nowej karcie i bez `opener`", () => {
    const { container } = render(<MessageBody text="[CKE](https://cke.gov.pl)" />);
    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://cke.gov.pl");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  test("niedomknięte pogrubienie w trakcie strumienia jest już pogrubieniem", () => {
    // Po to jest `remend`: bez niego odpowiedź migałaby gwiazdkami przy każdej klatce.
    const { container } = render(<MessageBody text="**waga pro" streaming />);
    expect(container.querySelector("strong")?.textContent).toContain("waga pro");
  });

  test("poza strumieniem tekst idzie taki, jaki przyszedł", () => {
    const { container } = render(<MessageBody text="**waga pro" />);
    expect(container.querySelector("strong")).toBeNull();
    expect(container.textContent).toContain("**waga pro");
  });
});
