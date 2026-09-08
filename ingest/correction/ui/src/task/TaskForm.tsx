import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { Chrome, Failure } from "../app/Chrome";
import { scopeQuery } from "../app/api";
import { fetchTask, fieldsOf, saveTask } from "./api";
import type { Asset, Criterion, Requirement, Task, TaskPayload, Version } from "./types";

/**
 * Formularz korekty jednego zadania — ścieżka krytyczna A2.
 *
 * Formularz jest NIEKONTROLOWANY: wartości trzyma DOM, a wysyłamy to, co da
 * `FormData`. Nie z lenistwa — na braku niezaznaczonego pola wyboru stoi
 * kasowanie wierszy, a nazwy pól (`criterion.12.points`) rozstrzyga `db.save`.
 * Przepisanie tego na stan Reacta znaczyłoby przepisanie reguł zapisu do
 * korpusu przy okazji migracji frontu, a to dwie różne zmiany.
 */
export function TaskForm() {
  const taskId = taskIdFromPath(window.location.pathname);
  const [data, setData] = useState<TaskPayload | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [errors, setErrors] = useState<readonly string[]>([]);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState<number | null>(pageFromQuery());
  const [editedBefore, setEditedBefore] = useState(
    new URLSearchParams(window.location.search).get("edited_before") === "1",
  );
  // Rośnie po każdej odpowiedzi serwera. Formularz jest niekontrolowany, więc
  // `defaultValue` działa tylko przy montowaniu — bez przemontowania pola
  // pokazywałyby stan sprzed dołożenia progu.
  const [revision, setRevision] = useState(0);

  const scope = {
    year: new URLSearchParams(window.location.search).get("year") ?? "",
    code: new URLSearchParams(window.location.search).get("code") ?? "",
    variant: new URLSearchParams(window.location.search).get("variant") ?? "",
  };
  const query = scopeQuery(scope);

  useEffect(() => {
    if (taskId === null) {
      setFailure("adres nie wskazuje zadania");
      return;
    }
    let current = true;
    fetchTask(taskId, page)
      .then((next) => {
        if (current) {
          setData(next);
          setRevision((n) => n + 1);
        }
      })
      .catch((error: Error) => {
        if (current) setFailure(error.message);
      });
    return () => {
      current = false;
    };
    // Zależność tylko od zadania, celowo. Zmiana strony podglądu NIE ma
    // przeładowywać formularza: obrazek bierze numer z własnego adresu,
    // a odświeżenie zgubiłoby to, co korektor zdążył wpisać.
  }, [taskId]);

  const submit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (data === null || taskId === null || busy) {
        return;
      }
      const submitter = (event.nativeEvent as SubmitEvent).submitter as
        | HTMLButtonElement
        | null;
      // Enter w polu tekstowym trafia w pierwszy przycisk formularza; „save"
      // jest wtedy jedyną rozsądną domyślną drogą — zapisz i zostań.
      const action = submitter?.value || "save";

      setBusy(true);
      const result = await saveTask({
        taskId,
        action,
        startedAt: data.started_at,
        page,
        editedBefore,
        scope,
        fields: fieldsOf(event.currentTarget),
      });
      setBusy(false);

      if (result.kind === "redirect") {
        window.location.assign(result.to);
        return;
      }
      if (result.kind === "errors") {
        setErrors(result.messages);
        return;
      }
      setErrors([]);
      setData(result.payload);
      setEditedBefore(result.payload.edited_before ?? editedBefore);
      setRevision((n) => n + 1);
    },
    [busy, data, editedBefore, page, scope, taskId],
  );

  if (failure !== null) {
    return (
      <Chrome scopeQuery={query}>
        <Failure reason={failure} />
      </Chrome>
    );
  }
  if (data === null) {
    return (
      <Chrome scopeQuery={query}>
        <p className="small">Wczytuję zadanie…</p>
      </Chrome>
    );
  }

  const { task, nav, status_labels: labels } = data;
  const shownPage = page ?? data.page;

  return (
    <Chrome
      scopeQuery={query}
      subtitle={
        <>
          <span className="mono">
            {task.code} · {task.session}
          </span>{" "}
          · zadanie {task.number} ·{" "}
          <span className={`tag ${task.review_status}`}>
            {labels[task.review_status] ?? task.review_status}
          </span>
        </>
      }
      actions={
        <>
          {nav.previous !== null && (
            <a href={`/task/${nav.previous}${query}`} title="przejście bez zapisu formularza">
              ← poprzednie
            </a>
          )}
          {nav.next !== null && (
            <a href={`/task/${nav.next}${query}`} title="przejście bez zapisu formularza">
              następne →
            </a>
          )}
          {(nav.previous !== null || nav.next !== null) && (
            <span className="small">(bez zapisu)</span>
          )}
        </>
      }
    >
      {errors.length > 0 && (
        <div className="errors">
          <strong>Nie zapisano — popraw i spróbuj ponownie:</strong>
          <ul>
            {errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="split">
        <div className="viewer">
          <KeyPage
            task={task}
            page={shownPage}
            documentPages={data.document_pages}
            onPage={(next) => {
              setPage(next);
              // Strona podglądu jest stanem widoku, więc siedzi w adresie:
              // link „patrz na stronę 13" ma się dać wkleić w notatce.
              const params = new URLSearchParams(window.location.search);
              params.set("page", String(next));
              window.history.replaceState(null, "", `?${params.toString()}`);
            }}
          />
          {task.solutions.length > 0 && (
            <div className="card">
              <h2>
                Rozwiązania przykładowe <span className="small">(z klucza, tylko do wglądu)</span>
              </h2>
              {task.solutions.map((solution, index) => (
                <div key={index}>
                  <h3>
                    {solution.method || "sposób"} · {solution.points} pkt
                  </h3>
                  <p className="small">{solution.content}</p>
                </div>
              ))}
            </div>
          )}
          {task.rules.length > 0 && (
            <div className="card">
              <h2>Reguły arkusza w zakresie tego zadania</h2>
              {task.rules.map((rule, index) => (
                <p className="small" key={index}>
                  <span className="tag">{rule.kind}</span>{" "}
                  {rule.tasks_from !== null && (
                    <span className="mono">
                      {rule.tasks_from}–{rule.tasks_to}
                    </span>
                  )}{" "}
                  {rule.content}
                </p>
              ))}
              <p className="small" style={{ marginBottom: 0 }}>
                Reguły wiszą na arkuszu, nie na zadaniu — poprawia się je razem z arkuszem,
                więc tutaj są tylko kontekstem oceny.
              </p>
            </div>
          )}
        </div>

        <form key={revision} onSubmit={submit}>
          {/* Domyślny przycisk formularza: przeglądarka wysyła Enter z pola
              tekstowego do PIERWSZEGO przycisku w drzewie. Bez tego Enter
              w „numer" trafiał w „Wytnij" albo „+ próg punktowy". */}
          <button type="submit" value="save" className="default-submit" tabIndex={-1} aria-hidden>
            Zapisz
          </button>

          {task.model_notes !== null && <ModelNotesBox notes={task.model_notes} />}
          <Checklist task={task} />
          <TaskRow task={task} kinds={data.task_kinds} />
          <Versions versions={task.versions} />
          <Criteria task={task} />
          <Requirements task={task} available={data.requirements} />
          {task.assets.length > 0 && <Assets assets={task.assets} />}
          <Decide task={task} editedBefore={editedBefore} busy={busy} />
        </form>
      </div>
    </Chrome>
  );
}

function taskIdFromPath(path: string): number | null {
  const match = /^\/task\/(\d+)/.exec(path);
  return match === null ? null : Number.parseInt(match[1], 10);
}

function pageFromQuery(): number | null {
  const raw = new URLSearchParams(window.location.search).get("page");
  return raw !== null && /^\d+$/.test(raw) ? Number.parseInt(raw, 10) : null;
}

function KeyPage({
  task,
  page,
  documentPages,
  onPage,
}: {
  task: Task;
  page: number | null;
  documentPages: number | null;
  onPage: (page: number) => void;
}) {
  return (
    <div className="card">
      <h2>
        Klucz — strona {page ?? "—"}
        {documentPages !== null && ` z ${documentPages}`}
      </h2>
      {page !== null ? (
        <>
          <img
            src={`/task/${task.id}/page.png?n=${page}`}
            alt={`strona ${page} klucza ${task.code}`}
          />
          <p className="small" style={{ margin: ".5rem 0 0" }}>
            {page > 1 && (
              <button type="button" className="small" onClick={() => onPage(page - 1)}>
                ← strona {page - 1}
              </button>
            )}{" "}
            {(documentPages === null || page < documentPages) && (
              <button type="button" className="small" onClick={() => onPage(page + 1)}>
                strona {page + 1} →
              </button>
            )}{" "}
            <span className="mono">{task.document_path}</span>
          </p>
        </>
      ) : (
        <p className="small">
          Ten klucz wczytano razem z arkuszami przed migracją 0004, więc numer strony
          w KLUCZU nie został zapisany (<span className="mono">task.page</span> jest puste).
          Przeładuj go poleceniem <span className="mono">task ingest</span>, żeby odzyskać
          podgląd.
        </p>
      )}
    </div>
  );
}

function ModelNotesBox({ notes }: { notes: NonNullable<Task["model_notes"]> }) {
  return (
    <div className="hints">
      <strong className="small">
        Model {notes.model}{" "}
        {notes.action === "unsure"
          ? "nie rozstrzygnął tego zadania"
          : "rozstrzygnął, ale zostawił uwagi"}{" "}
        ({notes.when}):
      </strong>
      <ul className="small">
        {notes.reasons.map((reason, index) => (
          <li key={index}>{reason}</li>
        ))}
      </ul>
    </div>
  );
}

function Checklist({ task }: { task: Task }) {
  const unframed = task.assets.filter((asset) => !asset.framed);
  return (
    <div className="card checklist">
      <h2>Co sprawdzasz w tym zadaniu</h2>
      <ol className="small">
        <li>
          Treść i odpowiedź wzorcowa zgadzają się z kluczem po lewej
          {task.kind === "closed" && " — w zadaniu zamkniętym to jest cała ocena"}.
        </li>
        {(task.kind !== "closed" || task.criteria.length > 0) && (
          <li>
            Progi punktowe, pod nimi warunki, pod warunkami zapisy równoważne. Każdy poziom to
            alternatywa: dowolny warunek daje próg.
          </li>
        )}
        <li>Wymaganie podstawy programowej jest dopięte.</li>
        {task.assets.length > 0 && (
          <li>
            Wycinek rysunku obejmuje sam rysunek, nie całą stronę
            {unframed.length > 0 && (
              <>
                {" — "}
                <strong style={{ color: "var(--warn)" }}>
                  tu {unframed.length} jeszcze bez ramki
                </strong>
              </>
            )}
            .
          </li>
        )}
      </ol>
      <p className="small" style={{ margin: ".5rem 0 0" }}>
        Przyciski „+ …" i „Wytnij" tylko zapisują i wracają tutaj. Enter w polu też.
        Rozstrzyga dopiero „Zatwierdź" albo „Odrzuć" na dole.
      </p>
    </div>
  );
}

function TaskRow({ task, kinds }: { task: Task; kinds: readonly string[] }) {
  return (
    <div className="card">
      <h2>Zadanie</h2>
      <div className="row">
        <label>
          numer <input name="task.number" defaultValue={task.number} size={6} />
        </label>
        <label>
          pula punktów{" "}
          <input
            name="task.max_points"
            defaultValue={task.max_points ?? ""}
            size={4}
            inputMode="numeric"
          />
        </label>
        <label>
          rodzaj{" "}
          <select name="task.kind" defaultValue={task.kind}>
            {kinds.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}

function Versions({ versions }: { versions: readonly Version[] }) {
  return (
    <div className="card">
      <h2>Wersje i odpowiedzi wzorcowe</h2>
      {versions.length === 0 ? (
        <p className="small">
          Zadanie nie ma ani jednej wersji — to błąd ładowania, nie korekty.
        </p>
      ) : (
        versions.map((version) => (
          <div key={version.id}>
            <h3 className="mono">
              {version.code}-{version.variant}
              {version.version !== null && ` wersja ${version.version}`}
            </h3>
            <textarea
              name={`version.${version.id}.content`}
              rows={3}
              defaultValue={version.content ?? ""}
              placeholder="treść zadania — pusta, dopóki ingest nie doczytał arkusza"
            />
            {version.answers.map((answer) => (
              <div className="row" style={{ margin: ".3rem 0" }} key={answer.id}>
                <span className="small">
                  odpowiedź{answer.part !== null && ` (${answer.part})`}
                </span>
                <input
                  name={`answer.${answer.id}.answer`}
                  defaultValue={answer.answer}
                  size={16}
                />
                <label className="del">
                  <input type="checkbox" name={`delete.answer.${answer.id}`} value="1" /> usuń
                </label>
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  );
}

function Criteria({ task }: { task: Task }) {
  return (
    <div className="card">
      <h2>
        Kryteria <span className="small">próg → warunek → zapis równoważny</span>
      </h2>
      {task.hints.length > 0 && (
        // Podpowiedź, nie drugi formularz: LLM proponuje, człowiek zatwierdza.
        // Nic stąd nie wchodzi do korpusu samo — trzeba to przepisać w pole.
        <div className="hints">
          <strong className="small">
            Model {task.hints[0].model} widzi to inaczej ({task.hints.length}{" "}
            {task.hints.length === 1 ? "różnica" : "różnic"}):
          </strong>
          <ul className="small">
            {task.hints.map((hint, index) => (
              <li key={index}>
                <span className="tag">{hint.points} pkt</span>{" "}
                {hint.kind === "criterion_missing"
                  ? "brak progu w rekordzie"
                  : hint.kind === "criterion_extra"
                    ? "próg, którego model nie widzi"
                    : "brak warunku"}{" "}
                — {hint.hint}
                {hint.detail.map((line, position) => (
                  <span key={position}>
                    <br />
                    <span className="mono">≡ {line}</span>
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}

      {task.criteria.length === 0 ? (
        <NoCriteria task={task} />
      ) : (
        task.criteria.map((criterion) => (
          <CriterionBox key={criterion.id} criterion={criterion} task={task} />
        ))
      )}
      <button name="action" value="add:criterion" className="small">
        + próg punktowy
      </button>
    </div>
  );
}

function NoCriteria({ task }: { task: Task }) {
  if (task.kind === "closed" && !task.closed_have_criteria) {
    return (
      <p className="small">
        Brak kryteriów to tu <strong>norma dokumentu</strong>: ten klucz nie ma sekcji
        kryteriów dla żadnego zadania zamkniętego — tak wygląda rocznik 2019, gdzie oceny
        pilnuje sama odpowiedź wzorcowa. Nie ma czego szukać w kluczu; zatwierdź, gdy
        odpowiedź się zgadza.
      </p>
    );
  }
  return (
    <p className="small" style={{ color: "var(--warn)" }}>
      Brak kryteriów to tu <strong>dziura</strong>, nie norma:{" "}
      {task.kind === "closed"
        ? "inne zadania zamknięte tego klucza kryteria mają"
        : "zadanie otwarte bez progów nie da się ocenić"}
      . Dopisz progi z klucza albo odrzuć rekord.
    </p>
  );
}

function CriterionBox({ criterion, task }: { criterion: Criterion; task: Task }) {
  const overPool =
    criterion.points !== null &&
    task.max_points !== null &&
    criterion.points > task.max_points;

  return (
    <div className="criterion">
      <div className="row">
        <label>
          <input
            name={`criterion.${criterion.id}.points`}
            defaultValue={criterion.points ?? ""}
            size={3}
            inputMode="numeric"
          />{" "}
          pkt
        </label>
        <input
          name={`criterion.${criterion.id}.label`}
          defaultValue={criterion.label ?? ""}
          placeholder="etykieta progu, np. pełne rozwiązanie"
          size={34}
        />
        <label className="del">
          <input type="checkbox" name={`delete.criterion.${criterion.id}`} value="1" /> usuń
          próg
        </label>
        {/* Ostrzeżenie, nie więz: schemat świadomie na to pozwala, bo taki zapis
            stoi w prawdziwym kluczu CKE (OMAP-900-2105, literówka komisji).
            Chodzi o to, żeby człowiek nie zrobił tego samego przez pomyłkę. */}
        {overPool && (
          <span
            className="tag"
            style={{ color: "var(--warn)", borderColor: "var(--warn)" }}
            title="Sekcja SPÓJNOŚĆ w raporcie ingestu też to pokaże"
          >
            próg ponad pulą zadania
          </span>
        )}
      </div>
      <textarea
        name={`criterion.${criterion.id}.description`}
        rows={2}
        defaultValue={criterion.description ?? ""}
        placeholder="treść progu, gdy klucz nie wypunktowuje warunków"
      />

      {criterion.conditions.map((condition) => (
        <div className="condition" key={condition.id}>
          <div className="row">
            <textarea
              name={`condition.${condition.id}.description`}
              rows={2}
              defaultValue={condition.description}
              placeholder="warunek — spełnienie DOWOLNEGO daje próg"
            />
            <label className="del">
              <input type="checkbox" name={`delete.condition.${condition.id}`} value="1" /> usuń
              warunek
            </label>
          </div>
          {condition.expressions.map((expression) => (
            <div className="expression" key={expression.id}>
              <input
                name={`expression.${expression.id}.expression`}
                defaultValue={expression.expression}
                placeholder="zapis równoważny"
              />
              {expression.mathjson !== null && <span className="tag">MathJSON</span>}
              <label className="del">
                <input type="checkbox" name={`delete.expression.${expression.id}`} value="1" />{" "}
                usuń
              </label>
            </div>
          ))}
          <button name="action" value={`add:expression:${condition.id}`} className="small">
            + zapis równoważny
          </button>
        </div>
      ))}
      <button name="action" value={`add:condition:${criterion.id}`} className="small">
        + warunek
      </button>
    </div>
  );
}

function Requirements({
  task,
  available,
}: {
  task: Task;
  available: readonly Requirement[];
}) {
  return (
    <div className="card">
      <h2>Wymagania podstawy programowej</h2>
      {task.requirements.length === 0 ? (
        <p className="small">Zadanie bez wymagania — mapa braków go nie zobaczy.</p>
      ) : (
        task.requirements.map((requirement) => (
          <div className="row" style={{ margin: ".2rem 0" }} key={requirement.id}>
            <span className="tag">{requirement.regime}</span>
            <span className="mono">
              {requirement.kind} {requirement.stage ?? ""} {requirement.path}
            </span>
            <span className="small">{requirement.content.slice(0, 90)}</span>
            <label className="del">
              <input type="checkbox" name={`delete.requirement.${requirement.id}`} value="1" />{" "}
              odepnij
            </label>
          </div>
        ))
      )}
      <div className="row" style={{ marginTop: ".5rem" }}>
        <select name="add_requirement" defaultValue="">
          <option value="">— dopnij wymaganie —</option>
          {available.map((requirement) => (
            <option key={requirement.id} value={requirement.id}>
              {requirement.regime} · {requirement.kind} {requirement.stage ?? ""}{" "}
              {requirement.path} — {requirement.content.slice(0, 70)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function Assets({ assets }: { assets: readonly Asset[] }) {
  return (
    <div className="card">
      <h2>
        Wycinki graficzne{" "}
        <span className="small">ramka w punktach PDF, od lewego górnego rogu</span>
      </h2>
      <p className="small">
        Strona zeszytu obok ma siatkę: kreska co 50 pt, podpis co 100. Odczytaj rogi rysunku,
        wpisz je i kliknij „Wytnij" — wycinek pokaże się pod ramką. Poprawianie jest tanie,
        plik nadpisuje się w miejscu.
      </p>
      {assets.map((asset) => (
        <AssetBox key={asset.id} asset={asset} />
      ))}
    </div>
  );
}

function AssetBox({ asset }: { asset: Asset }) {
  return (
    <div className="criterion">
      <div className="row">
        <span className="mono small">
          {asset.variant}
          {asset.version !== null && `-${asset.version}`} · {asset.kind}
        </span>
        <label className="small">
          strona <input name={`asset.${asset.id}.page`} defaultValue={asset.page} size={3} />
          {asset.paper_pages !== null && <span className="small"> z {asset.paper_pages}</span>}
        </label>
        {(["x0", "top", "x1", "bottom"] as const).map((name) => (
          <label className="small" key={name}>
            {name}{" "}
            <input
              name={`asset.${asset.id}.${name}`}
              defaultValue={asset.box[name]}
              size={6}
            />
          </label>
        ))}
        <button name="action" value="crop" className="small">
          Wytnij
        </button>
        {!asset.framed && <span className="tag pending">ramka: cała strona</span>}
      </div>
      <div className="split" style={{ marginTop: ".5rem" }}>
        <div>
          <p className="small" style={{ margin: "0 0 .2rem" }}>
            zeszyt zadań, strona {asset.page}
          </p>
          {asset.paper_path !== null ? (
            <img
              src={`/asset/${asset.id}/page.png?n=${asset.page}`}
              style={{ width: "100%" }}
              alt={`strona ${asset.page} zeszytu zadań z siatką współrzędnych`}
            />
          ) : (
            <p className="small">
              Brak zeszytu w bazie — przeładuj klucz poleceniem{" "}
              <span className="mono">task ingest -- --with-papers</span>.
            </p>
          )}
        </div>
        <div>
          <p className="small" style={{ margin: "0 0 .2rem" }}>
            wycinek <span className="mono">{asset.path}</span>
          </p>
          {asset.cropped ? (
            <img
              src={`/asset/${asset.id}.png`}
              style={{ maxWidth: "100%" }}
              alt={`wycinek zasobu ${asset.id}`}
            />
          ) : (
            <p className="small">Jeszcze nie wycięty.</p>
          )}
        </div>
      </div>
      {/* Alt-text (G2.5.2, pomiar S7). Test jakości jest jeden: czy z opisu da
          się rozwiązać zadanie bez patrzenia na rysunek. */}
      <div style={{ marginTop: ".6rem" }}>
        <div className="row">
          <span className="small">opis rysunku (alt-text)</span>
          <span
            className={`tag ${
              asset.description_status === "approved"
                ? "approved"
                : asset.description_status === "corrected"
                  ? "corrected"
                  : "pending"
            }`}
          >
            {asset.description_status}
          </span>
          <label className="small">
            <input
              type="checkbox"
              name={`asset.${asset.id}.approve_description`}
              value="1"
            />{" "}
            opis sprawdzony, zgodny z rysunkiem
          </label>
        </div>
        <textarea
          name={`asset.${asset.id}.description`}
          rows={3}
          defaultValue={asset.description ?? ""}
          placeholder="opis pozwalający rozwiązać zadanie bez oglądania rysunku — propozycję modelu dorzuca `task describe`"
        />
        <p className="small" style={{ margin: ".2rem 0 0" }}>
          To osobna decyzja od rozstrzygnięcia zadania (pomiar S7). Opis może zostać do
          sprawdzenia później; zadanie zatwierdzasz niezależnie.
        </p>
      </div>
    </div>
  );
}

function Decide({
  task,
  editedBefore,
  busy,
}: {
  task: Task;
  editedBefore: boolean;
  busy: boolean;
}) {
  return (
    <div className="card decide">
      <h2>Rozstrzygnięcie</h2>
      <div className="row">
        <button name="action" value="approve" className="primary" disabled={busy}>
          Zatwierdź i przejdź dalej →
        </button>
        <button name="action" value="save" disabled={busy}>
          Zapisz, zostań
        </button>
        <button name="action" value="reject" className="danger" disabled={busy}>
          Odrzuć
        </button>
        {task.review_status !== "pending" && (
          <button name="action" value="reopen" disabled={busy}>
            Cofnij do korekty
          </button>
        )}
      </div>
      <p className="small">
        {editedBefore ? (
          <>
            W tej rundzie były już poprawki, więc „Zatwierdź" zapisze zadanie jako{" "}
            <span className="tag corrected">poprawione</span>.
          </>
        ) : (
          <>
            Status wychodzi z porównania z bazą, nie z deklaracji: pola bez zmian →{" "}
            <span className="tag approved">zatwierdzone</span> (parser trafił sam), pola
            zmienione → <span className="tag corrected">poprawione</span>.
          </>
        )}{" "}
        „Odrzuć" wyrzuca rekord poza korpus jako dziurę do zaraportowania. „Zapisz, zostań"
        nie rozstrzyga i nie zatrzymuje zegara S8.
      </p>
    </div>
  );
}
