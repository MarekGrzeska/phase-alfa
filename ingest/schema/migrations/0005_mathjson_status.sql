-- =============================================================================
-- 0005 · Status konwersji MathJSON per zapis równoważny
--
-- G2.6. Kolumna `condition_expression.mathjson` istnieje od 0001 i stoi pusta.
-- Bez niej Compute Engine w A3 (G3.1.3, EvaluateClosed) porównuje STRINGI,
-- więc `2(x+1)` i `2x+2` są dla niego dwoma różnymi odpowiedziami — a to jest
-- dokładnie ta równoważność, dla której zapisy równoważne w kluczu istnieją.
--
-- Sama kolumna nie wystarczy, bo NULL nie odróżnia trzech różnych rzeczy:
-- „jeszcze nie próbowano", „konwerter nie ugryzł" i „człowiek to sprawdził".
-- `failed` jest stanem JAWNYM po to, żeby zapis, którego konwerter nie
-- przerobił, był w ekranie korekty widoczny jako robota do zrobienia,
-- a nie znikał w tle jako pusta komórka.
--
-- BEGIN/COMMIT celowo NIE MA: migrate.py wykonuje każdy plik w jednej
-- transakcji razem z wpisem do schema_migrations.
-- =============================================================================

ALTER TABLE condition_expression
    ADD COLUMN mathjson_status text NOT NULL DEFAULT 'none'
        CHECK (mathjson_status IN ('none', 'auto', 'approved', 'failed')),
    -- Powód odmowy po polsku, prosto do ekranu korekty. Bez niego `failed`
    -- mówi „nie da się", a człowiek i tak musi odtworzyć, czego konwerter
    -- nie zrozumiał — czyli zrobić diagnozę drugi raz.
    ADD COLUMN mathjson_error text;

-- Ekran korekty i raport domknięcia pytają o to samo: co jeszcze nie ma
-- MathJSON-a. Przy 514 zapisach indeks jest tani, a przy K6 (matura) już nie
-- będzie oczywisty.
CREATE INDEX condition_expression_mathjson_status_idx
    ON condition_expression (mathjson_status);
