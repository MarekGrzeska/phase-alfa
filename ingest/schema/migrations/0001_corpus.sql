-- =============================================================================
-- 0001 · Korpus CKE — schemat relacyjny
--
-- Awans z research/schema/schema.sql (sonda 24-25.08.2026) bez zmian w modelu.
-- Każda decyzja w tym pliku wynika z pomiaru na pobranym mirrorze, nie
-- z wyobrażenia o tym, jak arkusze są zbudowane.
--
-- Rzecz, którą schemat musi udźwignąć, a której plan z „Kopalni CKE" nie
-- przewidywał: relacja klucz → arkusz jest wiele-do-wielu, nie trójką plików.
-- 31 z 46 kluczy matematyki E8, które deklarują sekcję „Formy arkusza",
-- obsługuje więcej niż jeden arkusz; jeden plik z angielskiego nazywa się
-- OJAP-100-200-400-500-660-K00-2505-zasady.pdf — sześć wariantów w nazwie.
--
-- WIĘZY ZOSTAJĄ OSTRE. UNIQUE (zadanie_id, punkty) w `kryterium` złapał
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

-- Archiwum E8 obejmuje trzy reżimy wymagań i NIE WOLNO ich mieszać bez
-- oznaczenia: zadania z lat 2021-2024 sprawdzały okrojony zakres pandemiczny.
-- Reżim wisi na sesji egzaminacyjnej, nie na roku publikacji pliku.
CREATE TABLE rezim (
    id            smallserial PRIMARY KEY,
    kod           text        NOT NULL UNIQUE,   -- 'pp2017', 'wym-covid', 'pp2024'
    nazwa         text        NOT NULL,
    sesja_od      date        NOT NULL,
    sesja_do      date,                          -- NULL = obowiązuje nadal
    zrodlo        text                           -- Dz.U. albo komunikat CKE
);

-- Drzewo wymagań. Klucze CKE podają przy KAŻDYM zadaniu wymaganie ogólne
-- (cyfra rzymska) i co najmniej jedno szczegółowe (dział rzymski + punkt
-- arabski), razem z etapem edukacyjnym („KLASY IV–VI", „KLASY VII i VIII").
-- Zmierzone: 100% kluczy matematyki, polskiego i angielskiego E8 to niesie.
-- To znaczy, że mapa braków wypada z parsera klucza za darmo.
CREATE TABLE wymaganie (
    id            serial      PRIMARY KEY,
    rezim_id      smallint    NOT NULL REFERENCES rezim(id),
    parent_id     integer     REFERENCES wymaganie(id),
    rodzaj        text        NOT NULL CHECK (rodzaj IN ('ogolne', 'szczegolowe')),
    etap          text,                          -- 'IV-VI', 'VII-VIII', NULL dla ogólnych
    sciezka       text        NOT NULL,          -- 'V.3' — dział rzymski + punkt
    tresc         text        NOT NULL,
    UNIQUE (rezim_id, rodzaj, etap, sciezka)
);

-- =============================================================================
-- 02 · DOKUMENTY I FORMY — warstwa plików, prosto z urls.tsv
-- =============================================================================

-- Jeden wiersz = jeden PDF w mirrorze. Kolumny lustrzane wobec urls.tsv, żeby
-- ingest był przepisaniem, nie tłumaczeniem.
CREATE TABLE dokument (
    id            serial      PRIMARY KEY,
    segment       text        NOT NULL,          -- 'e8' | 'matura-f2023' | 'matura-f2015'
    rocznik       smallint    NOT NULL,          -- rocznik STRONY, z której wzięty
    kod           text        NOT NULL,          -- 'OMAP'
    warianty      text,                          -- '100,X' — surowe, do audytu
    sesja         date,                          -- NULL dla arkuszy pokazowych (85 plików)
    typ           text        NOT NULL CHECK (typ IN
                    ('arkusz', 'zasady_oceniania', 'karta_odpowiedzi',
                     'transkrypcja', 'zalacznik', 'aneks')),
    zrodlo_typu   text        NOT NULL,          -- 'sufiks'|'prefiks'|'katalog'|'domyslny'
    url           text        NOT NULL UNIQUE,
    sciezka       text        NOT NULL,
    sha256        char(64),                      -- kotwica odtwarzalności
    stron         smallint,
    ingest_status text        NOT NULL DEFAULT 'nowy'
                    CHECK (ingest_status IN ('nowy', 'sparsowany', 'zatwierdzony', 'odrzucony'))
);
CREATE INDEX dokument_kod_sesja_idx ON dokument (kod, sesja, typ);

-- FORMA = to, co uczeń dostaje na stole: konkretny wariant dostosowania
-- w konkretnej wersji, w konkretnej sesji. Nie plik — plik jest nośnikiem.
--
-- Dwie osie, które łatwo pomylić, a znaczą co innego:
--   wariant  100/200/400/500/700/800/C00/K00/Q00 — dostosowanie. 700 i 800 mają
--            INNE, łatwiejsze zadania na to samo wymaganie, więc rodzą osobne
--            rekordy `zadanie`, spięte przez `wymaganie`.
--   wersja   X/Y — bliźniaki: inna treść, TE SAME kryteria i to samo wymaganie.
CREATE TABLE forma (
    id            serial      PRIMARY KEY,
    rezim_id      smallint    NOT NULL REFERENCES rezim(id),
    egzamin       text        NOT NULL CHECK (egzamin IN ('e8', 'matura')),
    przedmiot     text        NOT NULL,          -- 'matematyka'
    kod           text        NOT NULL,          -- 'OMAP'
    wariant       text        NOT NULL,          -- '100'
    wersja        text,                          -- 'X' | 'Y' | NULL, gdy brak bliźniaka
    sesja         date        NOT NULL,
    UNIQUE (kod, wariant, wersja, sesja)
);

-- N:M — sedno tej sekcji. Klucz OMAP-100-2505-zasady.pdf deklaruje w nagłówku:
--   Formy arkusza: OMAP-100-2505 (wersje X i Y), OMAP-200-2505, OMAP-400-2505,
--                  OMAP-C00-2505, OMAP-K00-2505, OMAU-C00-2505
-- czyli JEDEN klucz obsługuje SZEŚĆ form, a forma 100 ma DWA zeszyty zadań.
CREATE TABLE forma_dokument (
    forma_id      integer     NOT NULL REFERENCES forma(id) ON DELETE CASCADE,
    dokument_id   integer     NOT NULL REFERENCES dokument(id) ON DELETE CASCADE,
    rola          text        NOT NULL CHECK (rola IN
                    ('arkusz', 'klucz', 'karta', 'transkrypcja', 'zalacznik')),
    PRIMARY KEY (forma_id, dokument_id, rola)
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
-- odpowiedzi na `zadanie_wersja`.
CREATE TABLE zadanie (
    id            serial      PRIMARY KEY,
    klucz_id      integer     NOT NULL REFERENCES dokument(id),  -- skąd kryteria
    numer         text        NOT NULL,          -- '16', '4.1' (angielski numeruje podpunktami)
    kolejnosc     smallint    NOT NULL,
    punkty_max    smallint    NOT NULL CHECK (punkty_max BETWEEN 0 AND 60),
    typ           text        NOT NULL CHECK (typ IN
                    ('zamkniete', 'otwarte_krotkie', 'otwarte_rozszerzone', 'wypracowanie')),
    UNIQUE (klucz_id, numer)
);

-- N:M — zadanie mapuje się na JEDNO wymaganie ogólne i OD JEDNEGO DO KILKU
-- szczegółowych. Zmierzone: zadanie 20 z OMAP-100-2505 wskazuje trzy
-- (XI.3, XI.5 z klas IV-VI oraz IV.1).
CREATE TABLE zadanie_wymaganie (
    zadanie_id    integer     NOT NULL REFERENCES zadanie(id) ON DELETE CASCADE,
    wymaganie_id  integer     NOT NULL REFERENCES wymaganie(id),
    PRIMARY KEY (zadanie_id, wymaganie_id)
);

-- ZADANIE_WERSJA = konkretna treść w konkretnej formie. Tu mieszka to, co
-- różni bliźniaki: sformułowanie, dane liczbowe, poprawna odpowiedź, rysunek.
CREATE TABLE zadanie_wersja (
    id            serial      PRIMARY KEY,
    zadanie_id    integer     NOT NULL REFERENCES zadanie(id) ON DELETE CASCADE,
    forma_id      integer     NOT NULL REFERENCES forma(id),
    arkusz_id     integer     REFERENCES dokument(id),   -- skąd treść
    tresc         text,                          -- po rekonstrukcji układu
    tresc_status  text        NOT NULL DEFAULT 'automat'
                    CHECK (tresc_status IN ('automat', 'poprawiona', 'zatwierdzona')),
    strona        smallint,
    bbox          numeric[4],                    -- gdzie na stronie, do korekty
    UNIQUE (zadanie_id, forma_id)
);

-- Odpowiedź wzorcowa zadania zamkniętego — na WERSJI, bo X i Y różnią się.
-- W kluczu wygląda to tak:  Rozwiązanie – wersja X | wersja Y
--                                       BD          |  AC
-- Płaska ekstrakcja skleja to w „BD AC" i traci przypisanie do kolumny.
CREATE TABLE odpowiedz_wzorcowa (
    id            serial      PRIMARY KEY,
    wersja_id     integer     NOT NULL REFERENCES zadanie_wersja(id) ON DELETE CASCADE,
    podpunkt      text,                          -- '1', '2' przy zadaniach wieloczęściowych
    odpowiedz     text        NOT NULL,          -- 'BD', 'FP', 'the cinema'
    UNIQUE (wersja_id, podpunkt)
);

-- =============================================================================
-- 04 · KRYTERIA — trzy poziomy dysjunkcji, bo tyle ich jest w kluczu
-- =============================================================================

-- Zmierzone na zadaniu 20 (0-3) z OMAP-100-2505:
--
--   3 punkty – pełne rozwiązanie          ← PRÓG
--       poprawny sposób obliczenia..., wynik (105 cm²)
--   2 punkty                              ← PRÓG
--       • poprawny sposób obliczenia pola czworokąta AECF, np.
--            P = ... albo P = ... albo P = ...      ← ZAPISY RÓWNOWAŻNE
--       LUB                                          ← granica WARUNKU
--       • poprawny sposób obliczenia, jaką częścią pola...
--   1 punkt  … (sześć warunków połączonych LUB)
--   0 punktów – rozwiązanie błędne albo brak
--
-- Próg jest osiągnięty, gdy spełniony jest DOWOLNY warunek, a warunek —
-- gdy uczeń zapisał DOWOLNY z równoważnych zapisów. Spłaszczenie tego do
-- jednego pola tekstowego oznacza, że silnik dostanie akapit prozy zamiast
-- listy sprawdzalnych alternatyw — a to jest cała teza produktu.
CREATE TABLE kryterium (
    id            serial      PRIMARY KEY,
    zadanie_id    integer     NOT NULL REFERENCES zadanie(id) ON DELETE CASCADE,
    punkty        smallint    NOT NULL,
    etykieta      text,                          -- 'pełne rozwiązanie'
    opis          text,                          -- treść progu, gdy bez wypunktowania
    kolejnosc     smallint    NOT NULL,
    UNIQUE (zadanie_id, punkty)                  -- ← ten więz złapał prawdziwy błąd
);

CREATE TABLE kryterium_warunek (
    id            serial      PRIMARY KEY,
    kryterium_id  integer     NOT NULL REFERENCES kryterium(id) ON DELETE CASCADE,
    opis          text        NOT NULL,
    kolejnosc     smallint    NOT NULL
);

-- Zapisy równoważne wewnątrz warunku (rozdzielone „albo" / „lub").
-- `mathjson` wypełnia konwerter (G2.6) — Compute Engine porównuje wyrażenia,
-- nie stringi, więc to on jest docelową postacią, a nie tekst.
CREATE TABLE warunek_zapis (
    id            serial      PRIMARY KEY,
    warunek_id    integer     NOT NULL REFERENCES kryterium_warunek(id) ON DELETE CASCADE,
    zapis         text        NOT NULL,          -- 'P = 1/2⋅15·2⋅(15∶5)'
    mathjson      jsonb,
    kolejnosc     smallint    NOT NULL
);

-- Przykładowe rozwiązania z klucza — „I sposób", „II sposób". Zmierzone:
-- 100% kluczy matematyki E8 je ma. Gotowy materiał few-shot autorstwa
-- samej komisji.
CREATE TABLE rozwiazanie_przykladowe (
    id            serial      PRIMARY KEY,
    zadanie_id    integer     NOT NULL REFERENCES zadanie(id) ON DELETE CASCADE,
    punkty        smallint    NOT NULL,          -- „ocenione na 2 punkty"
    sposob        text,                          -- 'I', 'II'
    tresc         text        NOT NULL,
    kolejnosc     smallint    NOT NULL
);

-- Pary „odpowiedź → dlaczego punkt / dlaczego nie". W kluczu z angielskiego
-- są osobnymi tabelami (Przykłady odpowiedzi akceptowanych | Uzasadnienie
-- oraz …niepoprawnych | Uzasadnienie) i w płaskim tekście nie widać ich wcale.
CREATE TABLE przyklad_odpowiedzi (
    id            serial      PRIMARY KEY,
    zadanie_id    integer     NOT NULL REFERENCES zadanie(id) ON DELETE CASCADE,
    tresc         text        NOT NULL,
    akceptowana   boolean     NOT NULL,
    uzasadnienie  text
);

-- =============================================================================
-- 05 · REGUŁY PRZEKROJOWE — sekcja „Uwagi ogólne", której pipeline nie miał
-- =============================================================================

-- Zmierzone: 60% kluczy matematyki E8 i 100% maturalnych ma sekcję „Uwagi
-- ogólne". Nie są to kryteria zadania, tylko reguły całego arkusza:
--   • błąd rachunkowy przy poprawnej metodzie obniża ocenę o 1 punkt
--   • w zadaniach 16-21 sam poprawny wynik to 0 punktów
--   • 11 tolerancji dla uczniów uprawnionych do dostosowanych zasad
-- Działają PO ocenie wszystkich kryteriów naraz, czyli w kroku Compose.
CREATE TABLE regula (
    id            serial      PRIMARY KEY,
    klucz_id      integer     NOT NULL REFERENCES dokument(id) ON DELETE CASCADE,
    rodzaj        text        NOT NULL CHECK (rodzaj IN
                    ('rachunkowa', 'sprzeczne_rozwiazania', 'sam_wynik',
                     'dostosowanie', 'kalkulator', 'inna')),
    tresc         text        NOT NULL,
    zadania_od    text,                          -- '16'  — zakres obowiązywania
    zadania_do    text,                          -- '21'
    kolejnosc     smallint    NOT NULL
);

-- =============================================================================
-- 06 · GRAFIKA — 38% zadań matematyki bez niej nie istnieje
-- =============================================================================

-- Zmierzone na 11 arkuszach matematyki E8 wariantu bazowego: 84 z 219 zadań
-- (38%) odwołuje się do diagramu, wykresu, siatki albo osi liczbowej;
-- w arkuszach siedzi 587 obiektów graficznych.
--
-- Rysunek wisi na WERSJI, nie na zadaniu: bliźniaki X i Y mają ten sam
-- schemat, ale inne liczby na osiach.
--
-- UWAGA: po sondzie `bbox` to CAŁA STRONA, nie wycinek wokół rysunku —
-- wykrywanie regionu grafiki jest robotą G2.4, nie tej migracji.
CREATE TABLE zasob (
    id            serial      PRIMARY KEY,
    wersja_id     integer     NOT NULL REFERENCES zadanie_wersja(id) ON DELETE CASCADE,
    rodzaj        text        NOT NULL CHECK (rodzaj IN
                    ('rysunek', 'diagram', 'wykres', 'tabela', 'mapa', 'nuty')),
    sciezka       text        NOT NULL,          -- ŚCIEŻKA WZGLĘDNA w blob storage
    strona        smallint    NOT NULL,
    bbox          numeric[4]  NOT NULL,          -- skąd wycięty, do ponownego renderu
    opis          text,                          -- alt-text; WCAG nie jest opcją
    opis_status   text        NOT NULL DEFAULT 'brak'
                    CHECK (opis_status IN ('brak', 'automat', 'zatwierdzony'))
);

-- =============================================================================
-- 07 · WIDOKI — to, po co ten model w ogóle powstał
-- =============================================================================

-- Mapa braków: wymaganie → ile zadań je sprawdza i z jaką pulą punktów.
-- Ten widok jest testem schematu: jeśli da się go napisać bez podzapytań
-- korelowanych po tekście, model trzyma.
CREATE VIEW zadania_per_wymaganie AS
SELECT w.rezim_id,
       w.etap,
       w.sciezka,
       w.tresc,
       count(DISTINCT z.id)          AS zadan,
       sum(z.punkty_max)             AS punktow,
       count(DISTINCT zw.forma_id)   AS form
FROM wymaganie w
JOIN zadanie_wymaganie zwym ON zwym.wymaganie_id = w.id
JOIN zadanie z             ON z.id = zwym.zadanie_id
JOIN zadanie_wersja zw     ON zw.zadanie_id = z.id
WHERE w.rodzaj = 'szczegolowe'
GROUP BY w.rezim_id, w.etap, w.sciezka, w.tresc;

-- Zadania-bliźniaki: to samo zadanie w dwóch wersjach. Bez podziału
-- zadanie/wersja nie da się ich w ogóle zapytać.
CREATE VIEW blizniaki AS
SELECT z.id AS zadanie_id,
       z.numer,
       f.kod, f.wariant, f.sesja,
       count(*) AS wersji,
       array_agg(f.wersja ORDER BY f.wersja) AS wersje
FROM zadanie z
JOIN zadanie_wersja zw ON zw.zadanie_id = z.id
JOIN forma f           ON f.id = zw.forma_id
GROUP BY z.id, z.numer, f.kod, f.wariant, f.sesja
HAVING count(*) > 1;
