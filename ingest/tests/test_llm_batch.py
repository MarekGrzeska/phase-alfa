"""Przebieg wsadowy (G2.5) — czekanie, które ma koniec.

Wyniki wsadu odbiera się dopiero po jego zakończeniu, więc pętla odpytująca
trzyma całą opłaconą pracę przebiegu.

Wsad jest JEDYNYM miejscem, które schodzi poniżej LangChaina: `.batch()`
to zrównoleglenie po stronie klienta i pełna cena, a −50% daje osobny endpoint
dostawcy. Stąd te testy pracują na surowym kształcie API, a nie na LangChainie.
"""

from __future__ import annotations

import json

import pytest

from correction import llm


def line(custom_id: str, content: str) -> str:
    return json.dumps({"custom_id": custom_id,
                       "response": {"status_code": 200,
                                    "body": {"choices": [
                                        {"message": {"content": content}}]}},
                       "error": None})


class FakeBatch:
    id = "batch_test"


class FakeContent:
    def __init__(self, text):
        self.text = text


class FakeUpload:
    id = "file_in"


class FakeFiles:
    def __init__(self, contents):
        self._contents = contents
        self.uploaded = None

    def create(self, file, purpose):
        self.uploaded = file
        self.purpose = purpose
        return FakeUpload()

    def content(self, file_id):
        return FakeContent(self._contents.get(file_id, ""))


class FakeCounts:
    total = 3
    completed = 0
    failed = 0


class FakeStatus:
    def __init__(self, status, output_file_id, error_file_id):
        self.status = status
        self.request_counts = FakeCounts()
        self.output_file_id = output_file_id
        self.error_file_id = error_file_id


class FakeBatches:
    def __init__(self, statuses, output_file_id, error_file_id):
        self._statuses = list(statuses)
        self._output_file_id = output_file_id
        self._error_file_id = error_file_id
        self.created = None

    def create(self, input_file_id, endpoint, completion_window):
        self.created = {"input_file_id": input_file_id, "endpoint": endpoint,
                        "completion_window": completion_window}
        return FakeBatch()

    def retrieve(self, _id):
        state = self._statuses.pop(0) if self._statuses else "in_progress"
        if isinstance(state, Exception):
            raise state
        return FakeStatus(state, self._output_file_id, self._error_file_id)


class FakeClient:
    def __init__(self, statuses, contents=None, output_file_id=None,
                 error_file_id=None):
        self.files = FakeFiles(contents or {})
        self.batches = FakeBatches(statuses, output_file_id, error_file_id)


def test_results_are_keyed_by_custom_id_not_by_position():
    client = FakeClient(["in_progress", "completed"],
                        contents={"file_out": f"{line('task-2', 'b')}\n"
                                              f"{line('task-1', 'a')}"},
                        output_file_id="file_out")

    out = llm.run_batch([], client=client, poll_seconds=0)

    assert sorted(out) == ["task-1", "task-2"]
    body, why = llm.batch_payload(out["task-1"])
    assert not why
    assert body["choices"][0]["message"]["content"] == "a"


def test_requests_go_up_as_one_jsonl_file():
    """Wsad u OpenAI jest PLIKOWY: lista requestów to wiersze JSONL, a nie
    argument wywołania. Zgubiony `custom_id` znaczy tu wynik bez adresata."""
    client = FakeClient(["completed"], contents={"file_out": ""},
                        output_file_id="file_out")
    requests = [llm.batch_request("task-1", {"model": "gpt-5"}),
                llm.batch_request("task-2", {"model": "gpt-5"})]

    llm.run_batch(requests, client=client, poll_seconds=0)

    _, payload, _ = client.files.uploaded
    rows = [json.loads(row) for row in payload.getvalue().decode().splitlines()]
    assert [r["custom_id"] for r in rows] == ["task-1", "task-2"]
    assert rows[0]["url"] == llm.BATCH_ENDPOINT
    assert client.batches.created["input_file_id"] == "file_in"


def test_failed_rows_come_back_with_a_reason():
    """Wiersze z pliku błędów wracają tą samą drogą co udane — inaczej
    o niepowodzeniu wiadomo tylko tyle, że zadania nie ma."""
    broken = json.dumps({"custom_id": "task-9",
                         "error": {"message": "za długie żądanie"}})
    client = FakeClient(["completed"], contents={"file_err": broken},
                        output_file_id=None, error_file_id="file_err")

    out = llm.run_batch([], client=client, poll_seconds=0)
    body, why = llm.batch_payload(out["task-9"])

    assert body is None
    assert "za długie żądanie" in why


def test_a_stuck_batch_gives_the_console_back():
    client = FakeClient(["in_progress"] * 50)

    with pytest.raises(llm.LlmUnavailable, match="nie skończył się"):
        llm.run_batch([], client=client, poll_seconds=0, timeout_seconds=0)


def test_the_deadline_message_carries_the_batch_id():
    """Wsad liczy się dalej po stronie API — bez identyfikatora nie ma po co
    tam wracać."""
    client = FakeClient(["in_progress"])

    with pytest.raises(llm.LlmUnavailable, match="batch_test"):
        llm.run_batch([], client=client, poll_seconds=0, timeout_seconds=0)


def test_a_dead_batch_does_not_wait_for_the_deadline():
    """Wsad odrzucony w pierwszej minucie to sześć godzin ciszy, jeśli stan
    końcowy nie kończy pętli."""
    client = FakeClient(["failed"])

    with pytest.raises(llm.LlmUnavailable, match="failed"):
        llm.run_batch([], client=client, poll_seconds=0)


def test_a_network_hiccup_does_not_abandon_a_paid_batch():
    client = FakeClient([ConnectionError("zerwane"), "in_progress",
                         ConnectionError("zerwane"), "completed"],
                        contents={"file_out": line("task-1", "a")},
                        output_file_id="file_out")

    out = llm.run_batch([], client=client, poll_seconds=0)

    assert list(out) == ["task-1"]


def test_a_run_of_failures_ends_with_an_error_not_a_loop():
    client = FakeClient([ConnectionError("zerwane")] * (llm.MAX_BATCH_STUMBLES + 1))

    with pytest.raises(llm.LlmUnavailable, match="nie udało się zapytać o stan"):
        llm.run_batch([], client=client, poll_seconds=0)


def test_a_provider_without_a_batch_adapter_says_so_before_the_bill():
    """LangChain NIE abstrahuje Batch API. Dostawca bez adaptera ma o tym
    usłyszeć, a nie zapłacić podwójnie za `.batch()` z tą samą stawką."""
    with pytest.raises(llm.LlmUnavailable, match="bez `--batch`"):
        llm.check_batch("anthropic:claude-opus-5")


def test_a_model_without_a_provider_is_refused():
    """`init_chat_model` umie zgadnąć dostawcę z nazwy — a zgadywanie decyduje
    wtedy, z czyjego konta idzie rachunek."""
    with pytest.raises(llm.LlmUnavailable, match="bez dostawcy"):
        llm.split_model("gpt-5")


def test_the_bill_knows_the_batch_discount():
    full = llm.Spend(model="openai:gpt-5.6-terra", input_tokens=1_000_000)
    half = llm.Spend(model="openai:gpt-5.6-terra", input_tokens=1_000_000, batch=True)

    assert full.dollars == pytest.approx(2.0)
    assert half.dollars == pytest.approx(2.0 * llm.BATCH_DISCOUNT)


def test_the_measurement_pair_is_ten_times_apart():
    """Para S6/S7 to terra kontra luna. Gdy ktoś podmieni cennik, pomiar traci
    sens po cichu — stąd wartownik na samej różnicy."""
    tokens = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    terra = llm.Spend(model="openai:gpt-5.6-terra", **tokens)
    luna = llm.Spend(model="openai:gpt-5.6-luna", **tokens)

    assert terra.dollars == pytest.approx(luna.dollars * 10)
