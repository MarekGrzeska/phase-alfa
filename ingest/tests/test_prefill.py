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


class FakeRaw:
    """Surowa wiadomość spod `include_raw=True` — rachunek i powód końca."""

    def __init__(self, finish_reason):
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 20}
        self.response_metadata = {"finish_reason": finish_reason}


def reply(parsed, finish_reason="stop", parsing_error=None):
    """Kształt, który oddaje `with_structured_output(..., include_raw=True)`."""
    return {"raw": FakeRaw(finish_reason), "parsed": parsed,
            "parsing_error": parsing_error}


class FakeStructured:
    def __init__(self, replies):
        self._replies = list(replies)

    def invoke(self, _messages):
        answer = self._replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def make_tasks(count):
    return [{"id": i, "number": str(i), "max_points": 2, "content": "",
             "marking_text": "2 pkt pełne rozwiązanie"} for i in range(1, count + 1)]


def test_refusal_does_not_take_earlier_answers_down_with_it():
    """`parsed` jest `None` przy odmowie i przy ucięciu na limicie tokenów;
    `.model_dump()` leciał na tym AttributeError POZA pętlę."""
    good = prefill.Prefill(criteria=[])
    structured = FakeStructured([reply(good),
                                 reply(None, finish_reason="content_filter"),
                                 reply(good)])
    spend, out = llm.Spend(), {}

    prefill._ask_one_by_one(structured, make_tasks(3), spend, out)

    assert sorted(out) == [1, 3], "odpowiedzi sprzed odmowy mają zostać"
    assert len(spend.failures) == 1
    assert "content_filter" in spend.failures[0][1]


def test_refusal_still_lands_on_the_bill():
    structured = FakeStructured([reply(None, finish_reason="length")])
    spend, out = llm.Spend(), {}

    prefill._ask_one_by_one(structured, make_tasks(1), spend, out)

    assert not out
    assert spend.calls == 1 and spend.output_tokens == 20


def test_a_broken_schema_says_what_broke():
    """`parsing_error` niesie konkret; sam `finish_reason: stop` kazałby szukać
    powodu tam, gdzie go nie ma."""
    structured = FakeStructured([reply(None, parsing_error=ValueError("brak `points`"))])
    spend, out = llm.Spend(), {}

    prefill._ask_one_by_one(structured, make_tasks(1), spend, out)

    assert "brak `points`" in spend.failures[0][1]


def test_network_error_does_not_end_the_run():
    structured = FakeStructured([reply(prefill.Prefill(criteria=[])),
                                 ConnectionError("zerwane połączenie")])
    spend, out = llm.Spend(), {}

    prefill._ask_one_by_one(structured, make_tasks(2), spend, out)

    assert list(out) == [1]
    assert "ConnectionError" in spend.failures[0][1]
