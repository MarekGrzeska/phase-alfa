import type { ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remend from "remend";

/**
 * Treść modelu renderowana jako markdown, którym model pisze. Wiadomości człowieka
 * NIE idą tą drogą — korektor pisze zdanie, a nie dokument.
 *
 * Bez `rehype-raw`, świadomie: surowy HTML z odpowiedzi nie jest wtedy renderowany
 * w ogóle i cały argument o bezpieczeństwie tego widoku brzmi „tego tu nie ma".
 */

/**
 * `remend` domyka to, czego strumień jeszcze nie dopowiedział — niedokończone `**`
 * jest pogrubieniem od pierwszej klatki, a nie dwiema gwiazdkami w tekście.
 * `linkMode: "text-only"` nie robi klikalnego pół-linku; `katex` niepotrzebny,
 * bo wzory z klucza jadą tu jako zwykły zapis, a nie jako TeX.
 */
const REMEND_OPTIONS = { linkMode: "text-only", katex: false } as const;

/**
 * Nadpisujemy tylko to, czego sam CSS nie załatwi — reszta znaczników bierze
 * wygląd z `.agent-md` w `panel.css`, czyli ze zmiennych ekranu korekty.
 */
const COMPONENTS = {
  // Nagłówki spłaszczone do pogrubionego akapitu. Odpowiedź w kolumnie szerokiej
  // na 24rem nie ma konspektu do niesienia, a prawdziwy `h1` przebiłby nagłówek
  // strony, na której panel stoi.
  h1: Heading,
  h2: Heading,
  h3: Heading,
  h4: Heading,
  h5: Heading,
  h6: Heading,
  a: SafeLink,
  // Tabela w wąskiej kolumnie wyjdzie poza nią przy każdej treści, więc przewija
  // się we własnym pudełku, zamiast rozpychać panel.
  table: ({ children }: { children?: ReactNode }) => (
    <div className="agent-md-scroll">
      <table>{children}</table>
    </div>
  ),
};

function Heading({ children }: { children?: ReactNode }) {
  return <p className="agent-md-heading">{children}</p>;
}

/** Cokolwiek nie jest `http(s)`, pokazujemy jako tekst — nie jako coś do kliknięcia.
 *
 * Model piszący `javascript:` albo `data:` to jedyna droga, którą jego odpowiedź
 * mogłaby DZIAŁAĆ na korektora, zamiast go informować.
 */
function SafeLink({ href, children }: { href?: string; children?: ReactNode }) {
  const safe = href !== undefined && /^https?:\/\//i.test(href);
  if (!safe) {
    return <span>{children}</span>;
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export function MessageBody({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const source = streaming ? remend(text, REMEND_OPTIONS) : text;
  return (
    <div className="agent-md">
      <Markdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {source}
      </Markdown>
    </div>
  );
}
