-- =============================================================================
-- 0001 · Korpus CKE — schemat relacyjny
--
-- Awans z research/schema/schema.sql (sonda 24-25.08.2026). Model bez zmian,
-- nazwy przetłumaczone na angielski zgodnie z CLAUDE.md (słownik pojęć
-- polski → angielski stoi tamże, w sekcji o języku).
--
-- Każda decyzja w tym pliku wynika z pomiaru na pobranym mirrorze, nie
-- z wyobrażenia o tym, jak arkusze są zbudowane.
--
-- Rzecz, którą schemat musi udźwignąć, a której plan z „Kopalni CKE" nie
-- przewidywał: relacja klucz → arkusz jest wiele-do-wielu, nie trójką plików.
-- 31 z 46 kluczy matematyki E8, które deklarują sekcję „Formy arkusza",
-- obsługuje więcej niż jeden arkusz; jeden plik z angielskiego nazywa się
-- OJAP-100-200-400-500-660-K00-2505-zasady.pdf — sześć wariantów w nazwie.
--
-- WIĘZY ZOSTAJĄ OSTRE. UNIQUE (task_id, points) w tabeli `criterion` złapał
-- prawdziwy błąd przy pierwszym ładowaniu w sondzie: sekcja reguł
-- przekrojowych stoi MIĘDZY zadaniami, więc podział tekstu po nagłówkach
-- doklejał ją do zadania poprzedzającego, a jej zdanie „…to otrzymuje
-- 0 punktów" udawało drugi próg. Bez tego więzu błąd wszedłby do korpusu
-- po cichu. Nic tu nie luzować „żeby przeszło" — od tego jest ekran korekty.
--
-- BEGIN/COMMIT celowo NIE MA: migrate.py wykonuje każdy plik w jednej
-- transakcji razem z wpisem do schema_migrations.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 00 · KOLACJA — polskie sortowanie tam, gdzie będzie potrzebne
-- -----------------------------------------------------------------------------
-- Cluster stoi w C.UTF-8, bo obraz postgres:*-alpine opiera się na musl,
-- które NIE MA pl_PL.UTF-8 — initdb z takim locale w ogóle nie wstanie.
-- Polskie porządkowanie wchodzi więc jawnie, przez ICU (wkompilowane w PG 15+
-- także w wariancie alpine), i jest widoczne w schemacie, czyli w kontrakcie.
-- Kolację nakłada się per kolumna albo per zapytanie (ORDER BY x COLLATE pl_icu)
-- dopiero tam, gdzie kolejność ma znaczenie dla człowieka.
CREATE COLLATION IF NOT EXISTS pl_icu (provider = icu, locale = 'pl-PL');

-- =============================================================================
-- 01 · PODSTAWA PROGRAMOWA — punkt zaczepienia dla wszystkiego
-- =============================================================================

-- Reżim wymagań. Archiwum E8 obejmuje trzy i NIE WOLNO ich mieszać bez
-- oznaczenia: zadania z lat 2021-2024 sprawdzały okrojony zakres pandemiczny.
-- Reżim wisi na sesji egzaminacyjnej, nie na roku publikacji pliku — po
-- naprawie parsera 7 plików z rocznika 2019 ma sesję 2018 (CKE trzyma stare
-- arkusze na nowej stronie rocznikowej).
CREATE TABLE requirement_regime (
    id            smallserial PRIMARY KEY,
    code          text        NOT NULL UNIQUE,   -- 'pp2017', 'wym-covid', 'pp2024'
    name          text        NOT NULL,
    session_from  date        NOT NULL,
    session_to    date,                          -- NULL = obowiązuje nadal
    source        text                           -- Dz.U. albo komunikat CKE
);

-- Drzewo wymagań podstawy programowej. Klucze CKE podają przy KAŻDYM zadaniu
-- wymaganie ogólne (cyfra rzymska) i co najmniej jedno szczegółowe (dział
-- rzymski + punkt arabski), razem z etapem edukacyjnym („KLASY IV–VI",
-- „KLASY VII i VIII"). Zmierzone: 100% kluczy matematyki, polskiego
-- i angielskiego E8 to niesie. To znaczy, że mapa braków — funkcja, którą
-- „Kopalnia CKE" wpisała do F0 jako osobną pracę — wypada z parsera za darmo.
CREATE TABLE requirement (
    id            serial      PRIMARY KEY,
    regime_id     smallint    NOT NULL REFERENCES requirement_regime(id),
    parent_id     integer     REFERENCES requirement(id),
    kind          text        NOT NULL CHECK (kind IN ('general', 'specific')),
    stage         text,                          -- 'IV-VI', 'VII-VIII', NULL dla ogólnych
    path          text        NOT NULL,          -- 'V.3' — dział rzymski + punkt
    content       text        NOT NULL,
    UNIQUE (regime_id, kind, stage, path)
);

-- =============================================================================
-- 02 · DOKUMENTY I FORMY — warstwa plików, prosto z urls.tsv
-- =============================================================================

-- Jeden wiersz = jeden PDF w mirrorze. Kolumny lustrzane wobec urls.tsv, żeby
-- ingest był przepisaniem, nie tłumaczeniem.
CREATE TABLE document (
    id            serial      PRIMARY KEY,
    segment       text        NOT NULL,          -- 'e8' | 'matura-f2023' | 'matura-f2015'
    year          smallint    NOT NULL,          -- rocznik STRONY, z której wzięty
    code          text        NOT NULL,          -- 'OMAP'
    variants      text,                          -- '100,X' — surowe, do audytu
    session       date,                          -- NULL dla arkuszy pokazowych (85 plików)
    kind          text        NOT NULL CHECK (kind IN
                    ('paper', 'marking_scheme', 'answer_sheet',
                     'transcript', 'attachment', 'annex')),
    kind_source   text        NOT NULL,          -- 'suffix'|'prefix'|'directory'|'default'
    url           text        NOT NULL UNIQUE,
    path          text        NOT NULL,
    sha256        char(64),                      -- kotwica odtwarzalności
    pages         smallint,
    ingest_status text        NOT NULL DEFAULT 'new'
                    CHECK (ingest_status IN ('new', 'parsed', 'approved', 'rejected'))
);
CREATE INDEX document_code_session_idx ON document (code, session, kind);

-- FORMA ARKUSZA = to, co uczeń dostaje na stole: konkretny wariant
-- dostosowania w konkretnej wersji, w konkretnej sesji. Nie plik — plik jest
-- nośnikiem.
--
-- Dwie osie, które łatwo pomylić, a znaczą co innego:
--   variant  100/200/400/500/700/800/C00/K00/Q00 — dostosowanie. 700 i 800 mają
--            INNE, łatwiejsze zadania na to samo wymaganie, więc rodzą osobne
--            rekordy `task`, spięte przez `requirement`.
--   version  X/Y — bliźniaki: inna treść, TE SAME kryteria i to samo wymaganie.
CREATE TABLE exam_form (
    id            serial      PRIMARY KEY,
    regime_id     smallint    NOT NULL REFERENCES requirement_regime(id),
    exam          text        NOT NULL CHECK (exam IN ('e8', 'matura')),
    subject       text        NOT NULL,          -- 'matematyka'
    code          text        NOT NULL,          -- 'OMAP'
    variant       text        NOT NULL,          -- '100'
    version       text,                          -- 'X' | 'Y' | NULL, gdy brak bliźniaka
    session       date        NOT NULL,
    UNIQUE (code, variant, version, session)
);

-- N:M — sedno tej sekcji. Klucz OMAP-100-2505-zasady.pdf deklaruje w nagłówku:
--   Formy arkusza: OMAP-100-2505 (wersje X i Y), OMAP-200-2505, OMAP-400-2505,
--                  OMAP-C00-2505, OMAP-K00-2505, OMAU-C00-2505
-- czyli JEDEN klucz obsługuje SZEŚĆ form, a forma 100 ma DWA zeszyty zadań.
-- Trójka „arkusz + karta + zasady" z „Kopalni CKE" nie ma tu gdzie stanąć.
CREATE TABLE exam_form_document (
    exam_form_id  integer     NOT NULL REFERENCES exam_form(id) ON DELETE CASCADE,
    document_id   integer     NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    role          text        NOT NULL CHECK (role IN
                    ('paper', 'marking_scheme', 'answer_sheet',
                     'transcript', 'attachment')),
    PRIMARY KEY (exam_form_id, document_id, role)
);

-- =============================================================================
-- 03 · ZADANIA — dwa poziomy, bo bliźniaki dzielą kryteria, a nie treść
-- =============================================================================

-- ZADANIE = jednostka logiczna: numer w arkuszu, pula punktów, kryteria,
-- wymagania podstawy. Wspólne dla wersji X i Y.
--
-- Zmierzone na OMAP-100-2505-zasady.pdf: zadania 1-15 (po 1 pkt, zamknięte)
-- mają nagłówek „Rozwiązanie – wersja X | wersja Y" z RÓŻNYMI odpowiedziami,
-- a zadania 16-21 (2-3 pkt, otwarte) nie mają go wcale — ich treść i kryteria
-- są identyczne w obu wersjach. Stąd podział: kryteria wiszą tutaj,
-- odpowiedzi na `task_version`.
CREATE TABLE task (
    id                serial   PRIMARY KEY,
    marking_scheme_id integer  NOT NULL REFERENCES document(id),  -- skąd kryteria
    number            text     NOT NULL,      -- '16', '4.1' (angielski numeruje podpunktami)
    position          smallint NOT NULL,
    max_points        smallint NOT NULL CHECK (max_points BETWEEN 0 AND 60),
    kind              text     NOT NULL CHECK (kind IN
                        ('closed', 'open_short', 'open_extended', 'essay')),
    UNIQUE (marking_scheme_id, number)
);

-- N:M — zadanie mapuje się na JEDNO wymaganie ogólne i OD JEDNEGO DO KILKU
-- szczegółowych. Zmierzone: zadanie 20 z OMAP-100-2505 wskazuje trzy
-- (XI.3, XI.5 z klas IV-VI oraz IV.1). Tabela pośrednia jest tu konieczna,
-- a nie „na wszelki wypadek".
CREATE TABLE task_requirement (
    task_id        integer    NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    requirement_id integer    NOT NULL REFERENCES requirement(id),
    PRIMARY KEY (task_id, requirement_id)
);

-- WERSJA ZADANIA = konkretna treść w konkretnej formie. Tu mieszka to, co
-- różni bliźniaki: sformułowanie, dane liczbowe, poprawna odpowiedź, rysunek.
CREATE TABLE task_version (
    id             serial     PRIMARY KEY,
    task_id        integer    NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    exam_form_id   integer    NOT NULL REFERENCES exam_form(id),
    paper_id       integer    REFERENCES document(id),   -- skąd treść
    content        text,                      -- po rekonstrukcji układu
    content_status text       NOT NULL DEFAULT 'auto'
                     CHECK (content_status IN ('auto', 'corrected', 'approved')),
    page           smallint,
    bbox           numeric[4],                -- gdzie na stronie, do korekty
    UNIQUE (task_id, exam_form_id)
);

-- Odpowiedź wzorcowa zadania zamkniętego — na WERSJI, bo X i Y różnią się.
-- W kluczu wygląda to tak:  Rozwiązanie – wersja X | wersja Y
--                                       BD          |  AC
-- Płaska ekstrakcja skleja to w „BD AC" i traci przypisanie do kolumny;
-- odzyskuje je dopiero extract_tables().
CREATE TABLE model_answer (
    id              serial   PRIMARY KEY,
    task_version_id integer  NOT NULL REFERENCES task_version(id) ON DELETE CASCADE,
    part            text,                     -- '1', '2' przy zadaniach wieloczęściowych
    answer          text     NOT NULL,        -- 'BD', 'FP', 'the cinema'
    UNIQUE (task_version_id, part)
);

-- =============================================================================
-- 04 · KRYTERIA — trzy poziomy dysjunkcji, bo tyle ich jest w kluczu
-- =============================================================================

-- Zmierzone na zadaniu 20 (0-3) z OMAP-100-2505:
--
--   3 punkty – pełne rozwiązanie          ← PRÓG      (criterion)
--       poprawny sposób obliczenia..., wynik (105 cm²)
--   2 punkty                              ← PRÓG
--       • poprawny sposób obliczenia pola czworokąta AECF, np.
--            P = ... albo P = ... albo P = ...   ← ZAPISY (condition_expression)
--       LUB                                      ← granica WARUNKU
--       • poprawny sposób obliczenia, jaką częścią pola...  (criterion_condition)
--   1 punkt  … (sześć warunków połączonych LUB)
--   0 punktów – rozwiązanie błędne albo brak
--
-- Próg jest osiągnięty, gdy spełniony jest DOWOLNY warunek, a warunek —
-- gdy uczeń zapisał DOWOLNY z równoważnych zapisów. Spłaszczenie tego do
-- jednego pola tekstowego oznacza, że silnik dostanie akapit prozy zamiast
-- listy sprawdzalnych alternatyw — a to jest cała teza produktu.
CREATE TABLE criterion (
    id           serial   PRIMARY KEY,
    task_id      integer  NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    points       smallint NOT NULL,
    label        text,                         -- 'pełne rozwiązanie'
    description  text,                         -- treść progu, gdy bez wypunktowania
    position     smallint NOT NULL,
    UNIQUE (task_id, points)                   -- ← ten więz złapał prawdziwy błąd
);

CREATE TABLE criterion_condition (
    id           serial   PRIMARY KEY,
    criterion_id integer  NOT NULL REFERENCES criterion(id) ON DELETE CASCADE,
    description  text     NOT NULL,
    position     smallint NOT NULL
);

-- Zapisy równoważne wewnątrz warunku (rozdzielone „albo" / „lub").
-- `mathjson` wypełnia konwerter (G2.6) — Compute Engine porównuje wyrażenia,
-- nie stringi, więc to on jest docelową postacią, a nie tekst.
CREATE TABLE condition_expression (
    id           serial   PRIMARY KEY,
    condition_id integer  NOT NULL REFERENCES criterion_condition(id) ON DELETE CASCADE,
    expression   text     NOT NULL,            -- 'P = 1/2⋅15·2⋅(15∶5)'
    mathjson     jsonb,
    position     smallint NOT NULL
);

-- Przykładowe rozwiązania z klucza — „I sposób", „II sposób". Zmierzone:
-- 100% kluczy matematyki E8 je ma. To gotowy materiał few-shot autorstwa
-- samej komisji; w kluczach maturalnych sekcja nazywa się inaczej, więc
-- parser potrzebuje słownika nagłówków per segment, nie jednego regexa.
CREATE TABLE example_solution (
    id           serial   PRIMARY KEY,
    task_id      integer  NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    points       smallint NOT NULL,            -- „ocenione na 2 punkty"
    method       text,                         -- 'I', 'II'
    content      text     NOT NULL,
    position     smallint NOT NULL
);

-- Pary „odpowiedź → dlaczego punkt / dlaczego nie". W kluczu z angielskiego
-- są osobnymi tabelami (Przykłady odpowiedzi akceptowanych | Uzasadnienie
-- oraz …niepoprawnych | Uzasadnienie) i w płaskim tekście nie widać ich wcale.
-- „Trzy filary" zakładały, że ten materiał trzeba napisać samemu.
CREATE TABLE answer_example (
    id            serial   PRIMARY KEY,
    task_id       integer  NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    content       text     NOT NULL,
    accepted      boolean  NOT NULL,
    justification text
);

-- =============================================================================
-- 05 · REGUŁY PRZEKROJOWE — sekcja „Uwagi ogólne", której pipeline nie miał
-- =============================================================================

-- Zmierzone: 60% kluczy matematyki E8 i 100% maturalnych ma sekcję „Uwagi
-- ogólne". Nie są to kryteria zadania, tylko reguły całego arkusza:
--   • błąd rachunkowy przy poprawnej metodzie obniża ocenę o 1 punkt
--   • w zadaniach 16-21 sam poprawny wynik to 0 punktów
--   • 11 tolerancji dla uczniów uprawnionych do dostosowanych zasad
-- W pipelinie z „Architektury Klucza" (Normalize → MatchCriteria →
-- EvaluateClosed → EvaluateOpen → Compose) nie ma dla nich miejsca: działają
-- PO ocenie wszystkich kryteriów naraz, czyli w kroku Compose.
CREATE TABLE rule (
    id                serial   PRIMARY KEY,
    marking_scheme_id integer  NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    kind              text     NOT NULL CHECK (kind IN
                        ('arithmetic', 'conflicting_solutions', 'result_only',
                         'accommodation', 'calculator', 'other')),
    content           text     NOT NULL,
    tasks_from        text,                    -- '16'  — zakres obowiązywania
    tasks_to          text,                    -- '21'
    position          smallint NOT NULL
);

-- =============================================================================
-- 06 · GRAFIKA — 38% zadań matematyki bez niej nie istnieje
-- =============================================================================

-- Zmierzone na 11 arkuszach matematyki E8 wariantu bazowego: 84 z 219 zadań
-- (38%) odwołuje się do diagramu, wykresu, siatki albo osi liczbowej;
-- w arkuszach siedzi 587 obiektów graficznych. Zadanie 1 z 2505 brzmi
-- „Na diagramie przedstawiono kwoty…" i po ekstrakcji tekstu jest bezużyteczne.
--
-- Rysunek wisi na WERSJI, nie na zadaniu: bliźniaki X i Y mają ten sam
-- schemat, ale inne liczby na osiach.
--
-- UWAGA: po sondzie `bbox` to CAŁA STRONA, nie wycinek wokół rysunku —
-- wykrywanie regionu grafiki jest robotą G2.4, nie tej migracji.
CREATE TABLE asset (
    id                 serial     PRIMARY KEY,
    task_version_id    integer    NOT NULL REFERENCES task_version(id) ON DELETE CASCADE,
    kind               text       NOT NULL CHECK (kind IN
                         ('drawing', 'diagram', 'chart', 'table', 'map', 'sheet_music')),
    path               text       NOT NULL,    -- ŚCIEŻKA WZGLĘDNA w blob storage
    page               smallint   NOT NULL,
    bbox               numeric[4] NOT NULL,    -- skąd wycięty, do ponownego renderu
    description        text,                   -- alt-text; WCAG nie jest opcją
    description_status text       NOT NULL DEFAULT 'none'
                         CHECK (description_status IN ('none', 'auto', 'approved'))
);

-- =============================================================================
-- 07 · WIDOKI — to, po co ten model w ogóle powstał
-- =============================================================================

-- Mapa braków: wymaganie → ile zadań je sprawdza i z jaką pulą punktów.
-- Ten widok jest testem schematu: jeśli da się go napisać bez podzapytań
-- korelowanych po tekście, model trzyma.
CREATE VIEW tasks_per_requirement AS
SELECT r.regime_id,
       r.stage,
       r.path,
       r.content,
       count(DISTINCT t.id)           AS tasks,
       sum(t.max_points)              AS points,
       count(DISTINCT tv.exam_form_id) AS forms
FROM requirement r
JOIN task_requirement tr ON tr.requirement_id = r.id
JOIN task t              ON t.id = tr.task_id
JOIN task_version tv     ON tv.task_id = t.id
WHERE r.kind = 'specific'
GROUP BY r.regime_id, r.stage, r.path, r.content;

-- Zadania-bliźniaki: to samo zadanie w dwóch wersjach. „Kopalnia CKE" nazwała
-- je „darmowym zestawem, za który normalnie płaci się autorom" — bez podziału
-- zadanie/wersja nie da się ich w ogóle zapytać.
CREATE VIEW twins AS
SELECT t.id AS task_id,
       t.number,
       f.code, f.variant, f.session,
       count(*) AS versions,
       array_agg(f.version ORDER BY f.version) AS version_list
FROM task t
JOIN task_version tv ON tv.task_id = t.id
JOIN exam_form f     ON f.id = tv.exam_form_id
GROUP BY t.id, t.number, f.code, f.variant, f.session
HAVING count(*) > 1;
