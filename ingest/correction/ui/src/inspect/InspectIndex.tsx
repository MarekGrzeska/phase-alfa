import { Chrome, Failure } from "../app/Chrome";
import { useRemote } from "./useRemote";
import { fetchHealth, fetchIndex } from "./api";
import "./inspect.css";

/** Spis tabel, zdrowie danych i kolumny, których nikt nie wypełnia. */
export function InspectIndex() {
  const { data, failure } = useRemote(fetchIndex, []);

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
        <p className="small">Wczytuję schemat…</p>
      </Chrome>
    );
  }

  return (
    <Chrome
      scopeQuery=""
      subtitle={`${data.tables.length} tabel · ${data.views.length} widoki · tylko odczyt`}
    >
      <div className="grid2">
        <div>
          <div className="card">
            <h2>Tabele</h2>
            <p className="small" style={{ marginTop: 0 }}>
              Liczby po całej tabeli, nie po korpusie. Klik prowadzi do listy; z listy — do
              wiersza, jego rodziców, dzieci i strony PDF, z której wyszedł.
            </p>
            <table>
              <thead>
                <tr>
                  <th>tabela</th>
                  <th className="n">wierszy</th>
                  <th>co to</th>
                </tr>
              </thead>
              <tbody>
                {data.tables.map((table) => (
                  <tr key={table.name} className={table.count === 0 ? "empty" : undefined}>
                    <td className="mono">
                      <a href={`/inspect/${table.name}`}>{table.name}</a>
                    </td>
                    <td className="n">{table.count}</td>
                    <td className="small">{table.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3 style={{ marginTop: "1rem" }}>Widoki</h3>
            <p className="small mono" style={{ margin: 0 }}>
              {data.views.join(" · ")}
            </p>
            <p className="small" style={{ margin: ".4rem 0 0" }}>
              Widoków inspektor nie listuje — <span className="mono">corpus_task</span> to{" "}
              <span className="mono">task</span> z filtrem{" "}
              <span className="mono">review_status</span>, a definicja korpusu ma stać
              w jednym miejscu.
            </p>
          </div>
        </div>

        <div>
          <div className="card">
            <h2>Zdrowie danych</h2>
            <p className="small" style={{ marginTop: 0 }}>
              Te same pytania co <span className="mono">task corpus:report</span>, ale każda
              liczba prowadzi do listy wierszy, a każdy wiersz — do swojego źródła.
            </p>
            <ul className="health">
              {data.health.map((check) => (
                <li key={check.key}>
                  <span className={`n ${check.count === 0 ? "zero" : check.severity}`}>
                    {check.count}
                  </span>
                  <span>
                    <a href={`/inspect/health/${check.key}`}>{check.title}</a>
                    <span className="tag" style={{ marginLeft: ".3rem" }}>
                      {check.severity === "problem" ? "problem" : "info"}
                    </span>
                    <span className="why small">{check.why}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h2>Kolumny, których nikt nie wypełnia</h2>
            <p className="small" style={{ marginTop: 0 }}>
              Schemat je obiecuje, żaden przebieg dziś nie pisze. Licznik mówi, ile wierszy
              ma wartość nietkniętą — gdy spadnie poniżej 100%, ktoś zaczął.
            </p>
            <table>
              <thead>
                <tr>
                  <th>tabela.kolumna</th>
                  <th className="n">nietknięte</th>
                  <th className="n">wierszy</th>
                </tr>
              </thead>
              <tbody>
                {data.empty_columns.map((entry) => (
                  <tr key={`${entry.table}.${entry.column}`}>
                    <td className="mono">
                      <a href={`/inspect/${entry.table}`}>{entry.table}</a>.{entry.column}
                    </td>
                    <td className="n">{entry.untouched}</td>
                    <td className="n">{entry.total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Chrome>
  );
}

/** Jedna kontrola zdrowia i wiersze, które ją zapaliły. */
export function InspectHealth() {
  const key = window.location.pathname.replace(/^\/inspect\/health\//, "");
  const { data, failure } = useRemote(() => fetchHealth(key), [key]);

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
        <p className="small">Wczytuję kontrolę…</p>
      </Chrome>
    );
  }

  return (
    <Chrome
      scopeQuery=""
      subtitle={
        <>
          <a href="/inspect">Inspektor</a> › zdrowie danych · {data.rows.length} wierszy
        </>
      }
    >
      <div className="card">
        <h2>
          {data.check.title}
          <span className="tag" style={{ marginLeft: ".4rem" }}>
            {data.check.severity}
          </span>
        </h2>
        <p className="small" style={{ marginTop: 0 }}>
          {data.check.why}
        </p>
        <p className="small">
          Tabela:{" "}
          <a className="mono" href={`/inspect/${data.check.table}`}>
            {data.check.table}
          </a>
        </p>

        <table>
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="small">
                  Nic — ta kontrola jest dziś czysta.
                </td>
              </tr>
            ) : (
              data.rows.map((row, index) => (
                <tr key={index}>
                  {row.map((cell, position) => (
                    <td
                      key={position}
                      className={data.columns[position] === "id" ? "mono" : undefined}
                      title={cell.full}
                    >
                      {cell.link ? (
                        <a className="mono" href={cell.link}>
                          {data.columns[position] === "id" ? `#${cell.text}` : cell.text}
                        </a>
                      ) : (
                        cell.text
                      )}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Chrome>
  );
}
