-- =============================================================================
-- 0004 · Bramka korekty — status per zadanie, dziennik pracy, widok korpusu
--
-- G2.1.1. Parser produkuje KANDYDATÓW, nie korpus. Do korpusu wchodzi wyłącznie
-- to, co człowiek rozstrzygnął w ekranie korekty — i to jest cała definicja
-- „zrobione" dla ingestu z DECYZJE.md („najpierw ekran korekty, potem parser").
--
-- Status wisi na ZADANIU, bo zadanie jest jednostką pracy w ekranie: człowiek
-- ogląda je z kompletem kryteriów, warunków, zapisów i obu wersji naraz
-- i rozstrzyga całość. Statusy drobniejsze już istnieją i zostają —
-- `task_version.content_status` (treść z arkusza) oraz `asset.description_status`
-- (alt-text) — bo domykają się w innym czasie i innym nakładem niż kryteria.
--
-- BEGIN/COMMIT celowo NIE MA: migrate.py wykonuje każdy plik w jednej
-- transakcji razem z wpisem do schema_migrations.
-- =============================================================================

-- `approved` i `corrected` to DWA stany, nie jeden z flagą, bo różnica między
-- nimi jest wynikiem badawczym alfy: odsetek zadań, które parser trafił sam,
-- to pomiar S6/S8 i liczba do wniosku grantowego. Trzymany jako osobny status
-- wychodzi jednym `GROUP BY`; upchnięty w jedną „zrobione" wymagałby
-- rekonstrukcji z dziennika, czyli zgadywania.
ALTER TABLE task
    ADD COLUMN review_status text NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'approved', 'corrected', 'rejected')),
    ADD COLUMN reviewed_at timestamptz,
    -- Strona w KLUCZU. `task_version.page` mówi o czym innym: gdy ingest
    -- doczytał zeszyty zadań (`--z-arkuszami`), trzyma stronę w ARKUSZU,
    -- a numer strony klucza nie stoi wtedy nigdzie. Ekran korekty renderuje
    -- właśnie tę stronę, bo sprawdza kryteria przeciwko dokumentowi,
    -- z którego zostały wyjęte.
    ADD COLUMN page smallint;

-- Uzupełnienie dla korpusu już załadowanego: gdy wersje zadania nie mają
-- arkusza, ich `page` NADAL wskazuje klucz — to ta sama liczba, tyle że
-- zapisana przed powstaniem tej kolumny. Klucze wczytane z arkuszami zostają
-- z NULL-em i domagają się przeładowania; ekran korekty mówi to wprost,
-- zamiast pokazywać przypadkową stronę.
UPDATE task t
   SET page = src.page
  FROM (SELECT task_id, min(page) AS page
          FROM task_version
         WHERE paper_id IS NULL AND page IS NOT NULL
         GROUP BY task_id) src
 WHERE src.task_id = t.id;

-- Dziennik korekty — surowiec dla S8 (czas pracy, rodzaj rozstrzygnięcia).
-- Czas liczy się z dziennika, a nie z licznika w kolumnie: licznik nadpisany
-- traci historię, dziennik nie.
CREATE TABLE correction_event (
    id             serial      PRIMARY KEY,
    -- SET NULL, nie CASCADE: ponowny ingest z `--overwrite-reviewed` kasuje
    -- zadania klucza, ale pomiar „ile kosztował półautomat" jest WYNIKIEM alfy
    -- i ma przeżyć przeładowanie korpusu. Wiersz bez zadania wciąż niesie czas
    -- i rodzaj decyzji, czyli wszystko, czego S8 potrzebuje.
    task_id        integer     REFERENCES task(id) ON DELETE SET NULL,
    action         text        NOT NULL CHECK (action IN
                     ('approve', 'correct', 'reject', 'reopen')),
    started_at     timestamptz NOT NULL,
    finished_at    timestamptz NOT NULL DEFAULT now(),
    -- {"edited": {"criterion": 2}, "deleted": {"condition_expression": 1}}
    fields_changed jsonb,
    -- Odwrócony przedział to zegar albo formularz sprzed doby, nie praca.
    -- Więz jest tani, a mediana liczona z ujemnych czasów kłamie po cichu.
    CHECK (finished_at >= started_at)
);

CREATE INDEX correction_event_task_idx ON correction_event (task_id);

-- Ekran wchodzi zawsze od strony „co jest do zrobienia", więc filtr po statusie
-- jest jedynym zapytaniem, które chodzi po całym korpusie przy każdym otwarciu.
CREATE INDEX task_review_status_idx ON task (review_status);

-- Kontrakt dla konsumentów korpusu — C# w W2.1 i pipeline w A3 czytają STĄD,
-- nigdy wprost z `task`. Dzięki temu definicja „co jest korpusem" stoi
-- w jednym miejscu schematu, zamiast być powtórzona w kodzie trzech warstw.
--
-- Kolumny wypisane jawnie, bo `SELECT *` w widoku zamraża listę kolumn z chwili
-- CREATE: kolumna dołożona do `task` późniejszą migracją nie pojawiłaby się
-- tutaj nigdy, a widok wyglądałby na aktualny.
CREATE VIEW corpus_task AS
SELECT id,
       marking_scheme_id,
       number,
       position,
       max_points,
       kind,
       page,
       review_status,
       reviewed_at
FROM task
WHERE review_status IN ('approved', 'corrected');
