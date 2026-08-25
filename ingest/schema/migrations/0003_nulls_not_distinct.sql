-- =============================================================================
-- 0003 · NULL ma być traktowany jako wartość w więzach słownikowych
--
-- W PostgreSQL domyślnie NULL <> NULL, więc UNIQUE go NIE pilnuje: dwa wiersze
-- z tą samą trójką i NULL-em na czwartej pozycji przechodzą oba. Dotyczy to
-- dwóch tabel, w których NULL jest normalną, częstą wartością:
--
--   requirement.stage    NULL dla wymagań ogólnych (nie mają etapu edukacyjnego)
--   exam_form.version    NULL dla form bez bliźniaka X/Y
--
-- Zmierzone przed naprawą: dwa identyczne wymagania ogólne wchodzą do bazy
-- bez protestu.
--
-- W sondzie problem był niewidoczny, bo ładowarka trzymała słownik reżimów,
-- wymagań i form w pamięci procesu i sama nie dopuszczała powtórzeń. To
-- działa dokładnie tak długo, jak długo trwa jeden przebieg — przy drugim
-- ingeście na tej samej bazie korpus zaczyna się dublować, a mapa braków
-- sumuje po ścieżce podstawy i cicho podwaja liczby.
--
-- NULLS NOT DISTINCT jest w PostgreSQL od wersji 15. Po tej zmianie
-- ładowarka może polegać na ON CONFLICT zamiast na własnej pamięci.
-- =============================================================================

ALTER TABLE requirement
    DROP CONSTRAINT requirement_regime_id_kind_stage_path_key;
ALTER TABLE requirement
    ADD CONSTRAINT requirement_regime_id_kind_stage_path_key
    UNIQUE NULLS NOT DISTINCT (regime_id, kind, stage, path);

ALTER TABLE exam_form
    DROP CONSTRAINT exam_form_code_variant_version_session_key;
ALTER TABLE exam_form
    ADD CONSTRAINT exam_form_code_variant_version_session_key
    UNIQUE NULLS NOT DISTINCT (code, variant, version, session);

-- `model_answer.part` bywa NULL przy zadaniach jednoczęściowych — ten sam
-- problem, ta sama naprawa.
ALTER TABLE model_answer
    DROP CONSTRAINT model_answer_task_version_id_part_key;
ALTER TABLE model_answer
    ADD CONSTRAINT model_answer_task_version_id_part_key
    UNIQUE NULLS NOT DISTINCT (task_version_id, part);
