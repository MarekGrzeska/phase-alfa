import {
  count,
  kindLabel,
  mathJsonLabel,
  versionsInOrder,
  type TaskDetail,
} from "./format";

/**
 * Podgląd zatwierdzonego zadania. Komponent DOSTAJE dane, nie pobiera ich —
 * dzięki temu da się go wyrenderować w teście bez sieci, a to on niesie
 * kontrakt zadanie/kryterium ustalany tygodnie przed pipeline'em A3.
 */
export function TaskDetailView({ task }: { readonly task: TaskDetail }) {
  const versions = versionsInOrder(task);

  return (
    <article className="task">
      <h2>
        Zadanie {task.number} <small>({count(task.maxPoints)} pkt · {kindLabel(task.kind)})</small>
      </h2>

      {/* Obie wersje obok siebie — do tego był podział task/task_version. */}
      <div className="versions">
        {versions.map((version) => (
          <section key={String(version.id)}>
            <h3>
              {version.code}-{version.variant}
              {version.version === null ? "" : ` · wersja ${version.version}`}
            </h3>
            <p className="content">{version.content ?? "Treść nie została wczytana z arkusza."}</p>

            {version.assets.map((asset) => (
              <figure key={String(asset.id)}>
                <img src={`/api/corpus/assets/${count(asset.id)}`} alt={asset.description ?? ""} />
                <figcaption>
                  {asset.description ?? "Bez opisu — alt-text czeka na zatwierdzenie."}
                </figcaption>
              </figure>
            ))}

            {version.answers.length > 0 && (
              <ul className="answers">
                {version.answers.map((answer) => (
                  <li key={String(answer.id)}>
                    {answer.part === null ? "" : `${answer.part}: `}
                    <strong>{answer.answer}</strong>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>

      <h3>Kryteria</h3>
      {task.criteria.length === 0 ? (
        <p className="muted">
          Bez kryteriów — dla zadań zamkniętych rocznika 2019 to norma dokumentu.
        </p>
      ) : (
        <ol className="criteria">
          {task.criteria.map((criterion) => (
            <li key={String(criterion.id)}>
              <strong>{count(criterion.points)} pkt</strong>{" "}
              {criterion.label ?? criterion.description ?? ""}
              {/* Trzy poziomy dysjunkcji, niespłaszczone: próg → warunek → zapis. */}
              <ul>
                {criterion.conditions.map((condition) => (
                  <li key={String(condition.id)}>
                    {condition.description}
                    {condition.expressions.length > 0 && (
                      <ul className="expressions">
                        {condition.expressions.map((expression) => (
                          <li key={String(expression.id)}>
                            <code>{expression.expression}</code>{" "}
                            <span className="muted">{mathJsonLabel(expression.mathJsonStatus)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}

      <h3>Wymagania podstawy programowej</h3>
      <ul>
        {task.requirements.map((requirement) => (
          <li key={String(requirement.id)}>
            <code>
              {requirement.regime} {requirement.stage ?? ""} {requirement.path}
            </code>{" "}
            {requirement.content}
          </li>
        ))}
      </ul>

      {task.rules.length > 0 && (
        <>
          <h3>Reguły arkusza w zakresie tego zadania</h3>
          <ul className="muted">
            {task.rules.map((rule) => (
              <li key={String(rule.id)}>{rule.content}</li>
            ))}
          </ul>
        </>
      )}
    </article>
  );
}
