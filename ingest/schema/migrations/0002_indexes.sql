-- =============================================================================
-- 0002 · Indeksy na kluczach obcych
--
-- PostgreSQL zakłada indeks na kluczu GŁÓWNYM i na UNIQUE, ale NIE na kluczu
-- obcym. Bez tych indeksów każdy DELETE na rodzicu (a mamy sporo
-- ON DELETE CASCADE) robi skan sekwencyjny dziecka — przy 1436 zadaniach
-- to niewidoczne, przy pełnym korpusie już nie.
--
-- Pominięte celowo: kolumny FK, które są PIERWSZE w istniejącym UNIQUE albo
-- w kluczu głównym — tam indeks już jest i drugi byłby kosztem bez zysku.
--   zadanie_wersja.zadanie_id     → UNIQUE (zadanie_id, forma_id)
--   odpowiedz_wzorcowa.wersja_id  → UNIQUE (wersja_id, podpunkt)
--   kryterium.zadanie_id          → UNIQUE (zadanie_id, punkty)
--   forma_dokument.forma_id       → PRIMARY KEY (forma_id, ...)
--   zadanie_wymaganie.zadanie_id  → PRIMARY KEY (zadanie_id, ...)
-- =============================================================================

CREATE INDEX wymaganie_rezim_idx            ON wymaganie (rezim_id);
CREATE INDEX wymaganie_parent_idx           ON wymaganie (parent_id);

CREATE INDEX forma_rezim_idx                ON forma (rezim_id);
CREATE INDEX forma_dokument_dokument_idx    ON forma_dokument (dokument_id);

CREATE INDEX zadanie_klucz_idx              ON zadanie (klucz_id);
CREATE INDEX zadanie_wymaganie_wymaganie_idx ON zadanie_wymaganie (wymaganie_id);

CREATE INDEX zadanie_wersja_forma_idx       ON zadanie_wersja (forma_id);
CREATE INDEX zadanie_wersja_arkusz_idx      ON zadanie_wersja (arkusz_id);

CREATE INDEX kryterium_warunek_kryterium_idx ON kryterium_warunek (kryterium_id);
CREATE INDEX warunek_zapis_warunek_idx      ON warunek_zapis (warunek_id);

CREATE INDEX rozwiazanie_zadanie_idx        ON rozwiazanie_przykladowe (zadanie_id);
CREATE INDEX przyklad_odpowiedzi_zadanie_idx ON przyklad_odpowiedzi (zadanie_id);

CREATE INDEX regula_klucz_idx               ON regula (klucz_id);
CREATE INDEX zasob_wersja_idx               ON zasob (wersja_id);

-- Raport pokrycia w ingest.py filtruje dokumenty po statusie — a od A2
-- ekran korekty będzie to robił przy każdym odświeżeniu widoku.
CREATE INDEX dokument_ingest_status_idx     ON dokument (ingest_status);
