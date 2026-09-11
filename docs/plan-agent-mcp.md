# Plan agenta — narzędzia MCP, pełny dostęp do bazy, ingest i nawigacja w ekranie

Stan na 8.09.2026. Panel agenta w ekranie korekty (`ingest/correction/ui/src/agent/`)
jest makietą: strumień, markdown i układ są gotowe, za nimi nie stoi żaden model.
Ten plan podłącza prawdziwego agenta i daje mu cztery rzeczy:

1. **pełny dostęp do bazy** — schemat, każde zapytanie, każdy wiersz z pochodzeniem,
   zdrowie danych; zapis do korpusu tą samą drogą co człowiek i model `verify`;
2. **wszystkie akcje ingestu** — każda pozycja z katalogu `task menu` jako narzędzie,
   uruchamiana jako zadanie w tle z logiem i raportem;
3. **świadomość stanu projektu i tego, jak co działa** — liczby korpusu, migracje,
   przebiegi, gałąź, klucze; dokumenty z `docs/`, `CLAUDE.md` i `DECYZJE.md` oraz
   kod źródłowy jako baza wiedzy, żeby agent tłumaczył, a nie zgadywał;
4. **integrację z frontem** — agent wie, na co patrzy korektor, i umie go zaprowadzić
   na właściwą stronę ekranu korekty albo inspektora, do właściwego pola.

Narzędzia powstają **raz, jako serwer MCP**. Ten sam zestaw dostaje agent w panelu
i każdy klient MCP z zewnątrz (Claude Code, Claude Desktop) — jedna definicja, zero
dryfu między „co umie panel" a „co umie terminal".

> **Definicja „zrobione"**
> Panel bez etykiety „makieta": pytanie o otwarte zadanie dostaje odpowiedź z bazy,
> prośba „pokaż zadania otwarte bez kryteriów" otwiera właściwą stronę inspektora,
> „odpal dry-run verify na 2025" uruchamia przebieg i wraca z raportem, a każda
> płatna albo kasująca akcja i każdy surowy zapis SQL czekają na kliknięcie
> człowieka. `claude mcp add` podłącza ten sam serwer do Claude Code. Rozmowy,
> wywołania narzędzi i koszt tokenów siedzą w schemacie (migracja 0010).

---

## Decyzje, na których stoi plan

**Jeden rejestr narzędzi, dwa wejścia.** Narzędzia to funkcje Pythona z modelami
Pydantic, zarejestrowane w `FastMCP` (oficjalny pakiet `mcp`, MIT). Serwer ma trzy
transporty z tego samego kodu: **stdio** (`task mcp` — dla Claude Code/Desktop),
**streamable HTTP** zamontowany w aplikacji ekranu korekty pod `/mcp` (127.0.0.1,
jak reszta ekranu) i **in-memory** dla agenta w tym samym procesie. Agent w panelu
jest więc *klientem MCP* jak każdy inny — jeśli coś działa w panelu, działa też
z terminala, i odwrotnie.

**Model wybiera człowiek w panelu, z trzech.** Lista do wyboru to
`AGENT_MODELS` (stała w `agent/runtime.py`): `openai:gpt-5.6-luna`,
`openai:gpt-5.6-terra`, `openai:gpt-5.6-sol`. Wybór jest **cechą sesji** — zapisany
w `agent_session.model`, widoczny w nagłówku panelu, zmiana = nowa rozmowa (historia
z jednego modelu nie miesza się z drugim, koszt liczy się per model). Domyślny
z `AGENT_MODEL` w `.env` (gdy brak — `terra`). Pętla idzie przez LangChain
(`llm.chat_model`), więc każdy z trzech musi mieć wpis w `llm.PRICING`:
`sol` dziś go nie ma — dochodzi w M4. Cennik OpenAI na 8.09.2026
(developers.openai.com/api/docs/pricing): `gpt-5.6-sol` **$4 / $20** za milion
tokenów wejścia / wyjścia (cache $0,40), stawka promocyjna **do 21.11.2026**, potem
$5 / $30; terra $2 / $12 i luna $0,20 / $1,20 bez zmian wobec `PRICING`. Wsad −50%
dla wszystkich trzech. Model spoza listy — także obecny
w `PRICING` — panel nie pokazuje, a `POST /api/agent/sessions` odrzuca z 400.
Cennik i `Spend` z `llm.py` liczą tokeny agenta tak samo jak tokeny `verify` —
koszt rozmów wchodzi do raportu, rozbity na modele. Bez klucza API panel wraca
do makiety i mówi to wprost.

**Zapis do korpusu wyłącznie przez `db.save` i `db.decide`.** To reguła z planu
A2-auto (X7) i zostaje: narzędzia `task_save`, `task_decide`, `task_add_row` wołają
ten sam kod co formularz i `verify`, więc więzy, status z porównania z bazą
i dziennik `correction_event` działają bez wyjątków. Autor w dzienniku: `actor =
'agent'` (rozszerzenie więzu w 0010) z nazwą modelu — powrót do stanu sprzed agenta
to jeden `UPDATE`, jak przy `verify`.

**„Pełny dostęp" znaczy: czytanie bez ograniczeń, zapis surowym SQL-em tylko po
potwierdzeniu.** `db_query` wykonuje dowolny SELECT w transakcji `READ ONLY`
z limitem czasu i wierszy. `db_execute` istnieje, ale każde wywołanie zatrzymuje
agenta i pokazuje człowiekowi treść zapytania z liczbą wierszy, które zmieni
(policzoną w wycofanej transakcji). Klik „Wykonaj" jest bramką — tą samą, którą
dla parsera był ekran korekty. Więzów bazy agent nie luzuje: rekord odrzucony przez
więz jest robotą dla człowieka, jak w `verify`.

**Akcje ingestu z katalogu, nie z ręki.** `cli/app.py` ma już `CATALOG`: nazwa
zadania w Taskfile, parametry z typami, znaczniki `paid`/`destructive`/`foreground`.
Narzędzia MCP powstają z niego automatycznie — nowa akcja w menu jest nową akcją
agenta bez dopisywania czegokolwiek. Ten sam test, który dziś pilnuje zgodności
katalogu z Taskfile, pilnuje narzędzi. Akcje `foreground` (`correction`, `db:psql`,
`menu`) są wyłączone: serwer nie uruchamia serwera, a konsola nie ma z kim rozmawiać.

**Nawigacja to adres, nie stan.** Ekran korekty ma routing po stronie serwera
(rozstrzygnięcie z 8.09.2026), więc „zaprowadź mnie do zadania 42" to
`window.location.assign("/task/42?...")`. Adresy składa Python (jeden budowniczy
URL-i), panel je tylko wykonuje. Skutek uboczny: każda nawigacja to przeładowanie
strony, więc **rozmowa musi żyć po stronie serwera** — stąd tabele w 0010, a nie
`localStorage`.

**Człowiek w pętli przez przerwanie grafu, nie przez drugi czat.** Potwierdzenia
(płatne, kasujące, `db_execute`) to `interrupt` LangGrapha z checkpointerem:
agent staje w połowie kroku, panel pokazuje przycisk, `POST /api/agent/confirm`
wznawia dokładnie ten krok. Bez potwierdzenia narzędzie nie wykonuje niczego.

---

## Architektura

```
przeglądarka (127.0.0.1:8600)
  ┌─ widok (Overview / TaskForm / Inspect*)       ┌─ AgentPanel ──────────────────┐
  │  adres = stan widoku                          │  POST /api/agent/messages     │
  │                                               │    ← SSE: token · tool · ui · │
  │  window.location.assign(url) ◄────────────────│       confirm · done          │
  └───────────────────────────────────────────────┴───────────────────────────────┘
                                   │ screen context: view, task_id, page, table, row, query
                                   ▼
correction.app (FastAPI)
  /api/agent/*  ──► agent.runtime ──► LangChain create_agent(model, tools, checkpointer)
                        │                      │ narzędzia = load_mcp_tools(session)
                        │                      ▼
                        │            klient MCP in-memory ──► agent.server (FastMCP)
                        │                                        │
  /mcp (streamable HTTP) ────────────────────────────────────────┤  ten sam rejestr
  `task mcp` (stdio: Claude Code / Desktop) ─────────────────────┘
                                                                 │
              ┌──────────────┬──────────────┬────────────────────┼───────────────┐
              ▼              ▼              ▼                    ▼               ▼
        tools/database  tools/corpus   tools/ingest         tools/knowledge  tools/navigation
        inspector,      db.save,       CATALOG → subprocess  docs/, CLAUDE.md, budowniczy
        READ ONLY SQL   db.decide      `task <nazwa> -- …`   kod, DECYZJE.md  adresów ekranu
                                       jobs: log + status
```

Granica warstw bez zmian: agent siedzi w `ingest/` (Python, localhost), C# go nie
widzi. To ten sam wyjątek, którym jest ekran korekty — narzędzie edytujące rekordy,
*zanim* staną się korpusem.

---

## Narzędzia — katalog

Nazwy po angielsku, opisy po polsku (czyta je model i człowiek w liście narzędzi).
Każde narzędzie wraca JSON-em; długie wyniki są przycinane z polem
`truncated: true` i podpowiedzią, jak zawęzić — kontekst modelu nie jest miejscem
na 1436 wierszy.

### A. Baza — `agent/tools/database.py`

| Narzędzie | Co robi | Skąd |
|---|---|---|
| `db_schema(table?)` | tabele, kolumny, typy, NOT NULL, klucze obce, wartości CHECK, **kto pisze kolumnę**, notatka o tabeli | `inspector.schema`, `SOURCES`, `TABLE_NOTES`, `load_enums` |
| `db_query(sql, limit=200)` | dowolny SELECT/WITH; transakcja `READ ONLY`, `statement_timeout` 15 s, `limit+1` wierszy → `truncated` | psycopg, `db.connect` |
| `db_execute(sql)` | INSERT/UPDATE/DELETE — **wymaga potwierdzenia**; przed pytaniem liczy wiersze w wycofanej transakcji i pokazuje je człowiekowi | jw. |
| `inspect_list(table, filters, sort, page)` | lista wierszy z filtrami inspektora (te same operatory, allowlista kolumn) + adres widoku | `inspector.list_rows`, `ListView.url` |
| `inspect_record(table, id)` | wiersz, rodzice, dzieci, **pochodzenie** (PDF, strona, wycinek, czy plik jest na dysku) | `inspector.get_row`, `provenance` |
| `db_health(key?)` | wszystkie kontrole z liczbami albo jedna z listą wierszy | `inspector.CHECKS` |
| `db_migrations()` | które migracje weszły, których brakuje, suma SHA | `schema.migrate` |

### B. Korpus — `agent/tools/corpus.py` (zapis tylko tędy)

| Narzędzie | Co robi | Skąd |
|---|---|---|
| `task_get(id, page?)` | zadanie w kształcie formularza: wersje, odpowiedzi, progi → warunki → zapisy, wymagania, zasoby, podpowiedzi, uwagi modelu, sąsiedzi | `api._task_payload` |
| `task_find(scope, status?, kind?, text?)` | lista zadań w zakresie (rocznik, kod, wariant) — to samo co przegląd | `db.list_tasks`, `db.next_pending` |
| `task_save(id, fields)` | zapis pól w nazwach formularza (`criterion.12.points`) — różnicę liczy `db.save` | `db.save` |
| `task_add_row(id, what, parent?)` | nowy próg / warunek / zapis | `db.add_*` |
| `task_decide(id, action, reasons)` | approve / reject / reopen; `actor='agent'`, `model=` z sesji — **wymaga potwierdzenia** | `db.decide` |
| `asset_frame(asset_id, box)` / `asset_describe(asset_id, text)` | ramka i opis jak w formularzu (walidacja `assets.BOX_FIELDS`, status `corrected`) | `assets`, `db.save` |
| `task_page_image(id, n?)` | obraz strony klucza jako treść obrazkowa (model wielomodalny może „spojrzeć") | `pages.render` |

### C. Ingest — `agent/tools/ingest.py` + `agent/jobs.py`

Jedno narzędzie na `Action` z `CATALOG`, nazwa `ingest_<task>` (`:` → `_`):
`ingest_mirror`, `ingest_ingest`, `ingest_parser_snapshot`, `ingest_crops`,
`ingest_verify`, `ingest_prefill`, `ingest_describe`, `ingest_frame`,
`ingest_golden_generate`, `ingest_golden_grade`, `ingest_mathjson`,
`ingest_corpus_report`, `ingest_correction_report`, `ingest_migrate`,
`ingest_up`, `ingest_down`, `ingest_db_reset`, `ingest_test_python`.
Schemat parametrów z `Param.kind` (text/int/bool/choice/words), flagi składa
istniejące `build_args`, polecenie — `command_for`. Znaczniki:

- `paid` → potwierdzenie z szacunkiem kosztu (sztuki × stawka z ostatniego raportu
  `verify`: ~$0,018/zadanie) i reguła z 4.09: **agent proponuje dry-run przed
  `--apply`** i mówi, gdy tej kolejności nie było;
- `destructive` → potwierdzenie z pełnym opisem, co znika (`db:reset`: korpus ORAZ
  Azurite; `ingest --wipe`; `crops --prune --yes`);
- `foreground` → narzędzia nie ma.

Przebieg to **zadanie w tle** (`jobs.py`): `subprocess.Popen(["task", name, "--",
*args], cwd=KORZEN_REPO, env={..., PYTHONIOENCODING: utf-8})`, stdout+stderr do
pliku `data/reports/jobs/<id>.log`, wpis w tabeli `agent_job` (pid, polecenie,
start, koniec, kod wyjścia, ścieżka logu). Dzięki temu `--reload` uvicorna nie gubi
przebiegu: rejestr jest w bazie, log na dysku. Narzędzia obok: `job_status(id)`,
`job_log(id, tail=80)`, `job_cancel(id)` (Windows: `CREATE_NEW_PROCESS_GROUP` +
`CTRL_BREAK_EVENT`), `job_list()`. Po zakończeniu agent czyta raport z
`data/reports/` (`report_read`) i streszcza liczby — nie wkleja całości.

### D. Wiedza i stan — `agent/tools/knowledge.py`, `agent/tools/status.py`

| Narzędzie | Co robi |
|---|---|
| `project_status()` | jedno wywołanie: liczby korpusu (`reports.corpus`), statusy i S6′/S7/S8′ (`stats.collect`), zdrowie (`inspector.health`), migracje, gałąź i ostatni commit, obecność `.env` i kluczy (nazwy, nie wartości), osiągalność bazy i mirrora, zadania w tle, ostatnie raporty |
| `docs_search(query, limit)` | wyszukiwanie po sekcjach dokumentów: `docs/*.html` (tekst z HTML, cięty po nagłówkach), `docs/*.md`, `README.md`, `CLAUDE.md`, `ingest/README.md`, `ingest/schema/README.md`, opcjonalnie `cke-mirror/docs/DECYZJE.md` i `LICZBY.md` (`CKE_MIRROR_DOCS` w `.env`). Indeks budowany przy starcie, bez embeddingów i bez kosztu — słowa + nagłówki wystarczą na 15 plików |
| `docs_read(path, section?)` | pełna sekcja dokumentu |
| `code_search(pattern, glob?)` / `code_read(path, lines?)` | grep i odczyt źródeł **wewnątrz repozytorium**; `.env`, `data/`, `node_modules`, `.venv` poza zasięgiem — agent tłumaczy, „jak co działa", z kodu, nie z pamięci |
| `explain_column(table, column)` | kto pisze, kiedy, sekcja z `database-guide.html` |
| `explain_check(key)` | dlaczego kontrola istnieje i co z nią zrobić (`Check.why` + link do listy) |
| `report_list()` / `report_read(name)` | raporty z `data/reports/` |

Do tego **system prompt** (`agent/prompts.py`): mapa warstw i granica C#/Python,
słownik pojęć z `CLAUDE.md`, zasady (więzy ostre, dry-run przed apply, zapis tylko
przez narzędzia korpusu), spis widoków ekranu z adresami, oraz **migawka stanu**
wstrzykiwana na początku sesji (to samo co `project_status`, skrócone) — agent zna
liczby, zanim o nie zapyta, a migawka jest deterministyczna i cache'owalna.

### E. Nawigacja i kontekst ekranu — `agent/tools/navigation.py`

Kontekst przychodzi **z każdą wiadomością** od panelu: `{view, path, query,
task_id, page, table, row_id, health_key}` — wszystko z `window.location`
i `data-view`, bo panel i widok to osobne korzenie Reacta. Agent dostaje go
w treści tury („operator patrzy na zadanie 42, strona 7 klucza"), nie musi pytać.

| Narzędzie | Zdarzenie do panelu | Co robi panel |
|---|---|---|
| `ui_navigate(target)` | `{"type":"ui","action":"navigate","url":…}` | po `done` — `window.location.assign(url)`; wcześniej pokazuje chip z adresem |
| `ui_focus(field)` | `{"type":"ui","action":"focus","name":"criterion.12.points"}` | `querySelector('[name=…]')` → `scrollIntoView` + podświetlenie; działa, bo nazwy pól formularza są stabilne |
| `ui_open_pdf(document_id, page)` | `{"type":"ui","action":"open","url":…}` | nowa karta z `/inspect/document/{id}.pdf#page=n` |

`target` jest strukturą, nie stringiem — adres składa `agent/urls.py`
(jedyne miejsce): `{"view":"task","id":42,"page":7,"scope":{…}}` →
`/task/42?page=7&year=2025`; `{"view":"inspect_list","table":"task",
"filters":{"kind":"open_short","review_status":"pending"}}` → adres z filtrami
w składni inspektora; `{"view":"health","key":"open_without_criteria"}`;
`{"view":"next","scope":…}`; `{"view":"inspect_record","table":"asset","id":9,
"pdf_page":3}`. Test pilnuje, że każdy adres z budowniczego odpowiada trasie
w `correction/app.py` (jak dziś test skorupy).

Nawigacja wykonuje się **po zakończeniu strumienia**: przeładowanie w połowie
odpowiedzi urwałoby ją, a rozmowa i tak jest na serwerze — po wczytaniu nowej
strony panel odtwarza historię z `GET /api/agent/sessions/{id}`.

---

## Klocki

### M1 — Serwer MCP i narzędzia tylko do odczytu

`ingest/agent/{__init__,server,tools/database,tools/knowledge,tools/status}.py`,
`agent/urls.py`. `FastMCP("klucz")` z rejestrem narzędzi z grup A (bez
`db_execute`), D i E (same adresy, bez zdarzeń — na tym etapie zwracają URL).
Wejścia: `python -m agent.server` (stdio) i `app.mount("/mcp",
mcp.streamable_http_app())` w `correction/app.py`. Taskfile: `task mcp`.

Zależności: `mcp` (MIT; sprawdzić licencję i wersję przy dodaniu, jak przy każdej
paczce), nic więcej — indeks dokumentów jest ręczny (tokenizacja + wagi nagłówków),
HTML → tekst przez `html.parser` ze standardowej biblioteki.

**Zrobione, gdy:** `claude mcp add --transport stdio klucz -- task mcp` w Claude
Code pozwala zapytać „ile zadań otwartych bez kryteriów i skąd ta kontrola" i dostać
liczbę z `db_health` plus zdanie z `explain_check`; `db_query` z `UPDATE` w środku
kończy się błędem `READ ONLY`, a test to pokazuje; test katalogu: każda trasa
z `app.py` ma odpowiednik w `urls.py`.

### M2 — Zapis do korpusu i protokół potwierdzeń

`tools/corpus.py` (grupa B) i `db_execute`. Potwierdzenie jest **cechą narzędzia**
w rejestrze (`requires_confirmation=True` w metadanych MCP), nie logiką w panelu:
serwer MCP wykonuje takie narzędzie tylko z ważnym tokenem potwierdzenia
w argumentach; bez tokenu wraca `{"confirm": {"id", "title", "preview", "cost?"}}`.
Dla `db_execute` preview to SQL + liczba wierszy z wycofanej transakcji; dla
`task_decide` — rekord i powody. Klient zewnętrzny (Claude Code) widzi to samo:
narzędzie odmawia, dopóki człowiek nie potwierdzi w panelu ekranu korekty
(`/api/agent/confirm/{id}`) — jedna bramka na wszystkie wejścia.

Migracja `0010_agent.sql`: więz `correction_event.actor` i `task.reviewed_by`
rozszerzone o `'agent'`; tabele `agent_session (id, model, created_at, screen)`,
`agent_message (session_id, role, content, tool_calls jsonb, input_tokens,
output_tokens, created_at)`, `agent_tool_call (message_id, tool, arguments jsonb,
result_summary, confirmed_by, duration_ms)`, `agent_job (…)`, `agent_confirmation
(id, tool, arguments, preview, created_at, decided_at, decision)`. Test więzu:
`actor = 'llm'` odrzucone, `'agent'` przyjęte.

**Zrobione, gdy:** `task_save` z błędną punktacją dostaje ten sam komunikat co
formularz (`friendly_error`), a więz `UNIQUE (task_id, points)` zostaje; `db_execute`
bez potwierdzenia nie zmienia ani jednego wiersza (test na czerwono najpierw);
`task_decide` zostawia w `correction_event` wpis `actor='agent'` z modelem.

### M3 — Akcje ingestu jako zadania w tle

`tools/ingest.py` (generacja z `CATALOG`), `agent/jobs.py`, narzędzia `job_*`,
`report_*`. Test: nazwy narzędzi ↔ `CATALOG` ↔ Taskfile (rozszerzenie
istniejącego testu menu), flagi składane przez `build_args` dają dokładnie tę
komendę, którą pokazuje `task menu`. Test integracyjny: `ingest_migrate_status`
uruchamia prawdziwy `task migrate:status` i log ląduje w pliku.

**Zrobione, gdy:** „odpal dry-run verify na 2025/100" tworzy `agent_job`, a po
zakończeniu agent podaje match/fix/unsure z raportu; `ingest_verify` z `--apply`
bez wcześniejszego dry-runu w sesji dostaje ostrzeżenie w potwierdzeniu; `db:reset`
pyta dwa razy (jak menu).

### M4 — Pętla agenta, rozmowa w bazie, SSE

`agent/runtime.py`: `AGENT_MODELS = ("openai:gpt-5.6-luna", "openai:gpt-5.6-terra",
"openai:gpt-5.6-sol")`; `llm.PRICING` dostaje wpis `"openai:gpt-5.6-sol": (4.0, 20.0)`
z komentarzem „promocja do 21.11.2026, potem (5.0, 30.0)" — po tej dacie cennik
do poprawienia, inaczej raport zaniży koszt; test `check_model` na czerwono bez wpisu.
`llm.chat_model(session.model)` → `langchain.agents.create_agent`
z narzędziami z `langchain_mcp_adapters.load_mcp_tools(session)` (sesja in-memory
do `agent.server`), checkpointer w Postgresie (`langgraph-checkpoint-postgres`,
MIT) albo w pamięci na start, `HumanInTheLoopMiddleware` dla narzędzi
z `requires_confirmation`. Historia tury: ostatnie N wiadomości + streszczenie
starszych; wyniki narzędzi przycięte do limitu znaków. `Spend` per sesja
z `usage_metadata`.

Zależności nowe w tym klocku: `langchain-mcp-adapters` (MIT) i — gdy checkpointer
ma przeżyć restart — `langgraph-checkpoint-postgres` (MIT). `langchain 1.3.17`
i `langgraph 1.2.11` są już w lockfile; `create_agent` i `HumanInTheLoopMiddleware`
sprawdzone w `.venv` 8.09.2026.

`agent/api.py`: `GET /api/agent/config` (lista `AGENT_MODELS` z etykietą i stawką
za milion tokenów, domyślny, czy klucz jest), `POST /api/agent/sessions` (nowa
rozmowa: `model` z listy albo 400, migawka stanu),
`GET /api/agent/sessions/{id}` (historia), `POST /api/agent/sessions/{id}/messages`
(treść + kontekst ekranu → `text/event-stream`: `token`, `tool_call`, `tool_result`,
`ui`, `confirm`, `usage`, `done`, `error`), `POST /api/agent/confirm/{id}`
(`accept`/`reject` → wznowienie grafu), `POST /api/agent/sessions/{id}/stop`.
Pętla LangChaina jest blokująca — biegnie w wątku, do generatora SSE idzie kolejką.
Ten sam wartownik `sec-fetch-site` co przy zapisie zadania.

Testy bez modelu: `GenericFakeChatModel` z zaplanowanymi wywołaniami narzędzi
(pytanie → `db_health` → odpowiedź; pytanie → `db_execute` → `confirm` → wznowienie),
zdarzenia SSE sprawdzane jako lista.

**Zrobione, gdy:** test z fałszywym modelem przechodzi całą pętlę z przerwaniem
i wznowieniem; rozmowa po restarcie serwera jest w `agent_message`; koszt sesji
w `usage` zgadza się z `Spend`.

### M5 — Panel: prawdziwy agent, potwierdzenia, nawigacja

`ui/src/agent/`: `agentClient.ts` (SSE przez `fetch` + `ReadableStream`, bo
`EventSource` nie robi POST), `screenContext.ts` (z `window.location` i `data-view`),
`ToolChip.tsx` (wywołanie narzędzia w rozmowie: nazwa, argumenty w skrócie, czas,
rozwijany wynik), `ConfirmCard.tsx` (tytuł, preview w `<pre>`, koszt, „Wykonaj" /
„Odrzuć"), obsługa `ui`: chip z adresem od razu, `assign` po `done`, `focus`
z podświetleniem, `open` w nowej karcie. Identyfikator sesji w `localStorage`,
historia z serwera po każdym wczytaniu strony; „Nowa rozmowa" w nagłówku panelu.
`ModelPicker.tsx` w nagłówku: `<select>` z trzech pozycji z `GET /api/agent/config`
(etykieta `luna · $0,2/$1,2`, `terra · $2/$12`, `sol · $4/$20`), wybrany model w miejsce
dzisiejszej etykiety „makieta"; zmiana wyboru zakłada nową sesję po pytaniu
„Zacząć nową rozmowę z <model>?", bo model jest cechą sesji. Ostatni wybór
w `localStorage` (jak szerokość panelu) — podpowiedź przy następnej rozmowie,
nie stan. `mockAgent` zostaje jako tryb bez klucza (`AGENT_MODEL=mock` albo brak
klucza — `config` mówi to wprost), etykieta „makieta" wraca tylko wtedy.

Testy vitest: zdarzenia → stan rozmowy; `confirm` rysuje kartę i wysyła decyzję;
`ui navigate` nie przeładowuje przed `done` (jsdom: `assign` podmienione);
`ModelPicker` pokazuje dokładnie trzy pozycje z `config` i wysyła wybrany model
w `POST /api/agent/sessions`.

**Zrobione, gdy:** „gdzie są zasoby bez wycinka?" → odpowiedź z liczbą i chip
`/inspect/health/asset_without_crop`, po kliknięciu/„done" strona się otwiera,
a panel wraca z historią; „popraw punktację progu 12 na 2" → `task_save` przez
chip, pole podświetlone w formularzu, status zadania bez zmiany do rozstrzygnięcia.

### M6 — Domknięcie: raport, dokumentacja, decyzje

`correction:report` i `corpus:report` dostają linię „agent: N sesji, M wywołań
narzędzi, $X" (`agent_message`, `agent_tool_call`). `README.md`: `task mcp`
i `AGENT_MODEL`; `.env.example`: `AGENT_MODEL`, `CKE_MIRROR_DOCS`; `CLAUDE.md`:
zdanie w „Granica warstw" (agent jak ekran korekty — wyjątek localhost; zapis tylko
przez narzędzia korpusu). Wpis do `docs/decyzje-A2.md`: MCP jako jedyny rejestr
narzędzi, `actor='agent'`, potwierdzenia jako cecha narzędzia. `docs/ingest-overview.html`
dostaje sekcję „Agent".

**Zrobione, gdy:** `task test` zielony, przegląd w `docs/review/` przez skill
`code-review`, `task corpus:report` pokazuje koszt agenta.

---

## Kolejność

| Krok | Klocek | Zależy od | Wynik dla człowieka |
|---|---|---|---|
| 1 | M1 | — | narzędzia w Claude Code od pierwszego dnia; panel jeszcze makietą |
| 2 | M2 | M1 | zapis do korpusu z bramką; migracja 0010 |
| 3 | M4 | M1 | agent w procesie, testy z fałszywym modelem, SSE |
| 4 | M5 | M4 | **panel przestaje być makietą** |
| 5 | M3 | M2 | przebiegi ingestu z panelu i z terminala |
| 6 | M6 | wszystko | raport, docs, decyzje |

M2 i M4 są niezależne — mogą iść równolegle. Każdy klocek to jedna gałąź
`feat/agent-m<n>` i jeden PR z czterema zielonymi checkami. Szacunek: 6–8 dni
pracy. W `docs/project-status.html` pierwsza pozycja to próbka ludzka — ten plan
jej nie zastępuje; agent ma ją *przyspieszyć* (nawigacja do kandydatów z
`model_notes`, zapis z panelu), więc M1+M4+M5 warto mieć przed siadaniem do próbki.

## Koszt

Tokeny agenta liczy `Spend`. Tura z dwoma–trzema narzędziami to 8–20 k tokenów
wejścia (system prompt + migawka + wyniki) i ~0,5 k wyjścia: przy `gpt-5.6-terra`
$0,02–0,05, przy `gpt-5.6-luna` dziesięć razy mniej, przy `gpt-5.6-sol` około
dwa razy więcej niż terra ($4/$20 do 21.11.2026, potem $5/$30). Domyślnie `terra`
(jakość użycia narzędzi ważniejsza niż cena),
a wybór w panelu jest per rozmowa, więc pytanie „czy luna wystarcza do nawigacji
i odczytu, a terra jest potrzebna dopiero do poprawek" dostaje odpowiedź z raportu:
`correction:report` rozbija koszt i liczbę tur na modele. Liczba do raportu,
nie do wiary.

## Ryzyka i pułapki

- **Wynik narzędzia zalewa kontekst.** `db_query` bez `LIMIT` na `criterion` to
  3315 wierszy. Limit 200 wierszy i przycięcie do ~8 k znaków w każdym narzędziu,
  z jawnym `truncated` — model ma dopytać z filtrem, nie dostać obciętą prawdę
  bez wiedzy, że jest obcięta.
- **Klient zewnętrzny omija panel.** Claude Code woła `db_execute` — potwierdzenie
  i tak jest w panelu ekranu korekty (jedna bramka). Gdy ekran nie stoi, narzędzia
  z `requires_confirmation` odmawiają z komunikatem „uruchom `task correction`
  i potwierdź w panelu". Bez tego stdio byłoby tylnym wejściem.
- **`--reload` uvicorna a zadania w tle.** Rejestr w bazie, log w pliku, proces
  potomny w osobnej grupie — restart serwera nie ubija przebiegu i nie gubi jego
  stanu. Test: `job_status` po ponownym imporcie modułu widzi zadanie.
- **Model rozstrzyga sam.** `task_decide` zawsze wymaga potwierdzenia — agent
  w panelu to pomocnik korektora, nie trzeci `verify`. Przebieg masowy ma swoje
  narzędzie (`ingest_verify`) z regułą dry-run.
- **`sec-fetch-site` a klient MCP po HTTP.** `/mcp` nie ma tego wartownika
  (klienci to programy, nie strony); dlatego zapisy z `/mcp` i tak idą przez
  potwierdzenie w panelu, a serwer słucha wyłącznie na 127.0.0.1.
- **Windows.** `task` z `shutil.which`, `PYTHONIOENCODING=utf-8` do procesu
  potomnego (pułapka z `CLAUDE.md`), log w UTF-8, anulowanie przez grupę procesów.
  CI na Linuxie jest źródłem prawdy o zielonym buildzie — także dla tego kodu.
- **Wersje bibliotek.** `langchain 1.3.17` i `langgraph 1.2.11` są już w lockfile;
  `create_agent`, `HumanInTheLoopMiddleware` i `load_mcp_tools` sprawdzić w tych
  wersjach w pierwszej godzinie M4, zanim powstanie cokolwiek, co od nich zależy.
  Gdy API się różni — przerwanie zrobić wprost przez `interrupt()` w narzędziu.

## Dziennik wykonania

| Data | Klocek | Wynik |
|---|---|---|
| 8.09 | M1 | serwer MCP (`ingest/agent/server.py`), 20 narzędzi odczytu; `task mcp` po stdio sprawdzony ręcznym handshake; `/mcp` jako trasa z gołym ASGI (Mount dawał 307); menedżer sesji w cyklu życia aplikacji |
| 8.09 | M2 | migracja 0010; zgoda jako cecha narzędzia (`confirm.py`); narzędzia korpusu przez `db.save`/`db.decide`; `db_execute` z próbą w wycofanej transakcji; więz `used_at` poprawiony po czerwonym teście (`=` przepuszczało NULL) |
| 8.09 | M4 | pętla `create_agent` + klient MCP in-memory; **interceptor z `interrupt()` zamiast `HumanInTheLoopMiddleware`** — podgląd zgody liczą narzędzia, a nie pętla; rozmowa w bazie; SSE; testy z modelem skryptowanym |
| 8.09 | M5 | panel na żywo: wybór modelu, chipy narzędzi, karty zgody, nawigacja po `done`, historia po wczytaniu strony; makieta zostaje bez klucza; 78 testów frontu |
| 8.09 | smoke | pierwsza tura z luna: 6 wywołań narzędzi (w tym samonaprawa po błędnym SQL), 100 kawałków strumienia, $0,039 — za drogo przez `task_find` na 201 wierszach → sufit 100 i podpowiedź w promptcie; **Responses API** konieczne dla gpt-5.6 z narzędziami |
| 8.09 | M3 | narzędzia `ingest_*` z `CATALOG`, przebiegi w tle z rejestrem w bazie; kod wyjścia NTSTATUS ze znakiem |
| 8.09 | M6 | koszt agenta w `correction:report` i `corpus:report`; README, CLAUDE.md, `.env.example`, `decyzje-A2.md`, sekcja w `ingest-overview.html` |

Odstępstwa od planu: `mcp` przypięty do `<2` (adaptery LangChaina wymagają 1.x);
`langgraph-checkpoint-postgres` nie dodany — stan grafu w pamięci procesu, historia
z bazy; przerwanie w toku po restarcie przepada i panel mówi to wprost.
Do zrobienia poza planem: przegląd kodu w `docs/review/` i próbka ludzka z panelem.
