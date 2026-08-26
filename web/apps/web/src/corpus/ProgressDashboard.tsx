import { useEffect, useState } from "react";

import { corpus, failed, LOADING, type Loaded } from "./api";
import { count, decidedShare, percent, type CorpusProgress } from "./format";

/**
 * Pulpit postępu ingestu (W2.3). Liczy po CAŁEJ tabeli zadań, nie po widoku
 * korpusu: pytanie brzmi „ile jeszcze zostało", więc rekordy spoza korpusu
 * są tu treścią, nie szumem.
 */
export function ProgressDashboard() {
  const progress = useProgress();

  if (progress.state === "loading") {
    return <p className="muted">Wczytuję…</p>;
  }

  if (progress.state === "error") {
    return <p className="error">{progress.message}</p>;
  }

  return <ProgressView progress={progress.data} />;
}

export function ProgressView({ progress }: { readonly progress: CorpusProgress }) {
  const totals = progress.totals;

  return (
    <section className="progress">
      <h2>Postęp korekty</h2>

      <div className="metrics">
        <Metric
          value={`${count(totals.decided)}/${count(totals.tasks)}`}
          label="rozstrzygniętych zadań"
        />
        <Metric value={percent(totals.hitShare)} label="parser trafił sam (S8)" />
        <Metric
          value={`${count(totals.assetsDescribed)}/${count(totals.assets)}`}
          label="opisów rysunków zatwierdzonych (S7)"
        />
        <Metric
          value={`${count(totals.expressionsWithMathJson)}/${count(totals.expressions)}`}
          label="zapisów z MathJSON-em"
        />
        <Metric value={String(count(totals.rejected))} label="odrzuconych (dziury)" />
      </div>

      <table>
        <caption className="muted">
          Kolumna „czeka” to praca, która została do zrobienia w ekranie korekty.
        </caption>
        <thead>
          <tr>
            <th>rocznik</th>
            <th>razem</th>
            <th>bez zmian</th>
            <th>poprawione</th>
            <th>odrzucone</th>
            <th>czeka</th>
            <th>postęp</th>
          </tr>
        </thead>
        <tbody>
          {progress.years.map((year) => (
            <tr key={String(year.year)}>
              <td>{count(year.year)}</td>
              <td>{count(year.total)}</td>
              <td>{count(year.approved)}</td>
              <td>{count(year.corrected)}</td>
              <td>{count(year.rejected)}</td>
              <td>{count(year.pending)}</td>
              <td>
                {/* `progress`, nie własny div ze szerokością: element natywny
                    czyta czytnik ekranu, a stylowania ponad czytelność nie ma. */}
                <progress value={decidedShare(year)} max={1}>
                  {percent(decidedShare(year))}
                </progress>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Metric({ value, label }: { readonly value: string; readonly label: string }) {
  return (
    <div className="metric">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

function useProgress(): Loaded<CorpusProgress> {
  const [state, setState] = useState<Loaded<CorpusProgress>>(LOADING);

  useEffect(() => {
    let alive = true;
    corpus
      .GET("/corpus/progress")
      .then(({ data, error }) => {
        if (!alive) {
          return;
        }
        setState(
          error === undefined && data !== undefined
            ? { state: "ready", data }
            : failed("nie udało się wczytać postępu", error),
        );
      })
      .catch((error: unknown) => alive && setState(failed("API nie odpowiada", error)));
    return () => {
      alive = false;
    };
  }, []);

  return state;
}
