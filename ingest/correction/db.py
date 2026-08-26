"""Dostęp do bazy dla ekranu korekty — jedyne miejsce z SQL-em tej warstwy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from correction import assets
from schema.migrate import polaczenie

STATUSES = ("pending", "approved", "corrected", "rejected")

STATUS_LABELS = {
    "pending": "do zatwierdzenia",
    "approved": "zatwierdzone",
    "corrected": "poprawione",
    "rejected": "odrzucone",
}

TASK_KINDS = ("closed", "open_short", "open_extended", "essay")

INT_COLUMNS = frozenset({"max_points", "points"})

# Kolumny NOT NULL — liczone PER TABELA, nie per nazwa kolumny. `description`
# jest wymagane w `criterion_condition`, ale NULL-owalne w `criterion`, gdzie
# parser zostawia je puste przy każdym progu z wypunktowanymi warunkami. Zbiór
# po samych nazwach kolumn traktował oba tak samo i zamykał drogę do
# zatwierdzenia większości zadań otwartych.
REQUIRED = {
    "task": frozenset({"number", "max_points", "kind"}),
    "model_answer": frozenset({"answer"}),
    "criterion_condition": frozenset({"description"}),
    "condition_expression": frozenset({"expression"}),
}

# Przynależność wiersza do zadania — pisana raz i wstrzykiwana do każdego
# UPDATE/DELETE. Bez tego podmieniony identyfikator w formularzu sięgałby
# do cudzego zadania; narzędzie stoi na localhoście, ale „nikt tego nie
# podmieni" nie jest więzem.
OWNERSHIP = {
    "task_version": "task_id = %(task)s",
    "model_answer":
        "task_version_id IN (SELECT id FROM task_version WHERE task_id = %(task)s)",
    "criterion": "task_id = %(task)s",
    "criterion_condition":
        "criterion_id IN (SELECT id FROM criterion WHERE task_id = %(task)s)",
    "condition_expression":
        "condition_id IN (SELECT id FROM criterion_condition WHERE criterion_id IN"
        " (SELECT id FROM criterion WHERE task_id = %(task)s))",
}

# Usuwać wolno mniej, niż wolno edytować. Wersji zadania nie ma na tej liście
# świadomie: kasowanie jej pociąga kaskadą odpowiedzi wzorcowe i wycinki graficzne
# (`asset` wisi na `task_version`), a sama powstaje w ingeście i tam się ją poprawia.
# Dopóki obie listy były tym samym słownikiem, ręcznie doklejone pole
# `delete.version.N` działało, choć żaden szablon go nie tworzy.
DELETABLE = ("answer", "criterion", "condition", "expression")

# Prefiks pola w formularzu → (tabela, kolumny). `criterion.12.points`
# adresuje kolumnę `points` wiersza 12 tabeli `criterion`.
EDITABLE = {
    "version": ("task_version", ("content",)),
    "answer": ("model_answer", ("answer",)),
    "criterion": ("criterion", ("points", "label", "description")),
    "condition": ("criterion_condition", ("description",)),
    "expression": ("condition_expression", ("expression",)),
}


class ValidationError(Exception):
    """Formularz nie nadaje się do zapisu — z listą powodów po polsku."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages))


def connect() -> psycopg.Connection:
    """Połączenie na jedno żądanie.

    Bez puli: ekran obsługuje jedną osobę na localhoście, a pula to trzecia
    zależność i własny tryb awarii (połączenie przeterminowane w tle) za
    oszczędność milisekund, których nikt tu nie zauważy.
    """
    return psycopg.connect(polaczenie(), row_factory=dict_row)


# --------------------------------------------------------------------- listy

def counts_by_status(cur) -> dict[str, int]:
    cur.execute("SELECT review_status, count(*) AS n FROM task GROUP BY review_status")
    found = {r["review_status"]: r["n"] for r in cur.fetchall()}
    return {s: found.get(s, 0) for s in STATUSES}


def filters(cur) -> dict[str, list]:
    """Wartości do rozwijanych list — wyłącznie te, które są w korpusie."""
    cur.execute("SELECT DISTINCT year FROM document WHERE kind = 'marking_scheme'"
                " ORDER BY year")
    years = [r["year"] for r in cur.fetchall()]
    cur.execute("SELECT DISTINCT code FROM document WHERE kind = 'marking_scheme'"
                " ORDER BY code")
    codes = [r["code"] for r in cur.fetchall()]
    # `unnest`, bo klucz bywa wspólny dla kilku wariantów i trzyma je w jednej
    # kolumnie po przecinku — lista wyboru ma pokazywać warianty, nie ich zlepki.
    cur.execute("SELECT DISTINCT unnest(string_to_array(variants, ',')) AS variant"
                " FROM document WHERE kind = 'marking_scheme' AND variants IS NOT NULL"
                " ORDER BY variant")
    return {"years": years, "codes": codes,
            "variants": [r["variant"] for r in cur.fetchall()]}


# Zakres pracy: pilot G2.2 to JEDEN rocznik i JEDEN wariant z ośmiu roczników
# w bazie. Ten sam warunek obowiązuje listę i „następne do korekty" — inaczej
# przycisk wyprowadza z pilotu do pierwszego czekającego zadania z 2019 r.
# Rzutowania są konieczne, nie ozdobne: nieotypowany NULL w `IS NULL` każe
# Postgresowi zgadywać typ parametru i kończy się błędem.
SCOPE_SQL = """(%(year)s::smallint  IS NULL OR d.year = %(year)s)
             AND (%(code)s::text    IS NULL OR d.code = %(code)s)
             AND (%(variant)s::text IS NULL
                  OR %(variant)s = ANY(string_to_array(d.variants, ',')))"""


def list_tasks(cur, status: str | None = None, year: int | None = None,
               code: str | None = None, variant: str | None = None,
               limit: int = 200) -> list[dict]:
    cur.execute(
        f"""SELECT t.id, t.number, t.max_points, t.kind, t.review_status,
                   t.reviewed_at, d.code, d.session, d.year, d.variants, d.path
            FROM task t
            JOIN document d ON d.id = t.marking_scheme_id
            WHERE (%(status)s::text IS NULL OR t.review_status = %(status)s)
              AND {SCOPE_SQL}
            ORDER BY d.session, d.path, t.position
            LIMIT %(limit)s""",  # noqa: S608
        {"status": status, "year": year, "code": code, "variant": variant,
         "limit": limit},
    )
    return cur.fetchall()


def next_pending(cur, year: int | None = None, code: str | None = None,
                 variant: str | None = None) -> int | None:
    """Następne zadanie do rozstrzygnięcia w zakresie — domyślne wejście do pracy."""
    cur.execute(
        f"""SELECT t.id FROM task t
            JOIN document d ON d.id = t.marking_scheme_id
            WHERE t.review_status = 'pending'
              AND {SCOPE_SQL}
            ORDER BY d.session, d.path, t.position
            LIMIT 1""",  # noqa: S608
        {"year": year, "code": code, "variant": variant},
    )
    row = cur.fetchone()
    return row["id"] if row else None


# --------------------------------------------------------------- jedno zadanie

def _task_ordinal(number: str | None) -> int | None:
    """Numer główny zadania: `16` → 16, `4.1` → 4. Zakresy reguł idą po nim."""
    if number is None:
        return None
    head = str(number).split(".")[0].strip()
    return int(head) if head.isdigit() else None


def rule_applies(rule: Mapping[str, Any], number: str) -> bool:
    """Czy reguła arkusza obowiązuje to zadanie.

    Porównanie musi być LICZBOWE. Zakres „16–21" obejmuje też 18, a dopasowanie
    po krańcach widziało wyłącznie 16 i 21 — czyli reguła „sam poprawny wynik
    to 0 punktów" znikała z ekranu przy większości zadań, których dotyczy.
    Numer bez sensownej części liczbowej pokazuje regułę, zamiast ją chować:
    kontekst za dużo jest tańszy niż kryterium ocenione bez reguły.
    """
    start = _task_ordinal(rule.get("tasks_from"))
    end = _task_ordinal(rule.get("tasks_to"))
    if start is None and end is None:
        return True
    here = _task_ordinal(number)
    if here is None:
        return False
    if start is not None and here < start:
        return False
    return not (end is not None and here > end)


def load_task(cur, task_id: int) -> dict | None:
    """Zadanie z kompletem tego, co ekran pokazuje i co wolno edytować."""
    cur.execute(
        """SELECT t.id, t.number, t.position, t.max_points, t.kind, t.page,
                  t.review_status, t.reviewed_at,
                  d.id AS document_id, d.path AS document_path, d.code,
                  d.session, d.year, d.pages AS document_pages
           FROM task t
           JOIN document d ON d.id = t.marking_scheme_id
           WHERE t.id = %s""",
        (task_id,),
    )
    task = cur.fetchone()
    if task is None:
        return None

    cur.execute(
        """SELECT tv.id, tv.content, tv.content_status, tv.page, tv.paper_id,
                  f.code, f.variant, f.version
           FROM task_version tv
           JOIN exam_form f ON f.id = tv.exam_form_id
           WHERE tv.task_id = %s
           ORDER BY f.variant, f.version NULLS FIRST""",
        (task_id,),
    )
    versions = cur.fetchall()

    cur.execute(
        """SELECT m.id, m.task_version_id, m.part, m.answer
           FROM model_answer m
           JOIN task_version tv ON tv.id = m.task_version_id
           WHERE tv.task_id = %s
           ORDER BY m.part NULLS FIRST, m.id""",
        (task_id,),
    )
    answers = cur.fetchall()
    for version in versions:
        version["answers"] = [a for a in answers
                              if a["task_version_id"] == version["id"]]

    cur.execute(
        """SELECT id, points, label, description, position FROM criterion
           WHERE task_id = %s ORDER BY points DESC, position""",
        (task_id,),
    )
    criteria = cur.fetchall()

    cur.execute(
        """SELECT cc.id, cc.criterion_id, cc.description, cc.position
           FROM criterion_condition cc
           JOIN criterion c ON c.id = cc.criterion_id
           WHERE c.task_id = %s ORDER BY cc.position, cc.id""",
        (task_id,),
    )
    conditions = cur.fetchall()

    cur.execute(
        """SELECT ce.id, ce.condition_id, ce.expression, ce.mathjson, ce.position
           FROM condition_expression ce
           JOIN criterion_condition cc ON cc.id = ce.condition_id
           JOIN criterion c ON c.id = cc.criterion_id
           WHERE c.task_id = %s ORDER BY ce.position, ce.id""",
        (task_id,),
    )
    expressions = cur.fetchall()

    for condition in conditions:
        condition["expressions"] = [e for e in expressions
                                    if e["condition_id"] == condition["id"]]
    for criterion in criteria:
        criterion["conditions"] = [c for c in conditions
                                   if c["criterion_id"] == criterion["id"]]
    task["criteria"] = criteria

    # Czy zadanie zamknięte BEZ kryteriów jest w tym kluczu normą, czy dziurą.
    # Rocznik 2019 podaje dla zadań zamkniętych samą odpowiedź wzorcową i sekcji
    # kryteriów nie ma tam wcale — korektor ma to zobaczyć jako kształt dokumentu,
    # a nie szukać po kluczu czegoś, czego w nim nie ma. Mierzone z dokumentu,
    # nie po roczniku: warianty 800 i Q00 z 2019 r. te sekcje mają.
    cur.execute(
        """SELECT EXISTS (SELECT 1 FROM task t
                            JOIN criterion c ON c.task_id = t.id
                           WHERE t.marking_scheme_id = %s AND t.kind = 'closed')
             AS found""",
        (task["document_id"],),
    )
    task["closed_have_criteria"] = cur.fetchone()["found"]

    cur.execute(
        """SELECT r.id, r.kind, r.stage, r.path, r.content, rr.code AS regime
           FROM task_requirement tr
           JOIN requirement r ON r.id = tr.requirement_id
           JOIN requirement_regime rr ON rr.id = r.regime_id
           WHERE tr.task_id = %s
           ORDER BY r.kind, r.stage NULLS FIRST, r.path""",
        (task_id,),
    )
    task["requirements"] = cur.fetchall()

    cur.execute(
        """SELECT id, points, method, content, position FROM example_solution
           WHERE task_id = %s ORDER BY position, id""",
        (task_id,),
    )
    task["solutions"] = cur.fetchall()

    # Reguły przekrojowe obejmujące to zadanie — kontekst, nie przedmiot edycji:
    # wiszą na arkuszu, więc poprawia się je razem z arkuszem.
    cur.execute(
        """SELECT id, kind, content, tasks_from, tasks_to FROM rule
           WHERE marking_scheme_id = %s ORDER BY position""",
        (task["document_id"],),
    )
    task["rules"] = [r for r in cur.fetchall() if rule_applies(r, task["number"])]
    task["versions"] = versions
    task["assets"] = assets.for_task(cur, task_id)
    task["hints"] = prefill_hints(cur, task_id, criteria)
    return task


def prefill_hints(cur, task_id: int, criteria: list[dict]) -> list[dict]:
    """Różnice parser vs LLM jako podpowiedzi przy polach (G2.5.1).

    Import w środku funkcji, bo `prefill` ciągnie SDK Anthropic, a ekran korekty
    ma wstawać także na maszynie bez niego — podpowiedzi są dodatkiem, nie
    warunkiem pracy.
    """
    cur.execute(
        "SELECT model, payload FROM prefill_suggestion WHERE task_id = %s"
        " ORDER BY created_at DESC LIMIT 1",
        (task_id,),
    )
    row = cur.fetchone()
    if row is None:
        return []
    try:
        from correction import prefill
        suggestion = prefill.parse_payload(row["payload"])
    except Exception:
        # Podpowiedź w kształcie, którego już nie rozumiemy, nie ma prawa
        # zablokować korekty — ekran działa bez niej od zawsze.
        return []
    hints = prefill.differences(criteria, suggestion)
    for hint in hints:
        hint["model"] = row["model"]
    return hints


def neighbours(cur, task: Mapping[str, Any]) -> dict[str, int | None]:
    """Poprzednie i następne zadanie w tym samym kluczu — nawigacja bez powrotu na listę."""
    cur.execute(
        """SELECT
             (SELECT id FROM task WHERE marking_scheme_id = %(doc)s
                AND position < %(pos)s ORDER BY position DESC LIMIT 1) AS previous,
             (SELECT id FROM task WHERE marking_scheme_id = %(doc)s
                AND position > %(pos)s ORDER BY position LIMIT 1) AS next""",
        {"doc": task["document_id"], "pos": task["position"]},
    )
    return cur.fetchone()


def page_source(cur, task_id: int) -> dict | None:
    """Dokument i strona do podglądu — osobne, małe zapytanie dla obrazka."""
    cur.execute(
        """SELECT d.path, d.pages, t.page FROM task t
           JOIN document d ON d.id = t.marking_scheme_id
           WHERE t.id = %s""",
        (task_id,),
    )
    return cur.fetchone()


def available_requirements(cur, task_id: int) -> list[dict]:
    """Wymagania z reżimów, w których stoją formy tego zadania."""
    cur.execute(
        """SELECT r.id, r.kind, r.stage, r.path, r.content, rr.code AS regime
           FROM requirement r
           JOIN requirement_regime rr ON rr.id = r.regime_id
           WHERE r.regime_id IN (SELECT f.regime_id
                                 FROM task_version tv
                                 JOIN exam_form f ON f.id = tv.exam_form_id
                                 WHERE tv.task_id = %s)
           ORDER BY r.kind, r.stage NULLS FIRST, r.path""",
        (task_id,),
    )
    return cur.fetchall()


# ------------------------------------------------------------------- zapis

def _clean(column: str, raw: str) -> Any:
    """Wartość z formularza → wartość dla kolumny. Rzuca `ValueError` na bzdurze."""
    value = raw.strip()
    if column in INT_COLUMNS:
        return int(value)
    if not value:
        # Kolumny NOT NULL zatrzyma walidacja wyżej; reszta woli NULL niż `''`,
        # bo puste pole znaczy „nie ma", a nie „jest, ale puste".
        return None
    return value


def _deleted_ids(form: Mapping[str, str], prefix: str) -> set[int]:
    """`delete.criterion.12` z zaznaczonego checkboksa."""
    out = set()
    for key in form:
        parts = key.split(".")
        if len(parts) == 3 and parts[0] == "delete" and parts[1] == prefix \
                and parts[2].isdigit():
            out.add(int(parts[2]))
    return out


def _submitted_rows(form: Mapping[str, str], prefix: str,
                    columns: tuple[str, ...]) -> dict[int, dict[str, str]]:
    """Wiersze obecne w formularzu, w postaci {id: {kolumna: tekst}}."""
    rows: dict[int, dict[str, str]] = {}
    for key, raw in form.items():
        parts = key.split(".")
        if len(parts) != 3 or parts[0] != prefix or not parts[1].isdigit():
            continue
        if parts[2] not in columns:
            continue
        rows.setdefault(int(parts[1]), {})[parts[2]] = raw
    return rows


def save(cur, task_id: int, form: Mapping[str, str]) -> dict[str, dict[str, int]]:
    """Edycje z formularza → baza. Zwraca, co się naprawdę zmieniło.

    Zwracany słownik jest jednocześnie treścią `correction_event.fields_changed`
    i odpowiedzią na pytanie „czy parser trafił sam": pusty znaczy `approved`,
    niepusty — `corrected`. Rozstrzyga porównanie z bazą, nie deklaracja
    człowieka, więc statusu nie da się przypadkiem przekłamać.

    WOŁAĆ W TRANSAKCJI. `ValidationError` leci PO wykonaniu części zapisów
    (kasowanie idzie pierwsze), więc bez wycofania zostawiłoby zadanie
    w stanie w połowie zapisanym.
    """
    edited: dict[str, int] = {}
    deleted: dict[str, int] = {}
    problems: list[str] = []

    skips = _rows_to_vanish(cur, task_id, form)
    _delete_rows(cur, task_id, form, deleted)
    _save_task_row(cur, task_id, form, edited, problems)
    for prefix, (table, columns) in EDITABLE.items():
        _save_rows(cur, task_id, form, prefix, table, columns, skips[prefix],
                   edited, problems)
    _save_requirements(cur, task_id, form, edited, deleted)

    # Cięcie PNG dotyka DYSKU, a dysk nie cofa się razem z transakcją: plik
    # wycięty przed nieudaną walidacją zostałby na miejscu, pokazując ramkę,
    # której w bazie nie ma. Dlatego najpierw wywracamy zapis na tekście,
    # a dopiero potem ruszamy zasoby.
    if problems:
        raise ValidationError(problems)

    assets.save(cur, task_id, form, edited, problems)
    if problems:
        raise ValidationError(problems)
    return {"edited": edited, "deleted": deleted}


def _rows_to_vanish(cur, task_id: int, form: Mapping[str, str]) -> dict[str, set[int]]:
    """Wiersze, których po tym zapisie nie będzie — zaznaczone i te z kaskady.

    Kasowanie progu zabiera jego warunki, a warunku — jego zapisy. Formularz
    nadal je przysyła, bo przeglądarka wysyła całą stronę: bez tej listy
    walidacja szukałaby ich w bazie, nie znajdowała i zgłaszała jako cudze,
    czyli usunięcie progu nie mogłoby się nigdy udać.
    """
    skips = {prefix: (_deleted_ids(form, prefix) if prefix in DELETABLE else set())
             for prefix in EDITABLE}
    if skips["version"]:
        cur.execute("SELECT id FROM model_answer WHERE task_version_id = ANY(%s)",
                    (list(skips["version"]),))
        skips["answer"] |= {r["id"] for r in cur.fetchall()}
    if skips["criterion"]:
        cur.execute("SELECT id FROM criterion_condition WHERE criterion_id = ANY(%s)",
                    (list(skips["criterion"]),))
        skips["condition"] |= {r["id"] for r in cur.fetchall()}
    if skips["condition"]:
        cur.execute("SELECT id FROM condition_expression WHERE condition_id = ANY(%s)",
                    (list(skips["condition"]),))
        skips["expression"] |= {r["id"] for r in cur.fetchall()}
    return skips


def _delete_rows(cur, task_id: int, form: Mapping[str, str],
                 deleted: dict[str, int]) -> None:
    # Kasowanie idzie PRZED walidacją reszty: pole wymagane, puste w wierszu
    # skazanym na usunięcie, nie ma prawa blokować zapisu.
    for prefix in DELETABLE:
        table = EDITABLE[prefix][0]
        ids = _deleted_ids(form, prefix)
        if not ids:
            continue
        cur.execute(
            f"DELETE FROM {table} WHERE id = ANY(%(ids)s) AND {OWNERSHIP[table]}",  # noqa: S608
            {"ids": list(ids), "task": task_id},
        )
        if cur.rowcount:
            deleted[table] = deleted.get(table, 0) + cur.rowcount


def _save_task_row(cur, task_id: int, form: Mapping[str, str],
                   edited: dict[str, int], problems: list[str]) -> None:
    columns = ("number", "max_points", "kind")
    if not any(f"task.{c}" in form for c in columns):
        return
    cur.execute("SELECT number, max_points, kind FROM task WHERE id = %s", (task_id,))
    current = cur.fetchone()
    values = {}
    for column in columns:
        raw = form.get(f"task.{column}")
        if raw is None:
            values[column] = current[column]
            continue
        if not raw.strip():
            problems.append(f"Zadanie, pole {column}: nie może być puste.")
            return
        try:
            values[column] = _clean(column, raw)
        except ValueError:
            problems.append(f"Zadanie, pole {column}: [{raw}] to nie jest liczba.")
            return
    if values["kind"] not in TASK_KINDS:
        problems.append(f"Zadanie: nieznany rodzaj [{values['kind']}].")
        return
    if values == {c: current[c] for c in columns}:
        return
    cur.execute(
        "UPDATE task SET number = %s, max_points = %s, kind = %s WHERE id = %s",
        (values["number"], values["max_points"], values["kind"], task_id),
    )
    edited["task"] = edited.get("task", 0) + 1


def _save_rows(cur, task_id: int, form: Mapping[str, str], prefix: str, table: str,
               columns: tuple[str, ...], skip: set[int], edited: dict[str, int],
               problems: list[str]) -> None:
    submitted = _submitted_rows(form, prefix, columns)
    if not submitted:
        return
    wanted = [rid for rid in submitted if rid not in skip]
    if not wanted:
        return
    required = REQUIRED.get(table, frozenset())

    cur.execute(
        f"SELECT id, {', '.join(columns)} FROM {table} "  # noqa: S608
        f"WHERE id = ANY(%(ids)s) AND {OWNERSHIP[table]}",
        {"ids": wanted, "task": task_id},
    )
    current = {r["id"]: r for r in cur.fetchall()}

    for row_id in wanted:
        old = current.get(row_id)
        if old is None:
            # Wiersz spoza tego zadania albo skasowany w międzyczasie —
            # milczące przejście dalej byłoby cichym zignorowaniem edycji.
            problems.append(f"{table} #{row_id}: nie należy do tego zadania.")
            continue
        new = {}
        for column in columns:
            raw = submitted[row_id].get(column)
            if raw is None:
                new[column] = old[column]
                continue
            if column in required and not raw.strip():
                problems.append(f"{table} #{row_id}, pole {column}: nie może być "
                                "puste — usuń wiersz, jeśli jest zbędny.")
                break
            try:
                new[column] = _clean(column, raw)
            except ValueError:
                problems.append(f"{table} #{row_id}: [{raw}] to nie jest liczba.")
                break
        else:
            if new == {c: old[c] for c in columns}:
                continue
            assignments = ", ".join(f"{c} = %({c})s" for c in columns)
            cur.execute(
                f"UPDATE {table} SET {assignments} "  # noqa: S608
                f"WHERE id = %(id)s AND {OWNERSHIP[table]}",
                {**new, "id": row_id, "task": task_id},
            )
            if cur.rowcount:
                edited[table] = edited.get(table, 0) + 1


def _save_requirements(cur, task_id: int, form: Mapping[str, str],
                       edited: dict[str, int], deleted: dict[str, int]) -> None:
    drop = _deleted_ids(form, "requirement")
    if drop:
        cur.execute(
            "DELETE FROM task_requirement WHERE task_id = %s AND requirement_id = ANY(%s)",
            (task_id, list(drop)),
        )
        if cur.rowcount:
            deleted["task_requirement"] = deleted.get("task_requirement", 0) + cur.rowcount
    add = (form.get("add_requirement") or "").strip()
    if add.isdigit():
        cur.execute(
            """INSERT INTO task_requirement (task_id, requirement_id)
               VALUES (%s, %s) ON CONFLICT DO NOTHING""",
            (task_id, int(add)),
        )
        if cur.rowcount:
            edited["task_requirement"] = edited.get("task_requirement", 0) + cur.rowcount


# ------------------------------------------------------------- nowe wiersze

def add_criterion(cur, task_id: int) -> None:
    """Nowy próg punktowy — z pierwszą wolną punktacją, bo UNIQUE (task_id, points)."""
    cur.execute("SELECT max_points FROM task WHERE id = %s", (task_id,))
    row = cur.fetchone()
    if row is None:
        raise ValidationError(["Nie ma takiego zadania."])
    cur.execute("SELECT points FROM criterion WHERE task_id = %s", (task_id,))
    taken = {r["points"] for r in cur.fetchall()}
    free = [p for p in range(row["max_points"], -1, -1) if p not in taken]
    if not free:
        raise ValidationError(
            ["Wszystkie progi od 0 do puli zadania już istnieją — "
             "popraw istniejący albo podnieś pulę punktów."]
        )
    cur.execute(
        """INSERT INTO criterion (task_id, points, position)
           VALUES (%s, %s, (SELECT coalesce(max(position), 0) + 1
                            FROM criterion WHERE task_id = %s))""",
        (task_id, free[0], task_id),
    )


def add_condition(cur, task_id: int, criterion_id: int) -> None:
    cur.execute(
        """INSERT INTO criterion_condition (criterion_id, description, position)
           SELECT c.id, '', coalesce(
                    (SELECT max(cc.position) FROM criterion_condition cc
                      WHERE cc.criterion_id = c.id), 0) + 1
             FROM criterion c WHERE c.id = %s AND c.task_id = %s""",
        (criterion_id, task_id),
    )
    if not cur.rowcount:
        raise ValidationError(["Próg nie należy do tego zadania."])


def add_expression(cur, task_id: int, condition_id: int) -> None:
    cur.execute(
        """INSERT INTO condition_expression (condition_id, expression, position)
           SELECT cc.id, '', coalesce(
                    (SELECT max(ce.position) FROM condition_expression ce
                      WHERE ce.condition_id = cc.id), 0) + 1
             FROM criterion_condition cc
             JOIN criterion c ON c.id = cc.criterion_id
            WHERE cc.id = %s AND c.task_id = %s""",
        (condition_id, task_id),
    )
    if not cur.rowcount:
        raise ValidationError(["Warunek nie należy do tego zadania."])


# ------------------------------------------------------------ rozstrzygnięcie

def refresh_document_status(cur, task_id: int) -> None:
    """`document.ingest_status` idzie za stanem zadań klucza.

    Plan A2 zapowiadał to przy G2.1.2, a kolumna stała na `new` niezależnie od
    tego, ile zadań przeszło przez ekran. Nic jej dziś nie czyta, ale to ona
    odpowiada na pytanie „które klucze są domknięte" — i lepiej, żeby odpowiadała
    prawdę od pierwszego dnia, niż żeby ktoś w G2.3 oparł na niej raport partii.

    `parsed` znaczy „parser przeszedł, korekta trwa", `approved` — komplet
    rozstrzygnięć z czymkolwiek użytecznym w środku, `rejected` — klucz odrzucony
    w całości.
    """
    cur.execute(
        """UPDATE document d SET ingest_status = CASE
               WHEN EXISTS (SELECT 1 FROM task t
                            WHERE t.marking_scheme_id = d.id
                              AND t.review_status = 'pending') THEN 'parsed'
               WHEN EXISTS (SELECT 1 FROM task t
                            WHERE t.marking_scheme_id = d.id
                              AND t.review_status IN ('approved', 'corrected'))
                    THEN 'approved'
               ELSE 'rejected' END
           WHERE d.id = (SELECT marking_scheme_id FROM task WHERE id = %s)""",
        (task_id,),
    )


def was_corrected(cur, task_id: int) -> bool:
    """Czy ten rekord był już kiedyś poprawiany ręcznie — wprost z dziennika."""
    cur.execute(
        """SELECT EXISTS (SELECT 1 FROM correction_event
                          WHERE task_id = %s AND action = 'correct') AS found""",
        (task_id,),
    )
    return cur.fetchone()["found"]


# Decyzja człowieka → status zadania. `approve` rozdwaja się na dwa stany
# w zależności od tego, czy coś poprawił — i to jest cała mechanika S6/S8.
def decide(cur, task_id: int, action: str, started_at, changes: dict,
           edited_before: bool = False) -> str:
    changed_now = bool(changes.get("edited") or changes.get("deleted"))

    if action == "reopen":
        status, event = "pending", "reopen"
    elif action == "reject":
        status, event = "rejected", "reject"
    elif action == "approve":
        # `approved` znaczy „parser trafił sam" i wyłącznie to. Poprawka zapisana
        # wcześniej — przy dokładaniu wiersza albo w rundzie przed cofnięciem
        # do korekty — nie znika z historii rekordu, więc nie ma prawa zniknąć
        # z pomiaru: inaczej S6/S8 rośnie za każdym razem, gdy ktoś dwa razy
        # kliknie, a to na tej liczbie stoi decyzja o zaworze z G2.2.2.
        by_hand = changed_now or edited_before or was_corrected(cur, task_id)
        status = "corrected" if by_hand else "approved"
        event = "correct" if by_hand else "approve"
    else:
        raise ValidationError([f"Nieznane rozstrzygnięcie: [{action}]."])

    cur.execute(
        """UPDATE task SET review_status = %s,
                           reviewed_at = CASE WHEN %s = 'pending' THEN NULL ELSE now() END
           WHERE id = %s""",
        (status, status, task_id),
    )
    cur.execute(
        # LEAST(..., now()): `started_at` powstaje na zegarze HOSTA, `finished_at`
        # na zegarze bazy. Więz CHECK (finished_at >= started_at) jest więc
        # założeniem o dwóch zegarach, nie o kolejności zdarzeń — a zegar maszyny
        # wirtualnej Dockera potrafi zostać w tyle po uśpieniu laptopa. Przycięcie
        # gubi wtedy jeden pomiar czasu, zamiast wywrócić rozstrzygnięcie, którego
        # treść była w porządku.
        """INSERT INTO correction_event (task_id, action, started_at, fields_changed)
           VALUES (%s, %s, LEAST(%s, now()), %s)""",
        (task_id, event, started_at, Jsonb(changes) if changed_now else None),
    )
    refresh_document_status(cur, task_id)
    return status
