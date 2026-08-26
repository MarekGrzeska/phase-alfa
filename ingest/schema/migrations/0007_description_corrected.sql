-- =============================================================================
-- 0007 · `corrected` w statusie opisu rysunku (G2.5.2, pomiar S7)
--
-- S7 z Planu Alfy brzmi: „odsetek opisów zatwierdzonych BEZ POPRAWKI". Stany
-- 'none' → 'auto' → 'approved' z migracji 0001 tego nie mierzą — 'approved'
-- znaczy tylko „człowiek to widział", więc opis przyjęty w całości i opis
-- przepisany od nowa wyglądają w bazie identycznie.
--
-- To ten sam argument, który w 0004 rozdzielił `approved` i `corrected`
-- na zadaniu: różnica między „model trafił sam" a „człowiek poprawił" jest
-- WYNIKIEM badawczym alfy i liczbą do wniosku, więc ma wychodzić jednym
-- GROUP BY, a nie rekonstrukcją z dziennika.
--
-- BEGIN/COMMIT celowo NIE MA: migrate.py wykonuje każdy plik w jednej
-- transakcji razem z wpisem do schema_migrations.
-- =============================================================================

ALTER TABLE asset DROP CONSTRAINT asset_description_status_check;

ALTER TABLE asset
    ADD CONSTRAINT asset_description_status_check
    CHECK (description_status IN ('none', 'auto', 'approved', 'corrected'));
