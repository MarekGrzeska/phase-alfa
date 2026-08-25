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
--   task_version.task_id            → UNIQUE (task_id, exam_form_id)
--   model_answer.task_version_id    → UNIQUE (task_version_id, part)
--   criterion.task_id               → UNIQUE (task_id, points)
--   exam_form_document.exam_form_id → PRIMARY KEY (exam_form_id, ...)
--   task_requirement.task_id        → PRIMARY KEY (task_id, ...)
-- =============================================================================

CREATE INDEX requirement_regime_idx           ON requirement (regime_id);
CREATE INDEX requirement_parent_idx           ON requirement (parent_id);

CREATE INDEX exam_form_regime_idx             ON exam_form (regime_id);
CREATE INDEX exam_form_document_document_idx  ON exam_form_document (document_id);

CREATE INDEX task_marking_scheme_idx          ON task (marking_scheme_id);
CREATE INDEX task_requirement_requirement_idx ON task_requirement (requirement_id);

CREATE INDEX task_version_exam_form_idx       ON task_version (exam_form_id);
CREATE INDEX task_version_paper_idx           ON task_version (paper_id);

CREATE INDEX criterion_condition_criterion_idx ON criterion_condition (criterion_id);
CREATE INDEX condition_expression_condition_idx ON condition_expression (condition_id);

CREATE INDEX example_solution_task_idx        ON example_solution (task_id);
CREATE INDEX answer_example_task_idx          ON answer_example (task_id);

CREATE INDEX rule_marking_scheme_idx          ON rule (marking_scheme_id);
CREATE INDEX asset_task_version_idx           ON asset (task_version_id);

-- Raport pokrycia w ingest.py filtruje dokumenty po statusie — a od A2
-- ekran korekty będzie to robił przy każdym odświeżeniu widoku.
CREATE INDEX document_ingest_status_idx       ON document (ingest_status);
