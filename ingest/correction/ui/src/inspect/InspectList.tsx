import { useCallback, useEffect, useState } from "react";
import type { FormEvent, MouseEvent } from "react";

import { Chrome, Failure } from "../app/Chrome";
import { fetchList } from "./api";
import type { ListData } from "./api";
import "./inspect.css";

/**
 * Lista wierszy jednej tabeli: filtry, sortowanie, stronicowanie.
 *
 * Adresy liczy `ListView` po stronie Pythona i przysyła gotowe — „posortuj po
 * tej kolumnie" ma zachować filtry, a „zdejmij filtr" — sortowanie, i ta reguła
 * ma stać w jednym miejscu. Front klika w to, co dostał, i wpisuje do paska
 * adresu wersję kanoniczną, żeby dało się ją skopiować.
 */

const PER_PAGE_KEY = "correction.inspect.perPage.v1";

function rememberedPerPage(): string | null {
  try {
    return window.localStorage.getItem(PER_PAGE_KEY);
  } catch {
    return null;
  }
}

function rememberPerPage(value: string): void {
  try {
    window.localStorage.setItem(PER_PAGE_KEY, value);
  } catch {
    /* trudno */
  }
}

export function InspectList() {
  const table = window.location.pathname.replace(/^\/inspect\//, "").split("/")[0];
  const [query, setQuery] = useState(() => {
    // Rozmiar strony jest wyborem CZŁOWIEKA, nie tabeli: raz ustawiony obowiązuje
    // w całym inspektorze. Wcześniej pamiętało go ciasteczko.
    const params = new URLSearchParams(window.location.search);
    const remembered = rememberedPerPage();
    if (!params.has("_per") && remembered !== null) {
      params.set("_per", remembered);
      return `?${params.toString()}`;
    }
    return window.location.search;
  });
  const [data, setData] = useState<ListData | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const onPop = () => setQuery(window.location.search);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    let current = true;
    setFailure(null);
    fetchList(table, query)
      .then((next) => {
        if (!current) return;
        setData(next);
        // Adres kanoniczny: wiersz filtrów wysyła `op.kolumna` osobno od wartości,
        // a w pasku ma zostać postać, którą da się wkleić w notatce.
        const wanted = next.links.canonical;
        if (wanted !== window.location.pathname + window.location.search) {
          window.history.replaceState(null, "", wanted);
        }
      })
      .catch((error: Error) => {
        if (current) setFailure(error.message);
      });
    return () => {
      current = false;
    };
  }, [table, query]);

  const go = useCallback((url: string) => {
    const search = url.includes("?") ? url.slice(url.indexOf("?")) : "";
    window.history.pushState(null, "", url);
    setQuery(search);
  }, []);

  function follow(event: MouseEvent<HTMLAnchorElement>): void {
    const href = event.currentTarget.getAttribute("href");
    if (href === null || !href.startsWith(`/inspect/${table}`)) {
      return;
    }
    event.preventDefault();
    go(href);
  }

  if (failure !== null) {
    return (
      <Chrome scopeQuery="">
        <Failure reason={failure} />
      </Chrome>
    );
  }
  if (data === null) {
    return (
      <Chrome scopeQuery="">
        <p className="small">Wczytuję wiersze…</p>
      </Chrome>
    );
  }

  const { view, links } = data;
  const key = data.table.single_key;
  const last = data.total > 0 ? Math.floor((data.total - 1) / view.per_page) + 1 : 1;
  const active = new Map(view.filters.map((filter) => [filter.column, filter]));

  function applyFilters(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const params = new URLSearchParams();
    for (const [name, value] of new FormData(event.currentTarget).entries()) {
      if (typeof value === "string") {
        params.append(name, value);
      }
    }
    go(`/inspect/${table}?${params.toString()}`);
  }

  return (
    <Chrome
      scopeQuery=""
      subtitle={
        <>
          <a href="/inspect">Inspektor</a> › {data.table.name} · {data.total} wierszy
        </>
      }
    >
      {data.errors.length > 0 && (
        <div className="errors">
          <strong>Filtr nie zadziałał:</strong>
          <ul>
            {data.errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="card">
        <h2 className="mono">{data.table.name}</h2>
        <p className="small" style={{ marginTop: 0 }}>
          {data.table.note}
        </p>

        <div className="fbar">
          {view.filters.map((filter) => (
            <span className="chip" key={filter.param}>
              {filter.label}{" "}
              <a href={links.drop[filter.param]} title="zdejmij" onClick={follow}>
                ×
              </a>
            </span>
          ))}
          {view.filters.length > 0 ? (
            <a className="small" href={links.clear} onClick={follow}>
              wyczyść wszystkie
            </a>
          ) : (
            <span className="small" style={{ color: "var(--ink-2)" }}>
              Filtruj w wierszu pod nagłówkami — działa od razu po zmianie. Nagłówek sortuje.
            </span>
          )}
          <span className="spacer" style={{ flex: 1 }}></span>
          <span className="small">
            <a href={links.columns} onClick={follow}>
              {view.all_columns ? "tylko ważne kolumny" : "wszystkie kolumny"}
            </a>
          </span>
        </div>

        <form onSubmit={applyFilters}>
          {/* Filtry po kolumnach spoza widoku jadą dalej ukryte — inaczej znikałyby
              po pierwszym użyciu wiersza filtrów. */}
          {view.filters
            .filter((filter) => !data.visible.includes(filter.column))
            .map((filter) => (
              <input
                key={filter.param}
                type="hidden"
                name={filter.param}
                value={filter.value ?? ""}
              />
            ))}
          {view.sort !== null && (
            <>
              <input type="hidden" name="_sort" value={view.sort} />
              <input type="hidden" name="_dir" value={view.direction} />
            </>
          )}
          {view.all_columns && <input type="hidden" name="_cols" value="all" />}
          <input type="hidden" name="_per" value={String(view.per_page)} />

          <table className="list">
            <thead>
              <tr>
                {data.visible.map((column) => (
                  <th key={column} className={view.sort === column ? "sorted" : undefined}>
                    <a href={links.sort[column]} onClick={follow}>
                      {column}
                      {view.sort === column && (view.direction === "asc" ? " ↑" : " ↓")}
                    </a>
                    {column !== key && (
                      <span className="src">
                        {data.table.columns.find((c) => c.name === column)?.source ?? ""}
                      </span>
                    )}
                  </th>
                ))}
                <th>rodzice</th>
              </tr>
              <tr className="filters">
                {data.visible.map((column) => {
                  const filter = active.get(column);
                  const offer = data.described[column];
                  return (
                    <td key={column}>
                      <div className={`cell ${filter ? "on" : ""}`}>
                        <select
                          name={`${data.operator_prefix}${column}`}
                          aria-label={`operator dla ${column}`}
                          defaultValue={filter?.op ?? offer?.default}
                          key={`op-${column}-${filter?.op ?? offer?.default}`}
                          onChange={(event) => event.currentTarget.form?.requestSubmit()}
                        >
                          {(offer?.operators ?? []).map((operator) => (
                            <option
                              key={operator}
                              value={operator}
                              title={data.operators[operator]?.[1]}
                            >
                              {data.operators[operator]?.[0]}
                            </option>
                          ))}
                        </select>
                        {offer?.is_enum ? (
                          // Wartość ze słownika — wybór, nie wpisywanie: literówka
                          // w statusie dawałaby pustą listę i wyglądała jak brak danych.
                          <select
                            name={column}
                            className="val"
                            aria-label={`wartość filtru dla ${column}`}
                            defaultValue={filter?.value ?? ""}
                            key={`val-${column}-${filter?.value ?? ""}`}
                            onChange={(event) => event.currentTarget.form?.requestSubmit()}
                          >
                            <option value="">—</option>
                            {offer.options.map((option) => (
                              <option key={option} value={option}>
                                {option}
                              </option>
                            ))}
                          </select>
                        ) : (
                          // `onChange`, nie `onInput`: zdarzenie leci po opuszczeniu
                          // pola albo po Enterze, więc jedno zapytanie na filtr,
                          // a nie jedno na literę.
                          <input
                            name={column}
                            aria-label={`filtr dla ${column}`}
                            defaultValue={filter?.value ?? ""}
                            key={`val-${column}-${filter?.value ?? ""}`}
                            onChange={(event) => event.currentTarget.form?.requestSubmit()}
                          />
                        )}
                      </div>
                    </td>
                  );
                })}
                <td></td>
              </tr>
            </thead>
            <tbody>
              {data.rows.length === 0 ? (
                <tr>
                  <td colSpan={20} className="small">
                    {data.errors.length > 0
                      ? "Nie wykonano zapytania."
                      : "Nic nie pasuje do filtra."}
                  </td>
                </tr>
              ) : (
                data.rows.map((row, index) => (
                  <tr key={row.key ?? index}>
                    {data.visible.map((column) => (
                      <td
                        key={column}
                        className={column === key ? "mono" : undefined}
                        title={row.cells[column]?.full}
                      >
                        {column === key ? (
                          <a href={`/inspect/${data.table.name}/${row.key}`}>#{row.key}</a>
                        ) : (
                          row.cells[column]?.text
                        )}
                      </td>
                    ))}
                    <td className="small mono">
                      {row.parents.map((parent, position) => (
                        <span key={`${parent.table}-${parent.id}`}>
                          {position > 0 && " · "}
                          <a href={`/inspect/${parent.table}/${parent.id}`}>
                            {parent.table}#{parent.id}
                          </a>
                        </span>
                      ))}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </form>

        <p className="legend">
          Operatory: <span className="mono">=</span> równe · <span className="mono">≠</span>{" "}
          różne · <span className="mono">≈</span> zawiera (ignoruje wielkość liter) ·{" "}
          <span className="mono">&gt; ≥ &lt; ≤</span> porównanie po typie kolumny, nie po
          tekście · <span className="mono">∅</span> pusta · <span className="mono">!∅</span>{" "}
          niepusta. Dwa filtry naraz łączy „i". Kolumna słownikowa daje wybór z listy zamiast
          wpisywania, a operatory ma zawężone do tych, które dla niej znaczą.
        </p>

        <div className="pager small">
          <span>
            strona {view.page} z {last}
          </span>
          {links.previous !== null && (
            <a href={links.previous} onClick={follow}>
              ← poprzednia
            </a>
          )}
          {links.next !== null && (
            <a href={links.next} onClick={follow}>
              następna →
            </a>
          )}
          <span>
            na stronie:{" "}
            {data.per_page_options.map((option, index) => (
              <span key={option}>
                {index > 0 && " · "}
                {option === view.per_page ? (
                  <b className="mono">{option}</b>
                ) : (
                  <a
                    className="mono"
                    href={links.per[String(option)]}
                    onClick={(event) => {
                      rememberPerPage(String(option));
                      follow(event);
                    }}
                  >
                    {option}
                  </a>
                )}
              </span>
            ))}
          </span>
          {view.sort !== null && (
            <span>
              sortowanie:{" "}
              <span className="mono">
                {view.sort} {view.direction}
              </span>
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Kolumny tej tabeli i kto je pisze</h3>
        <table>
          <thead>
            <tr>
              <th>kolumna</th>
              <th>typ</th>
              <th>NULL</th>
              <th>domyślnie</th>
              <th>źródło wartości</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.table.columns.map((column) => (
              <tr key={column.name}>
                <td className="mono">
                  {column.name}
                  {column.parent !== null && (
                    <span className="small">
                      {" → "}
                      <a href={`/inspect/${column.parent}`}>{column.parent}</a>
                    </span>
                  )}
                </td>
                <td className="small mono">{column.type}</td>
                <td className="small">{column.nullable ? "tak" : "nie"}</td>
                <td className="small mono">{column.default ?? ""}</td>
                <td
                  className={`small${column.source.startsWith("nikt") ? " mono" : ""}`}
                  style={column.source.startsWith("nikt") ? { color: "var(--crit)" } : undefined}
                >
                  {column.source}
                </td>
                <td className="small">
                  <a href={links.sort[column.name]} onClick={follow}>
                    sortuj
                  </a>
                  {!data.visible.includes(column.name) && (
                    <>
                      {" · "}
                      <a
                        href={`/inspect/${data.table.name}?${column.name}__notnull=`}
                        onClick={follow}
                      >
                        filtruj
                      </a>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small" style={{ margin: ".6rem 0 0" }}>
          Kolumny spoza widoku filtruje się po włączeniu „wszystkie kolumny" — wtedy każda
          dostaje swoje pole w wierszu filtrów. „Źródło" to wiedza o kodzie: który przebieg
          pisze tę kolumnę, nie skąd wziął się KONKRETNY wiersz.
        </p>
      </div>
    </Chrome>
  );
}
