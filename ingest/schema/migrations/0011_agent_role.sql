-- =============================================================================
-- 0011 · Rola bazy dla agenta — odczyt bez uprawnień superusera
--
-- Przegląd kodu z 11.09.2026 (docs/review/2026-09-11-feat-agent-m1.html, komentarze
-- 1 i 4) pokazał, że narzędzie `db_query` — opisane modelowi jako „tylko do odczytu"
-- i oznaczone `readOnlyHint` — pozwalało na więcej, niż obiecywało. Transakcja
-- READ ONLY zatrzymuje zapis DO BAZY, ale nie zatrzymuje konstrukcji, które zapisem
-- nie są: `COPY … TO PROGRAM` uruchamia program, a `pg_read_file()` czyta dysk
-- serwera. Oba przechodziły, bo rola `klucz` jest superuserem — tak zakłada ją
-- obraz Postgresa z `docker-compose.yml`.
--
-- Dowód z przeglądu: przez `db_query` powstał plik w `/tmp` kontenera bazy.
--
-- Naprawa jest po stronie UPRAWNIEŃ, nie po stronie listy zakazanych słów w SQL-u.
-- Lista zakazów zawsze jest niepełna i za rok nikt nie będzie pamiętał, czego
-- w niej brakuje; rola bez `SUPERUSER` odmawia sama, także konstrukcjom, których
-- dziś nie znamy.
--
-- Dlaczego osobne połączenie, a nie `SET LOCAL ROLE` na połączeniu `klucz`:
-- `klucz` jest superuserem, więc `RESET ROLE` w treści zapytania wróciłby do
-- pełnych uprawnień. Rola z własnym logowaniem nie ma tej drogi — nie jest
-- członkiem `klucz`, więc `SET ROLE klucz` odmawia.
--
-- Hasło stoi tu jawnie i to jest ta sama decyzja co `klucz_dev`
-- w `docker-compose.yml`: baza jest deweloperska, słucha na 127.0.0.1, a hasło
-- nie jest sekretem, tylko wartością konfiguracji. Wdrożenie poza localhost
-- nadpisuje je zmienną `AGENT_DB_PASSWORD` albo całym `AGENT_DATABASE_URL`.
--
-- BEGIN/COMMIT celowo NIE MA: migrate.py wykonuje każdy plik w jednej
-- transakcji razem z wpisem do schema_migrations.
-- =============================================================================

-- Role w PostgreSQL są wspólne dla całego klastra, a nie dla jednej bazy — więc
-- druga baza (każdy moduł testów stawia własną `klucz_test_*`) zastałaby rolę
-- już istniejącą i migracja by pękła. Stąd warunek, nie samo CREATE ROLE.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'klucz_agent') THEN
        CREATE ROLE klucz_agent LOGIN PASSWORD 'klucz_agent_dev'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;

-- Limit czasu zapytania siedzi na ROLI, a nie w treści transakcji. `SET LOCAL
-- statement_timeout` na początku zapytania dawało się zdjąć, bo model mógł
-- przysłać `SET statement_timeout = 0; SELECT …` w jednym poleceniu (komentarz 4).
-- Ustawienie roli obowiązuje od nowego połączenia i zapytanie go nie podniesie.
ALTER ROLE klucz_agent SET statement_timeout = '15s';
ALTER ROLE klucz_agent SET idle_in_transaction_session_timeout = '30s';

-- Nazwa bazy wstawiana dynamicznie, bo migracja chodzi też na bazach testowych
-- (`klucz_test_*`) — `GRANT … ON DATABASE` nie przyjmuje wyrażenia, tylko nazwę.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO klucz_agent', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO klucz_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO klucz_agent;

-- Tabela dołożona PÓŹNIEJSZĄ migracją ma być widoczna dla agenta bez dopisywania
-- tu kolejnego GRANT-a. Bez tego pierwsza nowa tabela byłaby dla `db_query`
-- niewidoczna, a komunikat mówiłby „permission denied" zamiast czegokolwiek
-- sensownego.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO klucz_agent;

-- Czego rola NIE dostaje i to jest treść tej migracji: żadnego INSERT, UPDATE,
-- DELETE ani TRUNCATE (zapis do korpusu idzie przez `db.save`/`db.decide` na
-- połączeniu `klucz`), żadnego CREATE (brak tabel tymczasowych), i żadnego
-- SUPERUSER (brak `COPY … TO PROGRAM`, `pg_read_file`, `lo_import`).
