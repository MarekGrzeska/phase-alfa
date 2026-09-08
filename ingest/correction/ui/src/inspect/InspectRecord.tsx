import { useCallback, useEffect, useState } from "react";

import { Chrome, Failure } from "../app/Chrome";
import { fetchRecord } from "./api";
import type { Provenance, RecordColumn, RecordData } from "./api";
import "./inspect.css";

/**
 * Jeden wiersz: wartości z ich źródłem, rodzice, dzieci i strona PDF, z której
 * rekord wyszedł. Numer strony jest stanem WIDOKU, więc siedzi w adresie —
 * link „patrz na stronę 13" ma się dać wkleić w notatce.
 */
export function InspectRecord() {
  // `/inspect/{tabela}/{id}` — nazwa tabeli i identyfikator prosto z adresu.
  const [, table = "", id = ""] = /^\/inspect\/([^/]+)\/([^/?]+)/.exec(
    window.location.pathname,
  ) ?? [];
  const [query, setQuery] = useState(window.location.search);
  const [data, setData] = useState<RecordData | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const onPop = () => setQuery(window.location.search);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    let current = true;
    setFailure(null);
    fetchRecord(table, id, query)
      .then((next) => {
        if (current) setData(next);
      })
      .catch((error: Error) => {
        if (current) setFailure(error.message);
      });
    return () => {
      current = false;
    };
  }, [table, id, query]);

  const showPage = useCallback((page: number) => {
    const params = new URLSearchParams(window.location.search);
    params.set("_pdfpage", String(page));
    window.history.pushState(null, "", `?${params.toString()}`);
    setQuery(`?${params.toString()}`);
  }, []);

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
        <p className="small">Wczytuję wiersz…</p>
      </Chrome>
    );
  }

  return (
    <Chrome
      scopeQuery=""
      subtitle={
        <>
          <a href="/inspect">Inspektor</a> ›{" "}
          <a href={`/inspect/${data.table.name}`}>{data.table.name}</a> › #{data.id}
        </>
      }
      actions={
        data.table.name === "task" ? (
          <a href={`/task/${data.id}`}>
            <button>Otwórz w korekcie →</button>
          </a>
        ) : undefined
      }
    >
      <div className="cols3">
        <div>
          <div className="card">
            <h2 className="mono">
              {data.table.name} #{data.id}
            </h2>
            <p className="small" style={{ marginTop: 0 }}>
              {data.table.note}
            </p>

            {data.row_notes.length > 0 && (
              <div className="notes small">
                <strong>Ten wiersz:</strong>
                {data.row_notes.map((note, index) => (
                  <p key={index}>{note}</p>
                ))}
              </div>
            )}

            <table className="rec">
              <thead>
                <tr>
                  <th>kolumna</th>
                  <th>wartość</th>
                  <th>źródło</th>
                </tr>
              </thead>
              <tbody>
                {data.columns.map((column) => (
                  <tr key={column.name}>
                    <td className="k">{column.name}</td>
                    <td className="v">
                      <Value column={column} />
                    </td>
                    <td className={`s${column.source.startsWith("nikt") ? " none" : ""}`}>
                      {column.source}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.parents.length > 0 && (
            <div className="card">
              <h3>Rodzice</h3>
              <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
                {data.parents.map((parent) => (
                  <li key={parent.column}>
                    <span className="mono">{parent.column}</span> →{" "}
                    <a className="mono" href={parent.url}>
                      {parent.table} #{parent.value}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.children.length > 0 && (
            <div className="card">
              <h3>Dzieci</h3>
              <ul className="kids" style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {data.children.map((child) => (
                  <li key={`${child.table}.${child.column}`}>
                    <a className="mono" href={child.url}>
                      {child.table}
                    </a>{" "}
                    <span className="small">
                      ({child.count}) przez <span className="mono">{child.column}</span>
                    </span>
                    {child.rows.length > 0 && (
                      <div className="rows">
                        {child.rows.map((row, index) => (
                          <div key={index}>
                            {row.url !== null && (
                              <a className="mono" href={row.url}>
                                #{row.id}
                              </a>
                            )}{" "}
                            {row.text}
                          </div>
                        ))}
                        {child.count > child.rows.length && (
                          <div className="small">
                            … <a href={child.url}>wszystkie {child.count}</a>
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div>
          <div className="card">
            <h2>Źródło w plikach</h2>
            <Source
              source={data.source}
              pdfPage={data.pdf_page}
              cropName={data.crop_name}
              onPage={showPage}
            />
          </div>
        </div>
      </div>
    </Chrome>
  );
}

function Value({ column }: { column: RecordColumn }) {
  if (column.kind === "null") {
    return <span className="null">NULL</span>;
  }
  if (column.kind === "parent") {
    return (
      <a className="mono" href={`/inspect/${column.parent}/${column.value}`}>
        {column.parent} #{column.value}
      </a>
    );
  }
  if (column.kind === "json") {
    return <pre>{column.text}</pre>;
  }
  if (column.kind === "status") {
    return <span className={`tag ${column.value}`}>{column.text}</span>;
  }
  return <>{column.text}</>;
}

function Source({
  source,
  pdfPage,
  cropName,
  onPage,
}: {
  source: Provenance;
  pdfPage: number;
  cropName: string | null;
  onPage: (page: number) => void;
}) {
  const last = source.document_pages;
  return (
    <>
      {source.note !== null && (
        <p className="small" style={{ marginTop: 0 }}>
          {source.note}
        </p>
      )}

      {source.document_id !== null ? (
        <>
          <p className="small mono" style={{ margin: 0 }}>
            <a href={`/inspect/document/${source.document_id}`}>
              document #{source.document_id}
            </a>{" "}
            · {source.document_kind} · {source.document_path}
            {source.page !== null && (
              <>
                {" "}
                · strona {source.page}
                {last !== null && ` z ${last}`}
              </>
            )}
          </p>
          {source.file_exists ? (
            <>
              <div className="src-links small">
                <a href={`/inspect/document/${source.document_id}.pdf`} target="_blank" rel="noreferrer">
                  ⬇ otwórz PDF
                </a>
                <a
                  href={`/inspect/document/${source.document_id}.pdf#page=${pdfPage}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  otwórz na stronie {pdfPage}
                </a>
                <a
                  href={`/inspect/document/${source.document_id}/page/${pdfPage}.png`}
                  target="_blank"
                  rel="noreferrer"
                >
                  ⤢ sama strona jako PNG
                </a>
              </div>

              <div className="pdfnav">
                <button
                  type="button"
                  className="small"
                  disabled={pdfPage <= 1}
                  onClick={() => onPage(pdfPage - 1)}
                >
                  ← poprzednia
                </button>
                <span className="jump small">
                  strona {pdfPage}
                  {last !== null && ` z ${last}`}
                </span>
                <button
                  type="button"
                  className="small"
                  disabled={last !== null && pdfPage >= last}
                  onClick={() => onPage(pdfPage + 1)}
                >
                  następna →
                </button>
                {source.page !== null && pdfPage !== source.page && (
                  <button type="button" className="small" onClick={() => onPage(source.page!)}>
                    wróć do strony rekordu ({source.page})
                  </button>
                )}
              </div>

              <div className="page-box">
                {source.bbox !== null && source.page_size !== null && pdfPage === source.page ? (
                  // viewBox w PUNKTACH PDF — ramka z bazy nakłada się bez przeliczania.
                  // Rysuje się WYŁĄCZNIE na swojej stronie: na innej wisiałaby w powietrzu.
                  <svg
                    viewBox={`0 0 ${source.page_size[0]} ${source.page_size[1]}`}
                    role="img"
                    aria-label={`strona ${pdfPage} z ramką zasobu`}
                  >
                    <image
                      href={`/inspect/document/${source.document_id}/page/${pdfPage}.png`}
                      width={source.page_size[0]}
                      height={source.page_size[1]}
                    />
                    <rect
                      x={source.bbox[0]}
                      y={source.bbox[1]}
                      width={source.bbox[2] - source.bbox[0]}
                      height={source.bbox[3] - source.bbox[1]}
                      fill="rgba(200,50,40,.12)"
                      stroke="#c0392b"
                      strokeWidth="2"
                    />
                  </svg>
                ) : (
                  <img
                    src={`/inspect/document/${source.document_id}/page/${pdfPage}.png`}
                    alt={`strona ${pdfPage}`}
                    loading="lazy"
                  />
                )}
              </div>
              {source.bbox !== null && (
                <p className="small mono" style={{ margin: ".4rem 0 0" }}>
                  bbox = [{source.bbox.map((value) => value.toFixed(1)).join(", ")}] pt
                  {pdfPage !== source.page && ` — ramka jest na stronie ${source.page}`}
                </p>
              )}
            </>
          ) : (
            <p className="missing">
              Pliku nie ma w mirrorze pod tą ścieżką. To nie jest NULL — baza wskazuje plik,
              którego dysk nie ma (<span className="mono">MIRROR_ROOT</span>?).
            </p>
          )}
        </>
      ) : source.related.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>rola</th>
              <th>plik</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {source.related.map((document) => (
              <tr key={document.id}>
                <td className="mono">{document.role}</td>
                <td className="mono small">{document.path}</td>
                <td>
                  <a href={`/inspect/document/${document.id}`}>document #{document.id}</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        source.note === null && <p className="small">Brak dokumentu źródłowego dla tego wiersza.</p>
      )}

      {source.asset_id !== null && (
        <>
          <h3 style={{ marginTop: "1rem" }}>Wycinek z bloba</h3>
          {source.crop_exists ? (
            <>
              <div className="crop">
                <img src={`/asset/${source.asset_id}.png`} alt="wycinek" loading="lazy" />
              </div>
              <p className="small mono" style={{ margin: ".3rem 0 0" }}>
                {source.crop_path}
              </p>
            </>
          ) : (
            <p className="missing">
              W blobie nie ma pliku <span className="mono">{cropName}</span> —{" "}
              <span className="mono">task crops</span> nie przeszedł po tym zasobie albo ramka
              jest świeższa niż cięcie.
            </p>
          )}
        </>
      )}
    </>
  );
}
