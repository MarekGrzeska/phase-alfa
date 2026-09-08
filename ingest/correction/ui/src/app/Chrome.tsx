import type { ReactNode } from "react";

/**
 * Górna belka ekranu korekty — ta sama, co w szablonach Jinja, bo do końca
 * migracji korektor przechodzi między jednym a drugim w tej samej sesji
 * i belka, która skacze, wygląda na zepsuty ekran.
 *
 * Odnośniki są zwykłymi `<a>`, a nie routingiem po stronie klienta: ekrany,
 * których jeszcze nie przepisano, są normalnymi stronami z serwera.
 */
export function Chrome({
  scopeQuery,
  subtitle,
  actions,
  children,
}: {
  scopeQuery: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <header>
        <h1>
          <a href={`/${scopeQuery}`}>Ekran korekty</a>
        </h1>
        <a className="small" href="/inspect">
          Inspektor
        </a>
        <span className="small">{subtitle}</span>
        <span className="spacer"></span>
        {actions}
      </header>
      <main>{children}</main>
    </>
  );
}

/** Błąd zapytania pokazany tam, gdzie stanąłby widok — z powodem, nie z ikoną. */
export function Failure({ reason }: { reason: string }) {
  return (
    <div className="errors">
      <strong>Nie udało się wczytać danych:</strong>
      <p style={{ margin: ".3rem 0 0" }}>{reason}</p>
    </div>
  );
}
