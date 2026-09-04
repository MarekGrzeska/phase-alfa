-- Kto rozstrzygnął rekord: człowiek w ekranie korekty czy model (plan A2-auto).
-- Decyzja MVP z 4.09.2026 odwraca „nic z modelu nie wchodzi do korpusu bez
-- bramki" — ale odwracalnie: provenance niesie schemat, więc powrót do korekty
-- ręcznej to `UPDATE task SET review_status = 'pending' WHERE reviewed_by = 'model'`.
-- Widok `corpus_task` zostaje bez zmian: definicja korpusu nie pyta, kto zatwierdził.

ALTER TABLE task
    ADD COLUMN reviewed_by text NOT NULL DEFAULT 'human'
        CHECK (reviewed_by IN ('human', 'model')),
    -- Adres modelu w postaci `dostawca:nazwa`, jak w cenniku `llm.PRICING`;
    -- NULL, gdy rozstrzygał człowiek.
    ADD COLUMN review_model text;

ALTER TABLE correction_event
    ADD COLUMN actor text NOT NULL DEFAULT 'human'
        CHECK (actor IN ('human', 'model')),
    ADD COLUMN model text;

-- `unsure`: model nie rozstrzygnął i zostawił powody w `fields_changed`.
-- Zadanie zostaje `pending`, a ekran korekty pokazuje powody nad formularzem.
ALTER TABLE correction_event DROP CONSTRAINT correction_event_action_check;
ALTER TABLE correction_event
    ADD CONSTRAINT correction_event_action_check
    CHECK (action IN ('approve', 'correct', 'reject', 'reopen', 'unsure'));

CREATE INDEX task_reviewed_by_idx ON task (reviewed_by);
