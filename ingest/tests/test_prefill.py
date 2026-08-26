"""Prefill LLM (G2.5.1) — kontrakt odpowiedzi i zachowanie, gdy jej nie ma.

Wywołań LLM nie ma w CI, więc sprawdza się schemat wysyłany do API i pętlę,
która przyjmuje odpowiedzi. Oba były zepsute tam, gdzie nikt nie patrzył.
"""

from __future__ import annotations

from correction import llm, prefill


def objects_in(node, found=None):
    """Wszystkie obiekty schematu, razem z tymi w `$defs`."""
    found = [] if found is None else found
    if isinstance(node, list):
        for item in node:
            objects_in(item, found)
    elif isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            found.append(node)
        for value in node.values():
            objects_in(value, found)
    return found


def test_schema_closes_every_object_not_just_the_root():
    """Schemat oklepany po korzeniu wracał z API kodem 400 na KAŻDYM żądaniu
    wsadu, czyli tańsze ramię pomiaru S6 nie działało wcale."""
    objects = objects_in(prefill.strict_schema(prefill.Prefill))

    assert len(objects) >= 3, "schemat ma korzeń i dwa `$defs`"
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_field_with_a_default_is_required_for_the_api():
    schema = prefill.strict_schema(prefill.Prefill)

    assert "criteria" in schema["required"]
    assert "conditions" in schema["$defs"]["Criterion"]["required"]
    assert "label" in schema["$defs"]["Criterion"]["required"]


def test_schema_carries_no_default_values():
    assert "default" not in str(prefill.strict_schema(prefill.Prefill))


def test_schema_stays_the_parser_contract():
    """Progi → warunki → zapisy: inaczej różnica parser vs model jest
    tłumaczeniem, a nie porównaniem."""
    schema = prefill.strict_schema(prefill.Prefill)

    assert set(schema["$defs"]["Criterion"]["properties"]) == {
        "points", "label", "conditions"}
    assert set(schema["$defs"]["Condition"]["properties"]) == {
        "description", "expressions"}


class FakeUsage:
    input_tokens = 100
    output_tokens = 20


class FakeResponse:
    def __init__(self, parsed_output, stop_reason="end_turn"):
        self.parsed_output = parsed_output
        self.stop_reason = stop_reason
        self.usage = FakeUsage()


class FakeMessages:
    def __init__(self, replies):
        self._replies = list(replies)

    def parse(self, **_):
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeClient:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)


def make_tasks(count):
    return [{"id": i, "number": str(i), "max_points": 2, "content": "",
             "marking_text": "2 pkt pełne rozwiązanie"} for i in range(1, count + 1)]


def test_refusal_does_not_take_earlier_answers_down_with_it():
    """`parsed_output` jest `None` przy odmowie i przy ucięciu na `max_tokens`;
    `.model_dump()` leciał na tym AttributeError POZA pętlę."""
    good = prefill.Prefill(criteria=[])
    client = FakeClient([FakeResponse(good),
                         FakeResponse(None, stop_reason="refusal"),
                         FakeResponse(good)])
    spend, out = llm.Spend(), {}

    prefill._ask_one_by_one(client, make_tasks(3), llm.DEFAULT_MODEL, spend, out)

    assert sorted(out) == [1, 3], "odpowiedzi sprzed odmowy mają zostać"
    assert len(spend.failures) == 1
    assert "refusal" in spend.failures[0][1]


def test_refusal_still_lands_on_the_bill():
    client = FakeClient([FakeResponse(None, stop_reason="max_tokens")])
    spend, out = llm.Spend(), {}

    prefill._ask_one_by_one(client, make_tasks(1), llm.DEFAULT_MODEL, spend, out)

    assert not out
    assert spend.calls == 1 and spend.output_tokens == 20


def test_network_error_does_not_end_the_run():
    client = FakeClient([FakeResponse(prefill.Prefill(criteria=[])),
                         ConnectionError("zerwane połączenie")])
    spend, out = llm.Spend(), {}

    prefill._ask_one_by_one(client, make_tasks(2), llm.DEFAULT_MODEL, spend, out)

    assert list(out) == [1]
    assert "ConnectionError" in spend.failures[0][1]
