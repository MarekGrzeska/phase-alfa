import { useEffect, useState } from "react";

import { corpus, failed, LOADING, type Loaded } from "./api";
import { count, formName, kindLabel, type FormSummary, type TaskDetail, type TaskSummary } from "./format";
import { TaskDetailView } from "./TaskDetailView";

/**
 * Przeglądarka korpusu (W2.2) — narzędzie badawcze, nie ekran produktu.
 * Czyta WYŁĄCZNIE zatwierdzone rekordy, przez C# i OpenAPI: granica warstw
 * bez zmian, a każdy dosypany rocznik jest natychmiast widoczny.
 *
 * Stan siedzi w adresie (`?form=…&task=…`) i to wystarcza za routing —
 * reguła stopu z Planu Implementacji: najprostsze, co odpowiada na pytanie.
 */
export function CorpusBrowser({
  formId,
  taskId,
  onSelect,
}: {
  readonly formId: number | null;
  readonly taskId: number | null;
  readonly onSelect: (next: { form?: number | null; task?: number | null }) => void;
}) {
  const forms = useForms();
  const tasks = useTasks(formId);
  const task = useTask(taskId);

  return (
    <div className="browser">
      <nav className="panel">
        <h2>Arkusze</h2>
        {forms.state === "loading" && <p className="muted">Wczytuję…</p>}
        {forms.state === "error" && <p className="error">{forms.message}</p>}
        {forms.state === "ready" && forms.data.length === 0 && (
          <p className="muted">
            Korpus jest pusty. Przeglądarka pokazuje wyłącznie rekordy zatwierdzone
            w ekranie korekty (<code>task correction</code>) — sparsowane, ale
            nierozstrzygnięte, korpusem jeszcze nie są.
          </p>
        )}
        {forms.state === "ready" && (
          <ul className="list">
            {forms.data.map((form) => (
              <li key={String(form.id)}>
                <button
                  type="button"
                  aria-current={formId === count(form.id)}
                  onClick={() => onSelect({ form: count(form.id), task: null })}
                >
                  {formName(form)}
                  <span className="muted"> · {count(form.tasks)} zad.</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {formId !== null && <TaskList tasks={tasks} selected={taskId} onSelect={onSelect} />}
      </nav>

      <div className="panel wide">
        {taskId === null && <p className="muted">Wybierz zadanie z listy.</p>}
        {taskId !== null && task.state === "loading" && <p className="muted">Wczytuję…</p>}
        {taskId !== null && task.state === "error" && <p className="error">{task.message}</p>}
        {task.state === "ready" && <TaskDetailView task={task.data} />}
      </div>
    </div>
  );
}

function TaskList({
  tasks,
  selected,
  onSelect,
}: {
  readonly tasks: Loaded<TaskSummary[]>;
  readonly selected: number | null;
  readonly onSelect: (next: { task: number }) => void;
}) {
  return (
    <>
      <h2>Zadania</h2>
      {tasks.state === "loading" && <p className="muted">Wczytuję…</p>}
      {tasks.state === "error" && <p className="error">{tasks.message}</p>}
      {tasks.state === "ready" && (
        <ul className="list">
          {tasks.data.map((task) => (
            <li key={String(task.id)}>
              <button
                type="button"
                aria-current={selected === count(task.id)}
                onClick={() => onSelect({ task: count(task.id) })}
              >
                {task.number}
                <span className="muted">
                  {" "}
                  · {count(task.maxPoints)} pkt · {kindLabel(task.kind)}
                  {task.hasAsset ? " · rysunek" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function useForms(): Loaded<FormSummary[]> {
  const [state, setState] = useState<Loaded<FormSummary[]>>(LOADING);

  useEffect(() => {
    let alive = true;
    corpus
      .GET("/corpus/forms")
      .then(({ data, error }) => {
        if (!alive) {
          return;
        }
        setState(
          error === undefined && data !== undefined
            ? { state: "ready", data }
            : failed("nie udało się wczytać arkuszy", error),
        );
      })
      .catch((error: unknown) => alive && setState(failed("API nie odpowiada", error)));
    return () => {
      alive = false;
    };
  }, []);

  return state;
}

function useTasks(formId: number | null): Loaded<TaskSummary[]> {
  const [state, setState] = useState<Loaded<TaskSummary[]>>(LOADING);

  useEffect(() => {
    if (formId === null) {
      return;
    }
    let alive = true;
    setState(LOADING);
    corpus
      .GET("/corpus/forms/{id}/tasks", { params: { path: { id: formId } } })
      .then(({ data, error }) => {
        if (!alive) {
          return;
        }
        setState(
          error === undefined && data !== undefined
            ? { state: "ready", data }
            : failed("nie udało się wczytać zadań", error),
        );
      })
      .catch((error: unknown) => alive && setState(failed("API nie odpowiada", error)));
    return () => {
      alive = false;
    };
  }, [formId]);

  return state;
}

function useTask(taskId: number | null): Loaded<TaskDetail> {
  const [state, setState] = useState<Loaded<TaskDetail>>(LOADING);

  useEffect(() => {
    if (taskId === null) {
      return;
    }
    let alive = true;
    setState(LOADING);
    corpus
      .GET("/corpus/tasks/{id}", { params: { path: { id: taskId } } })
      .then(({ data, error }) => {
        if (!alive) {
          return;
        }
        setState(
          error === undefined && data !== undefined
            ? { state: "ready", data }
            : failed("nie udało się wczytać zadania", error),
        );
      })
      .catch((error: unknown) => alive && setState(failed("API nie odpowiada", error)));
    return () => {
      alive = false;
    };
  }, [taskId]);

  return state;
}
