"""Menu ingestu: kategoria → akcja → pytania → podgląd komendy → uruchomienie.

Menu NIE powtarza logiki skryptów. Każda pozycja to nazwa zadania z `Taskfile.yml`
plus lista parametrów, z których składa się flagi. Uruchomienie idzie przez
`task <nazwa> -- <flagi>`, więc `.env`, katalog roboczy (`ingest/`) i komunikaty
zostają tam, gdzie były. Skrypt odpalony ręcznie i z menu robi dokładnie to samo.

Katalog akcji (`CATALOG`) jest danymi, nie kodem: test pilnuje, żeby każda nazwa
zadania istniała w Taskfile, a każda flaga w `--help` odpowiedniego modułu.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from sciezki import KORZEN_REPO

# `questionary` i `rich` ładowane leniwie w funkcjach interaktywnych: część
# czysta (katalog, składanie flag) ma dać się testować bez terminala.


# ── katalog akcji ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Param:
    """Jedno pytanie w menu → jedna flaga polecenia.

    `kind`:
      text   — wartość tekstowa, pusta odpowiedź znaczy „bez tej flagi"
      int    — jak text, ale przyjmuje wyłącznie liczbę
      bool   — flaga bez wartości (`--apply`); pytanie tak/nie
      choice — wybór z listy `choices`; pusta pozycja znaczy „bez flagi"
      words  — kilka wartości po spacji, każda jako osobny argument (`--compare A B`)
    """

    flag: str
    prompt: str
    kind: str = "text"
    default: str | bool | None = None
    choices: tuple[str, ...] = ()
    hint: str = ""


@dataclass(frozen=True)
class Action:
    task: str
    title: str
    about: str
    params: tuple[Param, ...] = ()
    # Przebieg z żywym modelem — z budżetu badawczego alfy. Menu pokazuje
    # ostrzeżenie i pyta drugi raz, tak samo jak przy akcjach kasujących.
    paid: bool = False
    destructive: bool = False
    # Serwer albo konsola: stoi, dopóki człowiek nie wyjdzie (Ctrl-C / \q).
    foreground: bool = False


@dataclass(frozen=True)
class Group:
    title: str
    about: str
    actions: tuple[Action, ...] = field(default_factory=tuple)


YEARS = tuple(str(y) for y in range(2019, 2027))
VARIANTS = ("100", "200", "400", "500", "700", "800", "C00", "K00", "Q00")


def _models() -> tuple[str, ...]:
    """Adresy modeli z cennika — jedno źródło prawdy, to samo co `--model`."""
    from correction.llm import PRICING
    return tuple(sorted(PRICING))


P_YEAR = Param("--year", "Rocznik", "choice", choices=YEARS,
               hint="puste = wszystkie roczniki 2019–2026")
P_VARIANT = Param("--variant", "Wariant arkusza", "choice", choices=VARIANTS,
                  hint="100 = bazowy; puste = wszystkie")
P_LIMIT = Param("--limit", "Limit sztuk", "int", hint="puste = domyślny limit modułu")
P_MODEL = Param("--model", "Model LLM", "choice", choices=(),
                hint="`dostawca:nazwa` z cennika llm.PRICING; puste = domyślny gpt-5.6-terra")
P_BATCH = Param("--batch", "Przez Batch API?", "bool", default=False,
                hint="−50% ceny, wynik po godzinach; adapter tylko dla openai")
P_REPORT = Param("--report", "Własna ścieżka raportu", "text",
                 hint="puste = data/reports/<nazwa>-RRRR-MM-DD.txt")


CATALOG: tuple[Group, ...] = (
    Group("Baza i środowisko", "Docker z Postgresem, migracje schematu, konsola SQL.", (
        Action("setup", "Sprawdź narzędzia", "Docker, uv, .env, .NET SDK, Node, pnpm — "
               "czy komplet jest na maszynie."),
        Action("up", "Postaw bazę", "docker compose up + zastosowanie brakujących migracji."),
        Action("migrate:status", "Stan migracji", "Które migracje weszły, których brakuje."),
        Action("migrate", "Zastosuj migracje", "Brakujące pliki SQL, każdy w jednej "
               "transakcji z wpisem do schema_migrations."),
        Action("db:psql", "Konsola SQL", "psql w kontenerze; wyjście: \\q.", foreground=True),
        Action("down", "Zatrzymaj bazę", "docker compose down — dane zostają w wolumenie."),
        Action("db:reset", "Baza od zera", "Kasuje wolumeny: korpus ORAZ dane Azurite. "
               "Pliki PNG w data/blob zostają — potem `crops --prune`.", destructive=True),
    )),
    Group("Mirror CKE", "Zwózka PDF-ów z cke.gov.pl do lokalnego mirrora (MIRROR_ROOT).", (
        Action("mirror", "Zwózka mirrora", "Spis z cke.gov.pl i pobranie brakujących PDF-ów. "
               "Idempotentna: pobrane pliki pomija.", (
                   Param("--filtr", "Podciąg ścieżki", hint="np. matematyka; puste = wszystko"),
                   Param("--rocznik", "Rocznik", "choice", choices=YEARS,
                         hint="puste = wszystkie"),
                   Param("--segment", "Segment", "choice",
                         choices=("e8", "matura-f2023", "matura-f2015"),
                         hint="puste = wszystkie"),
                   Param("--limit", "Najwyżej N plików", "int", hint="do testów; puste = bez"),
                   Param("--jobs", "Równoległe strumienie", "int", hint="puste = 8"),
                   Param("--tylko-spis", "Tylko odśwież spis, nie pobieraj?", "bool",
                         default=False),
                   Param("--dry-run", "Na sucho?", "bool", default=False,
                         hint="raport ze spisu na dysku, nic nie pobiera"),
                   Param("--force", "Pobierz ponownie mimo obecności pliku?", "bool",
                         default=False),
               )),
    )),
    Group("Parser i ładowanie", "PDF → rekordy w Postgresie (status pending), regresja parsera, "
          "wycinki PNG.", (
        Action("ingest", "Parser kluczy → baza", "Klucze OMAP z mirrora do Postgresa. "
               "Raport do data/reports/ingest-DATA.txt. Klucze po korekcie pomija.", (
                   P_YEAR, P_VARIANT,
                   Param("--code", "Kody arkuszy po przecinku", hint="puste = OMAP"),
                   Param("--limit", "Ile kluczy", "int", hint="puste = wszystkie z filtra"),
                   Param("--with-papers", "Doczytać zeszyty zadań?", "bool", default=True,
                         hint="treść zadań i rysunki; ~8× wolniej"),
                   Param("--verbose", "Wiersz na każdy klucz?", "bool", default=False),
                   Param("--wipe", "Opróżnić CAŁY korpus przed ładowaniem?", "bool",
                         default=False, hint="odmówi, gdy w bazie jest korekta lub dziennik"),
                   Param("--overwrite-reviewed", "Przeładować TAKŻE klucze po korekcie?",
                         "bool", default=False, hint="kasuje rozstrzygnięcia razem z zadaniami"),
                   Param("--engine", "Silnik PDF", "choice", choices=("pdfplumber", "pymupdf"),
                         hint="puste = pdfplumber (MIT)"),
                   P_REPORT,
               )),
        Action("parser:snapshot", "Zrzut liczb parsera", "Regresja bez bazy: liczniki i skróty "
               "treści per klucz, porównanie z poprzednim zrzutem.", (
                   P_YEAR, P_VARIANT,
                   Param("--limit", "Ile kluczy", "int", hint="puste = wszystkie"),
                   Param("--out", "Gdzie zapisać zrzut",
                         hint="puste = data/reports/parser-DATA.json"),
                   Param("--baseline", "Zrzut odniesienia",
                         hint="po przebiegu wypisze różnice; puste = bez porównania"),
                   Param("--compare", "Porównaj DWA gotowe zrzuty", "words",
                         hint="`stary.json nowy.json`; wtedy nic nie parsuje"),
               )),
        Action("crops", "Wycinki PNG", "Dotnij brakujące wycinki z zeszytów albo posprzątaj "
               "osierocone pliki w blobie.", (
                   Param("--force", "Przetnij od nowa także te z plikiem?", "bool",
                         default=False),
                   Param("--prune", "Tylko POKAŻ osierocone pliki?", "bool", default=False,
                         hint="nic nie kasuje"),
                   Param("--yes", "…i skasuj to, co wypisał --prune?", "bool", default=False),
               )),
    )),
    Group("Korekta", "Bramka do korpusu: ekran na localhoście i raport pomiarów.", (
        Action("correction", "Ekran korekty", "Serwer na 127.0.0.1:CORRECTION_PORT (8600). "
               "Stoi do Ctrl-C, potem menu wraca.", foreground=True),
        Action("correction:report", "Raport korekty (S6, S7, S8)", "Stan, czasy, prognoza "
               "→ data/reports/correction-DATA.txt.", (P_REPORT,)),
    )),
    Group("LLM — płatne", "Przebiegi z żywym modelem, z budżetu badawczego. Zawsze najpierw "
          "dry-run na jednym roczniku.", (
        Action("verify", "Drugi czytelnik rozstrzyga", "Model porównuje rekord ze stroną "
               "klucza: match / fix / unsure. Bez --apply tylko raport.", (
                   P_YEAR, P_VARIANT, P_MODEL, P_LIMIT,
                   Param("--apply", "Rozstrzygać w bazie?", "bool", default=False,
                         hint="bez tego: na sucho, sam raport + JSON"),
                   P_BATCH,
                   Param("--retry-unsure", "Wziąć też zadania unsure tego modelu?", "bool",
                         default=False),
                   P_REPORT,
               ), paid=True),
        Action("prefill", "Podpowiedzi kryteriów (S6)", "Model odtwarza progi → warunki → "
               "zapisy; wynik do prefill_suggestion, w ekranie jako różnice.",
               (P_YEAR, P_VARIANT, P_MODEL, P_LIMIT, P_BATCH, P_REPORT), paid=True),
        Action("describe", "Opisy rysunków (S7)", "Alt-text dla wycinków bez opisu; "
               "status `auto`, człowiek zatwierdza w ekranie.", (
                   P_YEAR, P_VARIANT, P_MODEL, P_LIMIT, P_BATCH,
                   Param("--force", "Opisać od nowa także te z opisem modelu?", "bool",
                         default=False, hint="opisów człowieka nie tyka"),
                   P_REPORT,
               ), paid=True),
        Action("frame", "Ramki rysunków z siatki (X3)", "Dla zasobów z ramką „cała strona”: "
               "model oddaje bbox, kod tnie PNG. Bez --apply tylko raport.", (
                   P_YEAR, P_VARIANT, P_MODEL, P_LIMIT,
                   Param("--apply", "Ciąć i zapisywać ramki?", "bool", default=False),
                   P_REPORT,
               ), paid=True),
        Action("golden:generate", "Golden set: odpowiedzi ucznia (model A)",
               "Trzy odpowiedzi (full/partial/wrong) na każde zadanie otwarte z korpusu "
               "→ ingest/golden/<rok>/task-N.json.", (
                   P_YEAR,
                   Param("--variant", "Wariant", "choice", choices=VARIANTS, hint="puste = 100"),
                   P_MODEL, P_LIMIT,
                   Param("--force", "Nadpisać istniejące pliki?", "bool", default=False),
                   P_REPORT,
               ), paid=True),
        Action("golden:grade", "Golden set: ocena (model B)", "Ocena wg klucza, próg po progu, "
               "do tych samych plików JSON. Innym modelem niż autor.", (
                   P_YEAR, P_MODEL, P_LIMIT,
                   Param("--force", "Ocenić od nowa także ocenione?", "bool", default=False),
                   P_REPORT,
               ), paid=True),
    )),
    Group("MathJSON", "Zapisy równoważne z kryteriów → MathJSON przez Compute Engine (Node).", (
        Action("mathjson:setup", "Zależności konwertera", "pnpm install @cortex-js/compute-engine "
               "w ingest/mathjson. Raz."),
        Action("mathjson", "Zapisy równoważne → MathJSON", "Normalizacja w Pythonie, "
               "parsowanie w Node; odmowy dostają `failed` z powodem.", (
                   P_YEAR, P_VARIANT,
                   Param("--force", "Przeliczyć od nowa także te z MathJSON-em?", "bool",
                         default=False, hint="nie tyka zapisów approved"),
                   P_REPORT,
               )),
    )),
    Group("Raporty i testy", "Domknięcie A2 i testy warstwy Pythona.", (
        Action("corpus:report", "Raport kompletności korpusu (G2.7)", "Definicja „zrobione” "
               "dla A2 liczona po corpus_task i po task.", (
                   Param("--copy-to-docs", "Skopiować też do docs/corpus-A2.txt?", "bool",
                         default=False),
                   P_REPORT,
               )),
        Action("test:python", "Testy ingestu", "ruff + pytest; testy z bazą tworzą własne "
               "bazy klucz_test_*."),
    )),
)


def actions() -> dict[str, Action]:
    return {a.task: a for g in CATALOG for a in g.actions}


# ── część czysta: odpowiedzi → flagi ───────────────────────────────────────

def build_args(action: Action, answers: dict[str, object]) -> list[str]:
    """Odpowiedzi (po fladze) → lista argumentów po `--`.

    Pusta odpowiedź, `None` i `False` znaczą „bez tej flagi". Kolejność jak
    w katalogu, żeby komenda w podglądzie była taka sama jak wykonana.
    """
    out: list[str] = []
    for param in action.params:
        value = answers.get(param.flag)
        if value is None or value is False or value == "":
            continue
        if param.kind == "bool":
            out.append(param.flag)
        elif param.kind == "words":
            out.append(param.flag)
            out.extend(str(value).split())
        else:
            out.extend([param.flag, str(value)])
    return out


def command_for(action: Action, args: list[str]) -> list[str]:
    """`task <nazwa> -- <flagi>`; bez `--`, gdy flag nie ma."""
    cmd = ["task", action.task]
    if args:
        cmd += ["--", *args]
    return cmd


def shell_line(cmd: list[str]) -> str:
    """Do pokazania człowiekowi — z cudzysłowami tam, gdzie jest spacja."""
    return " ".join(f'"{c}"' if " " in c else c for c in cmd)


# ── warstwa interaktywna ───────────────────────────────────────────────────

BACK = "__back__"
QUIT = "__quit__"
CUSTOM = "__custom__"

# Jedna paleta dla rich i questionary. Nazwy mówią o roli, nie o kolorze.
PALETTE = {
    "primary": "#4c8dff",   # wskaźnik, nazwy, ramki
    "ok": "#3fb37f",        # odpowiedzi, sukces
    "paid": "#e0b35a",      # akcje płatne
    "danger": "#ef6b5e",    # akcje kasujące, błędy
    "dim": "#8a94a6",       # opisy, podpowiedzi
}
POINTER = "▸"
NONE_CHOICE = "(bez flagi)"


def _utf8_console_streams() -> None:
    """Konsola Windows bez tego wybiera cp1250 i wywala się na strzałkach i ramkach."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def _console():
    from rich.console import Console
    _utf8_console_streams()
    return Console(highlight=False)


def _style():
    from questionary import Style
    p = PALETTE
    return Style([
        ("qmark", f"fg:{p['primary']} bold"),
        ("question", "bold"),
        ("answer", f"fg:{p['ok']} bold"),
        ("pointer", f"fg:{p['primary']} bold"),
        ("highlighted", f"fg:{p['primary']} bold"),
        ("selected", f"fg:{p['ok']}"),
        ("instruction", f"fg:{p['dim']}"),
        ("separator", f"fg:{p['dim']}"),
        # klasy własne, użyte w tytułach pozycji (FormattedText)
        ("name", "bold"),
        ("task", f"fg:{p['primary']}"),
        ("desc", f"fg:{p['dim']}"),
        ("paid", f"fg:{p['paid']} bold"),
        ("danger", f"fg:{p['danger']} bold"),
        ("count", f"fg:{p['primary']}"),
    ])


def _select(message: str, choices: list, instruction: str = "") -> object:
    """Wspólny wybór z listy; Ctrl-C leci wyżej jako przerwanie."""
    import questionary
    picked = questionary.select(
        message, choices=choices, style=_style(), pointer=POINTER,
        use_shortcuts=False, use_indicator=False,
        instruction=instruction or "↑↓ i Enter",
    ).ask()
    if picked is None:
        raise KeyboardInterrupt
    return picked


def _fit(text: str, width: int) -> str:
    return text[:width - 1] + "…" if len(text) > width else text.ljust(width)


def _badge(action: Action) -> tuple[str, str]:
    if action.paid:
        return ("class:paid", " [$] ")
    if action.destructive:
        return ("class:danger", " [!] ")
    if action.foreground:
        return ("class:desc", " [⏵] ")
    return ("class:desc", "     ")


def pick_group() -> Group | str:
    """Poziom 1: kategoria. Nazwa, liczba akcji, jedno zdanie opisu."""
    from questionary import Choice, Separator

    width = max(len(g.title) for g in CATALOG) + 2
    choices: list = []
    for group in CATALOG:
        n = len(group.actions)
        plural = "akcja" if n == 1 else ("akcje" if 2 <= n <= 4 else "akcji")
        choices.append(Choice([
            ("class:name", _fit(group.title, width)),
            ("class:count", f"{n:>2} {plural:<6}"),
            ("class:desc", f"  {group.about}"),
        ], value=group))
    choices.append(Separator(" "))
    choices.append(Choice([("class:desc", _fit("Własne polecenie task…", width)),
                           ("class:desc", "          dowolne zadanie spoza katalogu")],
                          value=CUSTOM))
    choices.append(Choice([("class:desc", "Wyjdź")], value=QUIT))
    return _select("Kategoria", choices,
                   instruction="↑↓ i Enter · Ctrl-C wychodzi")


def pick_action(group: Group) -> Action | str:
    """Poziom 2: akcja w kategorii. Tytuł, nazwa zadania, znacznik, opis."""
    from questionary import Choice, Separator
    from rich.panel import Panel

    _console().print(Panel(
        f"[{PALETTE['dim']}]{group.about}[/]\n"
        f"[{PALETTE['dim']}]znaczniki:[/] [{PALETTE['paid']}][$][/] płatne · "
        f"[{PALETTE['danger']}][!][/] kasuje dane · [{PALETTE['dim']}][⏵][/] stoi do Ctrl-C",
        title=f"[bold]{group.title}[/]", border_style=PALETTE["primary"], padding=(0, 1)))

    width = max(len(a.title) for a in group.actions) + 2
    task_width = max(len(a.task) for a in group.actions) + 2
    choices: list = []
    for action in group.actions:
        choices.append(Choice([
            ("class:name", _fit(action.title, width)),
            _badge(action),
            ("class:task", _fit(action.task, task_width)),
            ("class:desc", f" {action.about}"),
        ], value=action))
    choices.append(Separator(" "))
    choices.append(Choice([("class:desc", "← wróć do kategorii")], value=BACK))
    return _select("Akcja", choices, instruction="↑↓ i Enter · Ctrl-C wraca")


def show_action(action: Action) -> None:
    """Karta akcji przed pytaniami: co robi, jakie ma flagi, co znaczą."""
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    console = _console()
    head = f"[bold]{action.title}[/]   [{PALETTE['primary']}]task {action.task}[/]"
    body = f"{action.about}"
    if action.paid:
        body += f"\n[{PALETTE['paid']}]Płatne: przebieg z żywym modelem, z budżetu badawczego.[/]"
    if action.destructive:
        body += f"\n[{PALETTE['danger']}]Kasuje dane. Nie ma cofnięcia.[/]"
    if action.foreground:
        body += f"\n[{PALETTE['dim']}]Stoi na pierwszym planie do wyjścia (Ctrl-C albo \\q).[/]"
    console.print(Panel(body, title=head, title_align="left",
                        border_style=PALETTE["primary"], padding=(0, 1)))
    if not action.params:
        console.print(f"[{PALETTE['dim']}]Bez flag.[/]\n")
        return
    table = Table(box=box.SIMPLE, show_edge=False, pad_edge=False, padding=(0, 1),
                  title=f"[{PALETTE['dim']}]Flagi, o które zapyta menu[/]", title_justify="left")
    table.add_column("flaga", style=PALETTE["primary"], no_wrap=True)
    table.add_column("pytanie", style="bold")
    table.add_column("rodzaj", style=PALETTE["dim"], no_wrap=True)
    table.add_column("co znaczy", style=PALETTE["dim"])
    kinds = {"text": "tekst", "int": "liczba", "bool": "tak/nie", "choice": "lista",
             "words": "kilka wartości"}
    for p in action.params:
        default = ""
        if p.kind == "bool":
            default = "domyślnie tak" if p.default else "domyślnie nie"
        meaning = " · ".join(x for x in (p.hint, default) if x)
        table.add_row(p.flag, p.prompt, kinds[p.kind], meaning)
    console.print(table)
    console.print()


def ask_param(param: Param) -> object:
    """Jedno pytanie. `None` z questionary (Ctrl-C) leci wyżej jako przerwanie."""
    import questionary
    style = _style()
    message = f"{param.flag}  {param.prompt}"
    instruction = param.hint or ""
    if param.kind == "bool":
        answer = questionary.confirm(message, default=bool(param.default), style=style,
                                     instruction=f"({instruction})" if instruction else None).ask()
    elif param.kind == "choice":
        choices = list(param.choices) or (list(_models()) if param.flag == "--model" else [])
        answer = questionary.select(message, choices=[NONE_CHOICE, *choices], style=style,
                                    default=NONE_CHOICE, pointer=POINTER,
                                    instruction=instruction or "↑↓ i Enter").ask()
        if answer == NONE_CHOICE:
            answer = ""
    elif param.kind == "int":
        answer = questionary.text(
            message, default=str(param.default or ""), style=style,
            instruction=f"({instruction}) " if instruction else None,
            validate=lambda v: v.strip() == "" or v.strip().isdigit() or "podaj liczbę",
        ).ask()
    else:
        answer = questionary.text(message, default=str(param.default or ""), style=style,
                                  instruction=f"({instruction}) " if instruction else None).ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer.strip() if isinstance(answer, str) else answer


def ask_params(action: Action) -> dict[str, object]:
    return {p.flag: ask_param(p) for p in action.params}


def show_plan(action: Action, cmd: list[str]) -> None:
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append("$ " + shell_line(cmd), style="bold")
    body.append("\n\nkatalog: " + str(KORZEN_REPO), style=PALETTE["dim"])
    if action.paid:
        body.append("\n\nZanim --apply, dry-run na jednym roczniku. Powtarzalny powód "
                    "w `reasons` to błąd parsera, nie modelu.", style=PALETTE["paid"])
    if action.destructive:
        body.append("\n\nTa akcja KASUJE dane i nie ma cofnięcia.",
                    style=f"bold {PALETTE['danger']}")
    _console().print(Panel(body, title="[bold]Do uruchomienia[/]", title_align="left",
                           border_style=PALETTE["ok"] if not action.destructive
                           else PALETTE["danger"], padding=(0, 1)))


def confirm_run(action: Action) -> bool:
    import questionary
    if not (action.paid or action.destructive):
        answer = questionary.confirm("Uruchomić?", default=True, style=_style()).ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer is True
    word = "PŁACĘ" if action.paid else "KASUJ"
    typed = questionary.text(f"Wpisz {word}, żeby potwierdzić", style=_style(),
                             instruction="(cokolwiek innego = pomiń) ").ask()
    if typed is None:
        raise KeyboardInterrupt
    return typed.strip() == word


def run(cmd: list[str]) -> int:
    """Uruchamia z korzenia repo, z odziedziczonym terminalem — wyjście leci na żywo."""
    task = shutil.which("task")
    if task is None:
        _console().print(f"[{PALETTE['danger']}]BRAK: go-task.[/] "
                         "winget install Task.Task · brew install go-task")
        return 127
    _console().rule(style=PALETTE["dim"])
    try:
        return subprocess.run([task, *cmd[1:]], cwd=str(KORZEN_REPO), check=False).returncode  # noqa: S603
    except KeyboardInterrupt:
        # Ctrl-C trafia też do dziecka (ta sama grupa procesów); tu tylko wracamy do menu.
        return 130
    finally:
        _console().rule(style=PALETTE["dim"])


def show_result(code: int) -> None:
    console = _console()
    if code == 0:
        console.print(f"[{PALETTE['ok']}]✔ zakończone kodem 0[/]")
    elif code == 130:
        console.print(f"[{PALETTE['paid']}]⏹ przerwane (Ctrl-C)[/]")
    else:
        console.print(f"[{PALETTE['danger']}]✘ kod wyjścia {code}[/]  "
                      f"[{PALETTE['dim']}]1: poniżej progu / różnice · "
                      "2: nie ruszyło (brak spisu, klucza API, odmowa --wipe)[/]")
    console.print()


def custom_task() -> list[str] | None:
    """Dowolne `task …` wpisane ręcznie — dla zadań spoza katalogu (np. dev, test:web)."""
    import questionary
    line = questionary.text("task", style=_style(),
                            instruction="(np. `test:contract` albo `ingest -- --limit 1`) ").ask()
    if line is None:
        raise KeyboardInterrupt
    if not line.strip():
        return None
    return ["task", *line.split()]


def banner() -> None:
    from rich.panel import Panel
    mirror = os.environ.get("MIRROR_ROOT", "(z .env, ładuje task)")
    _console().print(Panel(
        f"[{PALETTE['dim']}]korzeń repo[/]  {KORZEN_REPO}\n"
        f"[{PALETTE['dim']}]MIRROR_ROOT[/]  {mirror}\n\n"
        f"[{PALETTE['dim']}]Kategoria → akcja → pytania o flagi → podgląd komendy → "
        "uruchomienie.\nKażda pozycja to `task <nazwa> -- <flagi>` z Taskfile.yml; "
        "menu niczego nie robi samo.[/]",
        title="[bold]Ingest — menu[/]", title_align="left",
        border_style=PALETTE["primary"], padding=(0, 1)))


def run_action(action: Action) -> None:
    show_action(action)
    args = build_args(action, ask_params(action))
    cmd = command_for(action, args)
    show_plan(action, cmd)
    if confirm_run(action):
        show_result(run(cmd))
    else:
        _console().print(f"[{PALETTE['dim']}]pominięte[/]\n")


def main() -> int:
    _utf8_console_streams()
    banner()
    while True:
        try:
            group = pick_group()
        except KeyboardInterrupt:
            _console().print()
            return 0
        if group == QUIT:
            return 0
        if group == CUSTOM:
            try:
                cmd = custom_task()
                if cmd:
                    show_result(run(cmd))
            except KeyboardInterrupt:
                _console().print(f"\n[{PALETTE['dim']}]powrót do kategorii[/]\n")
            continue
        # Poziom 2: zostajemy w kategorii, dopóki człowiek nie wybierze „wróć".
        while True:
            try:
                picked = pick_action(group)
                if picked == BACK:
                    break
                run_action(picked)
            except KeyboardInterrupt:
                _console().print(f"\n[{PALETTE['dim']}]powrót do kategorii[/]\n")
                break


if __name__ == "__main__":
    raise SystemExit(main())
