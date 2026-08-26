-- =============================================================================
-- 0006 · Podpowiedzi LLM dla ekranu korekty (G2.5.1)
--
-- Reguła twarda całego G2.5: LLM PROPONUJE, człowiek zatwierdza w ekranie
-- korekty. Nic z modelu nie wchodzi do korpusu bez bramki, więc podpowiedź
-- NIE MOŻE lądować w `criterion`/`criterion_condition` — leży obok, we własnej
-- tabeli, i ekran pokazuje ją jako różnicę przy polu, którego dotyczy.
--
-- Wiersz jest jednocześnie ZNACZNIKIEM RAMIENIA pomiaru S6: zadanie
-- z podpowiedzią i zadanie bez niej to dwie próby tego samego eksperymentu,
-- a czas i odsetek zatwierdzeń bez poprawki liczy się z `correction_event`
-- po tym, czy podpowiedź istniała. Bez tej tabeli S6 trzeba by rekonstruować
-- z pamięci, kiedy prefill był włączony.
--
-- Opisy rysunków (S7) NIE mają tu swojego miejsca celowo: dla nich provenance
-- niesie już schemat — `asset.description` plus `asset.description_status`
-- w stanach 'auto' → 'approved'. Druga tabela na to samo byłaby drugim
-- źródłem prawdy.
--
-- BEGIN/COMMIT celowo NIE MA: migrate.py wykonuje każdy plik w jednej
-- transakcji razem z wpisem do schema_migrations.
-- =============================================================================

CREATE TABLE prefill_suggestion (
    id            serial      PRIMARY KEY,
    task_id       integer     NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    -- Model jest PARAMETREM przebiegu, nie stałą w kodzie: różnica jakości
    -- opus vs haiku przy pięciokrotnej różnicy ceny jest częścią pomiaru S6.
    model         text        NOT NULL,
    -- Struktura progi → warunki → zapisy w tym samym kształcie, który produkuje
    -- parser. Trzymana jako jsonb, bo jest PROPOZYCJĄ — nie ma tu więzów
    -- korpusu, bo to jeszcze nie jest korpus.
    payload       jsonb       NOT NULL,
    input_tokens  integer     NOT NULL DEFAULT 0,
    output_tokens integer     NOT NULL DEFAULT 0,
    -- Przebiegi masowe idą przez Batch API (−50% kosztu), więc bez tej flagi
    -- rachunek z tokenów byłby dwa razy za wysoki.
    batch         boolean     NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    -- Jedna podpowiedź na zadanie i model: ponowny przebieg ma nadpisać własny
    -- wynik, a nie mnożyć wiersze, których ekran i tak pokaże tylko jeden.
    UNIQUE (task_id, model)
);

CREATE INDEX prefill_suggestion_task_idx ON prefill_suggestion (task_id);
