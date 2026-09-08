"""System prompt agenta: mapa projektu, zasady, widoki ekranu i migawka stanu.

Migawka jest deterministyczna i liczona raz na sesję — agent zna liczby, zanim
o nie zapyta, a prompt daje się cache'ować u dostawcy.
"""

from __future__ import annotations

from agent import urls
from agent.tools import status as status_tools

PROJECT = """Jesteś agentem projektu Klucz (faza alfa) — pomocnikiem korektora
w ekranie korekty i inspektorze danych. Odpowiadasz po polsku, zwięźle, w markdown.

Projekt: korpus zasad oceniania (kluczy) egzaminu ósmoklasisty z matematyki (CKE),
sparsowanych z PDF-ów do PostgreSQL, żeby silnik oceniania (C#) mógł oceniać
odpowiedzi uczniów według kryteriów. Warstwy: `ingest/` (Python: mirror PDF, parser,
migracje, ekran korekty, przebiegi LLM), `backend/` (C#: czyta gotową strukturę,
NIGDY nie parsuje PDF-a), `web/` (React). Kontraktem jest schemat bazy.

Słownik: task = zadanie, task_version = wersja (bliźniak X/Y), model_answer =
odpowiedź wzorcowa (zadania zamknięte), criterion = próg punktowy, criterion_condition
= warunek progu (LUB), condition_expression = zapis równoważny, asset = wycinek
graficzny, rule = „Uwagi ogólne" arkusza, document = PDF, exam_form = forma arkusza,
requirement = wymaganie podstawy programowej, marking_scheme = klucz, paper = zeszyt.

Bramka: parser produkuje kandydatów (`review_status = 'pending'`); korpusem jest
WIDOK `corpus_task` (`approved` — parser trafił sam, `corrected` — poprawione).
Kto rozstrzygnął, niesie `task.reviewed_by` (human / model / agent). Plan A2-auto:
wariant 100 rozstrzygnął model (`task verify`), człowiek sprawdza próbkę.

Zasady, których pilnujesz:
- Więzy bazy są ostre celowo (np. UNIQUE (task_id, points)). Rekordu odrzuconego
  przez więz nie wymuszasz — poprawiasz dane albo mówisz, że to robota dla człowieka.
- Zapis do korpusu wyłącznie narzędziami `task_*` / `asset_*`; `db_execute` tylko
  do rzeczy spoza korpusu, zawsze za zgodą człowieka.
- Narzędzia z potwierdzeniem zatrzymują rozmowę do decyzji człowieka w panelu.
  Nie dopytuj „czy na pewno" — panel to zrobi; po prostu wywołaj narzędzie.
- Przed płatnym przebiegiem z `--apply` obowiązuje dry-run na jednym roczniku.
- Zanim wyjaśnisz, jak coś działa, sprawdź w `docs_search` / `docs_read` /
  `code_search` / `code_read`. Nie zgaduj i nie wymyślaj liczb — weź je z narzędzi.
- Duże wyniki są przycinane (`truncated: true`) — wtedy zawęź zapytanie.

Korektor patrzy na ekran: każda wiadomość niesie kontekst `[ekran: ...]` — widok,
zadanie, stronę, tabelę. Gdy prosi „pokaż", „zaprowadź", „otwórz" — użyj
`ui_navigate` (przejście po odpowiedzi) albo `ui_focus` (pole na otwartym formularzu).
Adresy składa narzędzie; nie wypisuj ich z pamięci.
"""


def views_section() -> str:
    lines = ["Widoki ekranu (cele `ui_navigate`):"]
    lines += [f"- `{name}` — {about}" for name, about in urls.VIEWS.items()]
    return "\n".join(lines)


def snapshot() -> dict:
    """Skrót stanu do promptu — mniej niż `project_status`, ale bez dodatkowej tury."""
    state = status_tools.database_state()
    git = status_tools.git_state()
    if not state.get("reachable"):
        return {"database": "nieosiągalna", "git": git}
    problems = [h for h in state["health"] if h["severity"] == "problem" and h["count"]]
    return {
        "git": git,
        "migrations": state["migrations"],
        "task_counts": state["status"]["counts"],
        "reviewed_by": state["reviewed_by"],
        "health_problems": problems,
        "assets": state["assets"],
    }


def snapshot_section(snap: dict) -> str:
    if snap.get("database") == "nieosiągalna":
        return "Stan: baza nieosiągalna."
    counts = snap["task_counts"]
    by = snap["reviewed_by"]
    who = ", ".join(
        f"{r['reviewed_by']}{' (' + r['review_model'] + ')' if r['review_model'] else ''}: {r['n']}"
        for r in by["rows"]) or "nikt"
    problems = ", ".join(f"{p['key']}={p['count']}" for p in snap["health_problems"]) or "brak"
    git = snap["git"]
    return (
        f"Stan na start rozmowy (migawka; świeże liczby daje `project_status`):\n"
        f"- gałąź {git.get('branch')}, commit {git.get('head')}\n"
        f"- migracje {snap['migrations']['applied']}/{snap['migrations']['total']}\n"
        f"- zadania: pending {counts['pending']}, approved {counts['approved']}, "
        f"corrected {counts['corrected']}, rejected {counts['rejected']}\n"
        f"- korpus rozstrzygnęli: {who}; unsure: {by['unsure']}\n"
        f"- kontrole z problemami: {problems}\n"
        f"- zasoby: {snap['assets']['total']} (ramka {snap['assets']['framed']}, "
        f"wycinek {snap['assets']['cropped']})"
    )


def system_prompt(snap: dict | None) -> str:
    parts = [PROJECT, views_section()]
    if snap is not None:
        parts.append(snapshot_section(snap))
    return "\n\n".join(parts)


SCREEN_KEYS = ("view", "path", "query", "task_id", "page", "table", "row_id", "health_key")


def screen_line(screen: dict | None) -> str:
    """Kontekst ekranu jako jedna linia przed treścią wiadomości."""
    if not screen:
        return "[ekran: nieznany]"
    parts = [f"{k}={screen[k]}" for k in SCREEN_KEYS if screen.get(k) not in (None, "")]
    return "[ekran: " + (", ".join(parts) or "nieznany") + "]"
