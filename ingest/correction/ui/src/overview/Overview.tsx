import { useCallback, useEffect, useState } from "react";

import { Chrome, Failure } from "../app/Chrome";
import { fetchOverview, scopeQuery } from "../app/api";
import type { Overview as OverviewData, TaskRow, YearRow } from "../app/api";

/**
 * Przegląd korekty: liczby S8, pokrycie per rocznik i lista zadań z filtrem.
 * Pierwszy ekran przepisany z Jinja — to, co pokazuje, jest bez zmian.
 *
 * Filtr siedzi w ADRESIE, a nie tylko w stanie komponentu: link do „czeka,
 * rocznik 2023" ma się dać wkleić w notatce, a przycisk „wstecz" ma działać.
 */
export function Overview() {
  const [query, setQuery] = useState(() => window.location.search);
  const [data, setData] = useState<OverviewData | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const onPop = () => setQuery(window.location.search);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    let current = true;
    setFailure(null);
    fetchOverview(query)
      .then((next) => {
        if (current) setData(next);
      })
      .catch((error: Error) => {
        if (current) setFailure(error.message);
      });
    // Odpowiedź na PORZUCONE zapytanie nie ma prawa nadpisać świeższej:
    // filtr przełączony dwa razy pod rząd potrafi wrócić w odwrotnej kolejności.
    return () => {
      current = false;
    };
  }, [query]);

  const go = useCallback((next: string) => {
    window.history.pushState(null, "", next === "" ? "/" : next);
    setQuery(next);
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
        <p className="small">Wczytuję…</p>
      </Chrome>
    );
  }

  const scope = scopeQuery({
    year: data.selected.year === null ? "" : String(data.selected.year),
    code: data.selected.code ?? "",
    variant: data.selected.variant ?? "",
  });

  return (
    <Chrome
      scopeQuery={scope}
      subtitle={`${data.numbers.status.decided}/${data.numbers.status.total} rozstrzygniętych`}
      actions={
        data.next_id !== null ? (
          <a href={`/next${scope}`}>
            <button className="primary">Następne do korekty →</button>
          </a>
        ) : (
          <span className="small">
            {scope === "" ? "wszystko rozstrzygnięte" : "zakres rozstrzygnięty"}
          </span>
        )
      }
    >
      <Statistics numbers={data.numbers} />
      <YearCoverage years={data.numbers.years} />
      <Tasks data={data} scope={scope} onFilter={go} />
    </Chrome>
  );
}

function Statistics({ numbers }: { numbers: OverviewData["numbers"] }) {
  const { status, durations, forecast, assets } = numbers;
  return (
    <div className="card">
      <h2>Statystyka korekty — pomiar S8</h2>
      <div className="metrics">
        <Metric value={`${Math.round(100 * status.done_share)}%`}>
          rozstrzygnięte
          <br />({status.pending} czeka)
        </Metric>
        <Metric value={`${Math.round(100 * status.hit_share)}%`}>
          parser trafił sam
          <br />
          (bez ręcznej poprawki)
        </Metric>
        <Metric value={`${Math.round(durations.median)} s`}>
          mediana na zadanie
          <br />({durations.events} rozstrzygnięć)
        </Metric>
        <Metric value={`${forecast.hours.toFixed(1)} h`}>
          prognoza reszty
          <br />
          mediana × {forecast.tasks} zadań
        </Metric>
        <Metric value={String(status.rejected)}>
          odrzucone
          <br />
          (dziury w korpusie)
        </Metric>
        <Metric value={`${assets.cropped}/${assets.total}`}>
          wycinków w blobie
          <br />
          (ramka dociągnięta: {assets.framed})
        </Metric>
      </div>
      <p className="small" style={{ marginBottom: 0 }}>
        Prognoza mnoży <strong>medianę</strong>, nie średnią: formularz zostawiony otwarty na
        noc wchodzi do dziennika jako praca i zawyża sumę ({durations.long}{" "}
        {durations.long === 1 ? "tak długa sesja" : "tak długich sesji"}).
      </p>
    </div>
  );
}

function Metric({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <div className="metric">
      <b>{value}</b>
      <span>{children}</span>
    </div>
  );
}

function YearCoverage({ years }: { years: readonly YearRow[] }) {
  return (
    <div className="card">
      <h2>Pokrycie per rocznik</h2>
      <table>
        <thead>
          <tr>
            <th>rocznik</th>
            <th className="n">razem</th>
            <th className="n">czeka</th>
            <th className="n">bez zmian</th>
            <th className="n">poprawione</th>
            <th className="n">odrzucone</th>
          </tr>
        </thead>
        <tbody>
          {years.length === 0 ? (
            <tr>
              <td colSpan={6} className="small">
                Korpus pusty — uruchom <span className="mono">task ingest</span>.
              </td>
            </tr>
          ) : (
            years.map((row) => (
              <tr key={row.year}>
                <td className="mono">{row.year}</td>
                <td className="n">{row.total}</td>
                <td className="n">{row.pending}</td>
                <td className="n">{row.approved}</td>
                <td className="n">{row.corrected}</td>
                <td className="n">{row.rejected}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function Tasks({
  data,
  scope,
  onFilter,
}: {
  data: OverviewData;
  scope: string;
  onFilter: (query: string) => void;
}) {
  function submit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    onFilter(
      scopeQuery({
        status: String(form.get("status") ?? ""),
        year: String(form.get("year") ?? ""),
        code: String(form.get("code") ?? ""),
        variant: String(form.get("variant") ?? ""),
      }),
    );
  }

  return (
    <div className="card">
      <h2>Zadania</h2>
      <form onSubmit={submit} className="small" style={{ marginBottom: ".8rem" }}>
        <Picker label="status" name="status" value={data.selected.status ?? ""}>
          {Object.entries(data.status_labels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Picker>
        <Picker
          label="rocznik"
          name="year"
          value={data.selected.year === null ? "" : String(data.selected.year)}
        >
          {data.options.years.map((year) => (
            <option key={year} value={year}>
              {year}
            </option>
          ))}
        </Picker>
        <Picker label="kod" name="code" value={data.selected.code ?? ""}>
          {data.options.codes.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </Picker>
        <Picker label="wariant" name="variant" value={data.selected.variant ?? ""}>
          {data.options.variants.map((variant) => (
            <option key={variant} value={variant}>
              {variant}
            </option>
          ))}
        </Picker>
        <button>Filtruj</button>
      </form>
      <p className="small" style={{ margin: "-.4rem 0 .8rem" }}>
        Rocznik, kod i wariant wyznaczają też zakres przycisku „Następne do korekty" — pilot
        zostaje w swoim roczniku.
      </p>

      <table>
        <thead>
          <tr>
            <th>klucz</th>
            <th>zad.</th>
            <th className="n">pkt</th>
            <th>rodzaj</th>
            <th>status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {data.tasks.length === 0 ? (
            <tr>
              <td colSpan={6} className="small">
                Nic nie pasuje do filtra.
              </td>
            </tr>
          ) : (
            data.tasks.map((task) => (
              <TaskLine
                key={task.id}
                task={task}
                scope={scope}
                label={data.status_labels[task.review_status] ?? task.review_status}
              />
            ))
          )}
        </tbody>
      </table>
      {data.tasks.length >= 200 && (
        <p className="small" style={{ marginBottom: 0 }}>
          Lista ucięta do 200 pozycji — do pracy służy przycisk „Następne do korekty", nie
          przewijanie.
        </p>
      )}
    </div>
  );
}

function TaskLine({ task, scope, label }: { task: TaskRow; scope: string; label: string }) {
  return (
    <tr>
      <td className="mono small">
        {task.code}-{task.variants || "—"} · {task.session}
      </td>
      <td className="mono">{task.number}</td>
      <td className="n">{task.max_points}</td>
      <td className="small">{task.kind}</td>
      <td>
        <span className={`tag ${task.review_status}`}>{label}</span>
      </td>
      <td>
        <a href={`/task/${task.id}${scope}`}>otwórz</a>
      </td>
    </tr>
  );
}

/** Lista wyboru z opcją „wszystkie" na czele — pusta wartość znaczy „bez filtra". */
function Picker({
  label,
  name,
  value,
  children,
}: {
  label: string;
  name: string;
  value: string;
  children: React.ReactNode;
}) {
  // Niekontrolowana z `defaultValue`: formularz czyta się dopiero przy „Filtruj",
  // więc trzymanie każdego pola w stanie nic by tu nie dało poza kodem.
  // `key` przy wartości, bo `defaultValue` działa tylko przy montowaniu —
  // bez tego powrót „wstecz" zmieniał listę zadań, ale nie ustawienie filtra.
  return (
    <label>
      {label}{" "}
      <select key={value} name={name} defaultValue={value}>
        <option value="">wszystkie</option>
        {children}
      </select>
    </label>
  );
}
