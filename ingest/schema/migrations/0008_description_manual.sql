-- =============================================================================
-- 0008 · `manual` w statusie opisu rysunku (G2.5.2, pomiar S7)
--
-- 0007 rozdzielił „model trafił sam" (`approved`) od „człowiek poprawił"
-- (`corrected`). To wystarcza, dopóki opis ZAWSZE zaczyna się od modelu — a nie
-- zaczyna: w ekranie korekty da się opisać zasób, którego `task describe` nigdy
-- nie tknął. Bez osobnego stanu taki opis wchodził do MIANOWNIKA S7 i obniżał
-- „odsetek opisów modelu przyjętych bez poprawki" za pracę, o którą pomiar nie
-- pyta. `manual` stoi poza S7 tak samo, jak `rejected` stoi poza S8 (0004).
--
-- Wierszy nie ruszamy: `corrected` sprzed tej migracji mogło znaczyć jedno albo
-- drugie i nie ma z czego tego odtworzyć.
--
-- BEGIN/COMMIT celowo NIE MA: migrate.py wykonuje każdy plik w jednej
-- transakcji razem z wpisem do schema_migrations.
-- =============================================================================

ALTER TABLE asset DROP CONSTRAINT asset_description_status_check;

ALTER TABLE asset
    ADD CONSTRAINT asset_description_status_check
    CHECK (description_status IN ('none', 'auto', 'approved', 'corrected', 'manual'));
