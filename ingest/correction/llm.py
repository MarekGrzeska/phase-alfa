"""Wspólna mechanika wywołań LLM w ingeście (G2.5).

Reguła twarda obu pozycji G2.5: **model proponuje, człowiek zatwierdza
w ekranie korekty**. Nic stąd nie wchodzi do korpusu z pominięciem bramki,
a provenance niesie schemat (`prefill_suggestion`, `description_status='auto'`),
nie pamięć autora.

Co jest tutaj, a nie w `prefill.py` i `describe.py`: klient, cennik, rachunek
tokenów i przebieg wsadowy. Oba zastosowania mają ten sam rachunek kosztu
i tę samą regułę „przebiegi masowe przez Batch API", więc liczenie ich dwa
razy skończyłoby się dwiema różnymi liczbami w raporcie do wniosku.

**Wywołań LLM nie ma w CI.** Testy chodzą na utrwalonych odpowiedziach —
stąd podział na funkcje czyste (budowa żądania, walidacja odpowiedzi, różnice)
i cienką warstwę wejścia-wyjścia.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from sciezki import KORZEN_REPO

# Cennik za milion tokenów, stan na 2026-08-26. Model jest PARAMETREM przebiegu:
# różnica jakości przy pięciokrotnej różnicy ceny jest częścią pomiaru S6/S7,
# a nie decyzją podjętą z góry w kodzie.
PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
DEFAULT_MODEL = "claude-opus-5"

# Batch API liczy połowę stawki. Wynik i tak czyta się następnego dnia
# w ekranie korekty, więc przy całym roczniku nie ma powodu płacić podwójnie.
BATCH_DISCOUNT = 0.5


class LlmUnavailable(RuntimeError):
    """Brak SDK albo klucza — z instrukcją po polsku, co zrobić."""


@dataclass
class Spend:
    """Rachunek jednego przebiegu — wejście do raportu i do wniosku grantowego."""

    model: str = DEFAULT_MODEL
    batch: bool = False
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    @property
    def dollars(self) -> float:
        input_rate, output_rate = PRICING.get(self.model, PRICING[DEFAULT_MODEL])
        gross = (self.input_tokens * input_rate
                 + self.output_tokens * output_rate) / 1_000_000
        return gross * (BATCH_DISCOUNT if self.batch else 1.0)

    def as_lines(self) -> list[str]:
        return [
            f"  model                  : {self.model}"
            f"{' (Batch API, -50%)' if self.batch else ''}",
            f"  wywołań                : {self.calls}",
            f"  tokenów wejścia        : {self.input_tokens}",
            f"  tokenów wyjścia        : {self.output_tokens}",
            f"  koszt przebiegu        : ${self.dollars:.4f}",
        ]


def client():
    """Klient Anthropic. Klucz WYŁĄCZNIE ze środowiska — nigdy z repozytorium."""
    try:
        import anthropic
    except ImportError as e:
        raise LlmUnavailable(
            "BRAK: pakiet `anthropic`. Uruchom `uv sync` w katalogu ingest/."
        ) from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LlmUnavailable(
            "BRAK: ANTHROPIC_API_KEY. Wpisz klucz do .env (jest w .gitignore); "
            "wzór stoi w .env.example. Wartość nigdy nie wchodzi do repozytorium."
        )
    return anthropic.Anthropic()


def check_model(model: str) -> None:
    if model not in PRICING:
        raise LlmUnavailable(
            f"Nieznany model {model!r}. Rachunek kosztu jest wynikiem alfy, więc "
            f"model bez ceny w cenniku odrzucamy. Znane: {', '.join(sorted(PRICING))}."
        )


def report_path(name: str, given: str | None = None) -> Path:
    path = Path(given or (KORZEN_REPO / "data" / "reports"
                          / f"{name}-{time.strftime('%Y-%m-%d')}.txt"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def run_batch(anthropic_client, requests: list, model: str) -> dict[str, object]:
    """Przebieg wsadowy: wysyła, czeka, oddaje wyniki po `custom_id`.

    Wyniki wracają w DOWOLNEJ kolejności — kluczem jest `custom_id`, nigdy
    pozycja na liście.
    """
    batch = anthropic_client.messages.batches.create(requests=requests)
    while True:
        status = anthropic_client.messages.batches.retrieve(batch.id)
        if status.processing_status == "ended":
            break
        print(f"  wsad {batch.id}: {status.processing_status}, "
              f"w toku {status.request_counts.processing}")
        time.sleep(30)
    out: dict[str, object] = {}
    for result in anthropic_client.messages.batches.results(batch.id):
        out[result.custom_id] = result.result
    return out
