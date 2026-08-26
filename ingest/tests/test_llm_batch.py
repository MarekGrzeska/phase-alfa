"""Przebieg wsadowy (G2.5) — czekanie, które ma koniec.

Wyniki wsadu odbiera się dopiero po jego zakończeniu, więc pętla odpytująca
trzyma całą opłaconą pracę przebiegu.
"""

from __future__ import annotations

import pytest

from correction import llm


class FakeBatch:
    id = "msgbatch_test"


class FakeCounts:
    processing = 3


class FakeStatus:
    def __init__(self, processing_status):
        self.processing_status = processing_status
        self.request_counts = FakeCounts()


class FakeBatches:
    def __init__(self, statuses, results=()):
        self._statuses = list(statuses)
        self._results = list(results)

    def create(self, requests):
        self.sent = requests
        return FakeBatch()

    def retrieve(self, _id):
        state = self._statuses.pop(0) if self._statuses else "in_progress"
        if isinstance(state, Exception):
            raise state
        return FakeStatus(state)

    def results(self, _id):
        return iter(self._results)


class FakeClient:
    def __init__(self, statuses, results=()):
        self.messages = type("M", (), {"batches": FakeBatches(statuses, results)})()


class FakeResult:
    def __init__(self, custom_id, result):
        self.custom_id = custom_id
        self.result = result


def test_results_are_keyed_by_custom_id_not_by_position():
    client = FakeClient(["in_progress", "ended"],
                        [FakeResult("task-2", "b"), FakeResult("task-1", "a")])

    out = llm.run_batch(client, [], "claude-opus-5", poll_seconds=0)

    assert out == {"task-1": "a", "task-2": "b"}


def test_a_stuck_batch_gives_the_console_back():
    client = FakeClient(["in_progress"] * 50)

    with pytest.raises(llm.LlmUnavailable, match="nie skończył się"):
        llm.run_batch(client, [], "claude-opus-5", poll_seconds=0, timeout_seconds=0)


def test_the_deadline_message_carries_the_batch_id():
    """Wsad liczy się dalej po stronie API — bez identyfikatora nie ma po co
    tam wracać."""
    client = FakeClient(["in_progress"])

    with pytest.raises(llm.LlmUnavailable, match="msgbatch_test"):
        llm.run_batch(client, [], "claude-opus-5", poll_seconds=0, timeout_seconds=0)


def test_a_network_hiccup_does_not_abandon_a_paid_batch():
    client = FakeClient([ConnectionError("zerwane"), "in_progress",
                         ConnectionError("zerwane"), "ended"],
                        [FakeResult("task-1", "a")])

    out = llm.run_batch(client, [], "claude-opus-5", poll_seconds=0)

    assert out == {"task-1": "a"}


def test_a_run_of_failures_ends_with_an_error_not_a_loop():
    client = FakeClient([ConnectionError("zerwane")] * (llm.MAX_BATCH_STUMBLES + 1))

    with pytest.raises(llm.LlmUnavailable, match="nie udało się zapytać o stan"):
        llm.run_batch(client, [], "claude-opus-5", poll_seconds=0)
