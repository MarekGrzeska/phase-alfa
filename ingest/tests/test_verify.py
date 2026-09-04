"""Drugi czytelnik (`correction.verify`, plan A2-auto) — rekord ↔ formularz i zapis.

Wywołań LLM nie ma w CI: sprawdza się schemat wysyłany do API, tłumaczenie
werdyktu na formularz i to, że zapis idzie przez tę samą bramkę co człowiek —
więz bazy odrzuca rekord modelu, a zadanie ląduje w `unsure`, nie w korpusie.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

from correction import db, verify  # noqa: E402

pytestmark = pytest.mark.integracyjny

MODEL = "openai:gpt-5.6-luna"


# ── część czysta ───────────────────────────────────────────────────────────

def _task_dict() -> dict:
    return {
        "id": 1, "number": "20", "max_points": 3, "kind": "open_short",
        "code": "OMAP-100", "session": "2025-05-14", "year": 2025,
        "page": 3, "document_pages": 4, "document_path": "x.pdf",
        "versions": [{"id": 5, "content": "treść", "answers": [
            {"id": 7, "answer": "105"}, {"id": 8, "answer": "106"}]}],
        "criteria": [
            {"id": 9, "points": 3, "label": "pełne", "description": None,
             "conditions": [{"id": 11, "description": "metoda",
                             "expressions": [{"id": 13, "expression": "P=15"},
                                             {"id": 14, "expression": "P = 15"}]}]},
            {"id": 10, "points": 1, "label": None, "description": "częściowe",
             "conditions": []},
        ],
        "requirements": [],
    }


def test_schema_is_strict_in_every_object():
    schema = verify.strict_schema(verify.Verdict)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"verdict", "reasons", "record"}
    for name, obj in schema["$defs"].items():
        assert obj["additionalProperties"] is False, name
        assert set(obj["required"]) == set(obj["properties"]), name


def test_record_keeps_ids_and_round_trips_to_form():
    task = _task_dict()
    record = verify.record_of(task)
    assert [c.id for c in record.criteria] == [9, 10]
    form = verify.form_for(task, record)
    assert form["criterion.9.points"] == "3"
    assert form["expression.14.expression"] == "P = 15"
    assert form["answer.8.answer"] == "106"
    assert not [k for k in form if k.startswith("delete.")]


def test_rows_missing_from_record_are_marked_for_deletion():
    task = _task_dict()
    record = verify.record_of(task)
    record.criteria = record.criteria[:1]                     # próg 1 pkt znika
    record.criteria[0].conditions[0].expressions.pop()        # zapis 14 znika
    record.versions[0].answers.pop()                          # odpowiedź 8 znika
    form = verify.form_for(task, record)
    assert form["delete.criterion.10"] == "1"
    assert form["delete.expression.14"] == "1"
    assert form["delete.answer.8"] == "1"
    assert "criterion.10.points" not in form


def test_form_refuses_rows_without_ids():
    task = _task_dict()
    record = verify.record_of(task)
    record.criteria.append(verify.CriterionRow(id=None, points=2, label=None,
                                               description=None, conditions=[]))
    with pytest.raises(ValueError, match="create_missing"):
        verify.form_for(task, record)


def test_key_pages_run_to_the_next_task_with_a_cap():
    assert verify.key_pages({"page": 3, "document_pages": 4}) == [3, 4]
    assert verify.key_pages({"page": 4, "document_pages": 4}) == [4]
    assert verify.key_pages({"page": None, "document_pages": 4}) == []
    # Zadanie 20 z 2025 r.: strony 20–25, następne zadanie zaczyna się na 25.
    assert verify.key_pages({"page": 20, "document_pages": 26, "page_to": 25}) == [
        20, 21, 22, 23, 24]
    assert verify.key_pages({"page": 20, "document_pages": 26, "page_to": 21}) == [20, 21]


# ── zapis przez bramkę ─────────────────────────────────────────────────────

@pytest.fixture
def con(fresh_database):
    with psycopg.connect(fresh_database, autocommit=True, row_factory=dict_row) as c:
        yield c


@pytest.fixture
def task_id(con) -> int:
    """Zadanie otwarte z jednym progiem 3 pkt: warunek i zapis równoważny."""
    with con.cursor() as cur:
        cur.execute("TRUNCATE document, task, exam_form, correction_event "
                    "RESTART IDENTITY CASCADE")
        cur.execute(
            "INSERT INTO document (segment, year, code, variants, session, kind, "
            "kind_source, url, path, pages) VALUES ('e8', 2025, 'OMAP', '100', "
            "'2025-05-14', 'marking_scheme', 'suffix', 'test://verify', 'test.pdf', 4) "
            "RETURNING id")
        document = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, page) "
            "VALUES (%s, '20', 20, 3, 'open_short', 3) RETURNING id", (document,))
        task = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO criterion (task_id, points, label, position) "
            "VALUES (%s, 3, 'pełne rozwiązanie', 1) RETURNING id", (task,))
        criterion = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO criterion_condition (criterion_id, description, position) "
            "VALUES (%s, 'poprawny sposób obliczenia pola', 1) RETURNING id", (criterion,))
        condition = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO condition_expression (condition_id, expression, position) "
            "VALUES (%s, 'P = 15² − 3', 1)", (condition,))
    return task


def _started() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=30)


def _state(con, task_id: int) -> dict:
    return con.execute(
        "SELECT review_status, reviewed_by, review_model FROM task WHERE id = %s",
        (task_id,)).fetchone()


def _events(con) -> list[dict]:
    return con.execute(
        "SELECT action, actor, model, fields_changed FROM correction_event ORDER BY id"
    ).fetchall()


def _loaded(con, task_id: int) -> dict:
    with con.cursor() as cur:
        return db.load_task(cur, task_id)


def test_match_approves_as_model(con, task_id):
    verdict = verify.Verdict(verdict="match", reasons=[], record=None)
    assert verify.apply_verdict(con, task_id, verdict, MODEL, _started()) == "approved"
    assert _state(con, task_id) == {"review_status": "approved",
                                    "reviewed_by": "model", "review_model": MODEL}
    events = _events(con)
    assert [(e["action"], e["actor"], e["model"]) for e in events] == [
        ("approve", "model", MODEL)]


def test_fix_goes_through_save_and_is_corrected(con, task_id):
    record = verify.record_of(_loaded(con, task_id))
    record.criteria[0].label = "pełne rozwiązanie z wynikiem"
    record.criteria[0].conditions.append(verify.ConditionRow(
        id=None, description="poprawna metoda i wynik 222", expressions=[]))
    verdict = verify.Verdict(verdict="fix", reasons=["brakowało drugiego warunku"],
                             record=record)

    assert verify.apply_verdict(con, task_id, verdict, MODEL, _started()) == "corrected"
    assert _state(con, task_id)["reviewed_by"] == "model"
    assert [e["action"] for e in _events(con)] == ["correct"]
    conditions = _loaded(con, task_id)["criteria"][0]["conditions"]
    assert [c["description"] for c in conditions] == [
        "poprawny sposób obliczenia pola", "poprawna metoda i wynik 222"]


def test_fix_rejected_by_constraint_lands_in_unsure(con, task_id):
    """UNIQUE (task_id, points): drugi próg 3 pkt nie wchodzi — ani od człowieka,
    ani od modelu. Zadanie zostaje `pending`, powód w dzienniku."""
    record = verify.record_of(_loaded(con, task_id))
    record.criteria.append(verify.CriterionRow(
        id=None, points=3, label="dublet", description=None, conditions=[]))
    verdict = verify.Verdict(verdict="fix", reasons=["klucz ma dwa progi"], record=record)

    assert verify.apply_verdict(con, task_id, verdict, MODEL, _started()) == "unsure"
    assert _state(con, task_id)["review_status"] == "pending"
    events = _events(con)
    assert [(e["action"], e["actor"]) for e in events] == [("unsure", "model")]
    reasons = events[0]["fields_changed"]["reasons"]
    assert reasons[0] == verify.UNSURE_ON_DB
    assert "klucz ma dwa progi" in reasons
    # Transakcja cofnięta: dubletu nie ma, oryginał nietknięty.
    assert [c["points"] for c in _loaded(con, task_id)["criteria"]] == [3]

    with con.cursor() as cur:
        notes = db.model_notes(cur, task_id)
        assert notes["model"] == MODEL and notes["reasons"] == reasons
        # Bez `--retry-unsure` ten model nie dostaje zadania drugi raz.
        assert verify.collect_tasks(cur, 2025, "100", MODEL, 10, retry=False) == []
        assert [t["id"] for t in verify.collect_tasks(cur, 2025, "100", MODEL, 10,
                                                      retry=True)] == [task_id]


def test_unsure_verdict_keeps_task_pending(con, task_id):
    verdict = verify.Verdict(verdict="unsure", reasons=["strona nie pokazuje zadania 20"],
                             record=None)
    assert verify.apply_verdict(con, task_id, verdict, MODEL, _started()) == "unsure"
    assert _state(con, task_id)["review_status"] == "pending"


def test_reopen_drops_model_authorship(con, task_id):
    verify.apply_verdict(con, task_id, verify.Verdict(verdict="match", reasons=[],
                                                      record=None), MODEL, _started())
    with con.transaction(), con.cursor() as cur:
        db.decide(cur, task_id, "reopen", _started(),
                  {"edited": {}, "deleted": {}, "described": {}})
    assert _state(con, task_id) == {"review_status": "pending",
                                    "reviewed_by": "human", "review_model": None}


# ── przebieg z podstawionym modelem ────────────────────────────────────────

class _Raw:
    def __init__(self):
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 20}
        self.response_metadata = {"finish_reason": "stop"}


class _FakeStructured:
    """`with_structured_output(..., include_raw=True)`: kolejne odpowiedzi albo wyjątki."""

    def __init__(self, replies):
        self._replies = list(replies)

    def invoke(self, _messages):
        answer = self._replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"raw": _Raw(), "parsed": answer, "parsing_error": None}


class _FakeChat:
    def __init__(self, replies):
        self.replies = replies

    def with_structured_output(self, *_args, **_kwargs):
        return _FakeStructured(self.replies)


def test_run_applies_each_verdict_before_asking_for_the_next(con, task_id, monkeypatch):
    """Zapis po zadaniu, nie po przebiegu: awaria na drugim zadaniu nie ma
    prawa skasować rozstrzygnięcia pierwszego, które już jest opłacone."""
    with con.cursor() as cur:
        cur.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, "
                    "kind, page) SELECT marking_scheme_id, '22', 22, 1, 'closed', 4 "
                    "FROM task WHERE id = %s", (task_id,))
    replies = [verify.Verdict(verdict="match", reasons=[], record=None),
               RuntimeError("API padło")]
    monkeypatch.setattr(verify.llm, "chat_model", lambda *a, **k: _FakeChat(replies))
    monkeypatch.setattr(verify, "messages_for", lambda task: [])

    spend, outcome = verify.run(con, 2025, "100", MODEL, limit=10, apply=True)

    assert [r["state"] for r in outcome.rows] == ["approved", "failed"]
    assert _state(con, task_id)["review_status"] == "approved"
    assert spend.calls == 1 and len(spend.failures) == 1
    assert "API padło" in spend.failures[0][1]
