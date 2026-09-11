-- =============================================================================
-- 0010 · Agent w ekranie korekty — trzeci autor rozstrzygnięć i jego ślad
--
-- Plan: docs/plan-agent-mcp.md (M2). Agent w panelu pisze do korpusu wyłącznie
-- przez `db.save`/`db.decide`, jak człowiek i jak `verify`, więc provenance niesie
-- schemat: `reviewed_by = 'agent'`, `correction_event.actor = 'agent'`. Powrót
-- do stanu sprzed agenta to `UPDATE task SET review_status = 'pending'
-- WHERE reviewed_by = 'agent'` — jak przy modelu w 0009.
--
-- Rozmowy, wywołania narzędzi, potwierdzenia człowieka i przebiegi w tle leżą
-- w bazie, a nie w pamięci przeglądarki: nawigacja w ekranie przeładowuje
-- stronę, a koszt tokenów agenta jest liczbą do raportu, nie do wiary.
--
-- BEGIN/COMMIT celowo NIE MA: migrate.py wykonuje każdy plik w jednej
-- transakcji razem z wpisem do schema_migrations.
-- =============================================================================

ALTER TABLE task DROP CONSTRAINT task_reviewed_by_check;
ALTER TABLE task
    ADD CONSTRAINT task_reviewed_by_check
    CHECK (reviewed_by IN ('human', 'model', 'agent'));

ALTER TABLE correction_event DROP CONSTRAINT correction_event_actor_check;
ALTER TABLE correction_event
    ADD CONSTRAINT correction_event_actor_check
    CHECK (actor IN ('human', 'model', 'agent'));

-- Jedna rozmowa = jeden model: zmiana modelu w panelu zakłada nową sesję,
-- żeby koszt i historia nie mieszały dwóch cenników.
CREATE TABLE agent_session (
    id          serial      PRIMARY KEY,
    -- Adres modelu `dostawca:nazwa`, jak w cenniku llm.PRICING.
    model       text        NOT NULL,
    title       text,
    -- Na co patrzył korektor, gdy zaczynał rozmowę: widok, zadanie, tabela.
    screen      jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE agent_message (
    id             serial      PRIMARY KEY,
    session_id     integer     NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
    role           text        NOT NULL CHECK (role IN ('operator', 'agent', 'system')),
    content        text        NOT NULL,
    -- Wywołania narzędzi w tej turze, w kolejności: nazwa, argumenty, skrót wyniku.
    tool_calls     jsonb,
    input_tokens   integer     NOT NULL DEFAULT 0,
    output_tokens  integer     NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX agent_message_session_idx ON agent_message (session_id);

-- Potwierdzenie człowieka dla narzędzia, które zmienia dane albo kosztuje.
-- Narzędzie bez wpisu z `decision = 'accept'` nie wykonuje niczego — także
-- wtedy, gdy woła je klient z terminala, a nie panel.
CREATE TABLE agent_confirmation (
    id          serial      PRIMARY KEY,
    session_id  integer     REFERENCES agent_session(id) ON DELETE SET NULL,
    tool        text        NOT NULL,
    -- Dokładnie te argumenty, które zostaną wykonane — porównywane przy wykonaniu,
    -- żeby akceptacja jednego zapytania nie przepuściła innego.
    arguments   jsonb       NOT NULL,
    title       text        NOT NULL,
    preview     text,
    cost_usd    numeric(10, 4),
    created_at  timestamptz NOT NULL DEFAULT now(),
    decided_at  timestamptz,
    decision    text        CHECK (decision IS NULL OR decision IN ('accept', 'reject')),
    -- Jednorazowe: wykonane potwierdzenie nie otwiera drugiego wykonania.
    used_at     timestamptz,
    CHECK (decided_at IS NULL OR decided_at >= created_at),
    -- IS NOT DISTINCT FROM, nie `=`: przy `decision IS NULL` zwykłe porównanie daje
    -- NULL, a NULL w CHECK znaczy „przechodzi" — zużycie bez decyzji by się udało.
    CHECK (used_at IS NULL OR decision IS NOT DISTINCT FROM 'accept')
);

CREATE INDEX agent_confirmation_pending_idx ON agent_confirmation (created_at)
    WHERE decision IS NULL;

-- Dziennik wywołań narzędzi, które ZMIENIAJĄ dane (M2); od M4 także odczytów
-- z rozmowy. `session_id` NULL = klient z zewnątrz (Claude Code).
CREATE TABLE agent_tool_call (
    id               serial      PRIMARY KEY,
    session_id       integer     REFERENCES agent_session(id) ON DELETE CASCADE,
    message_id       integer     REFERENCES agent_message(id) ON DELETE SET NULL,
    tool             text        NOT NULL,
    arguments        jsonb,
    result_summary   text,
    is_error         boolean     NOT NULL DEFAULT false,
    confirmation_id  integer     REFERENCES agent_confirmation(id) ON DELETE SET NULL,
    duration_ms      integer,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX agent_tool_call_session_idx ON agent_tool_call (session_id);

-- Przebieg ingestu uruchomiony przez agenta (M3): rejestr w bazie, log w pliku,
-- żeby `--reload` uvicorna nie zgubił procesu, który dalej pracuje.
CREATE TABLE agent_job (
    id           serial      PRIMARY KEY,
    session_id   integer     REFERENCES agent_session(id) ON DELETE SET NULL,
    -- Nazwa zadania z Taskfile (`verify`, `crops`), bez flag.
    task         text        NOT NULL,
    command      text        NOT NULL,
    pid          integer,
    log_path     text        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    exit_code    integer,
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);
