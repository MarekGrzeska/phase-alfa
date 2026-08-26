"""Wspólna mechanika wywołań LLM w ingeście (G2.5).

Reguła twarda obu pozycji G2.5: **model proponuje, człowiek zatwierdza
w ekranie korekty**. Nic stąd nie wchodzi do korpusu z pominięciem bramki,
a provenance niesie schemat (`prefill_suggestion`, `description_status='auto'`),
nie pamięć autora.

Co jest tutaj, a nie w `prefill.py` i `describe.py`: klient, cennik, rachunek
tokenów i przebieg wsadowy. Oba zastosowania mają ten sam rachunek kosztu
i tę samą regułę „przebiegi masowe przez Batch API", więc liczenie ich dwa
razy skończyłoby się dwiema różnymi liczbami w raporcie do wniosku.

**Provider jest parametrem, nie stałą.** Wywołania idą przez LangChain
(`init_chat_model`), więc `prefill.py` i `describe.py` nie znają dostawcy —
znają model w postaci `provider:nazwa`. Zmiana `openai:gpt-5.6-terra` na
`anthropic:claude-opus-5` nie dotyka ani jednej linii tamtych plików.

**Wyjątek, który trzeba znać: Batch API.** LangChain go NIE abstrahuje —
`Runnable.batch()` to zrównoleglenie po stronie klienta, te same żądania
i ta sama cena. Prawdziwy wsad (−50%, okno 24 h) to osobny endpoint dostawcy,
więc `--batch` schodzi tu do surowego SDK i na dziś działa dla `openai`.
Innym dostawcom mówimy to wprost, zamiast po cichu policzyć podwójnie.

**Wywołań LLM nie ma w CI.** Testy chodzą na utrwalonych odpowiedziach —
stąd podział na funkcje czyste (budowa żądania, walidacja odpowiedzi, różnice)
i cienką warstwę wejścia-wyjścia.
"""

from __future__ import annotations

import io
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from sciezki import KORZEN_REPO

# Cennik za milion tokenów, stan na 2026-08-26. Klucz jest ADRESEM MODELU
# w LangChainie, więc ta sama wartość jest argumentem `--model`, kluczem cennika
# i wejściem `init_chat_model`. Para terra/luna to 10× różnicy ceny — dlaczego
# akurat ona jest pomiarem S6/S7, stoi w `docs/decyzje-A2.md`.
PRICING = {
    "openai:gpt-5.6-terra": (2.0, 12.0),
    "openai:gpt-5.6-luna": (0.2, 1.2),
    "anthropic:claude-opus-5": (5.0, 25.0),
    "anthropic:claude-haiku-4-5": (1.0, 5.0),
}
DEFAULT_MODEL = "openai:gpt-5.6-terra"

# Klucz WYŁĄCZNIE ze środowiska — nigdy z repozytorium. Wzór w `.env.example`.
API_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Pakiet LangChaina per dostawca — do komunikatu, gdy go brakuje.
PROVIDER_PACKAGES = {
    "openai": "langchain-openai",
    "anthropic": "langchain-anthropic",
}

# Batch API liczy połowę stawki. Wynik i tak czyta się następnego dnia
# w ekranie korekty, więc przy całym roczniku nie ma powodu płacić podwójnie.
BATCH_DISCOUNT = 0.5


class LlmUnavailable(RuntimeError):
    """Brak pakietu, klucza albo trybu — z instrukcją po polsku, co zrobić."""


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


# ── adres modelu ───────────────────────────────────────────────────────────

def split_model(model: str) -> tuple[str, str]:
    """`openai:gpt-5` → `("openai", "gpt-5")`.

    Sama nazwa bez dostawcy jest odrzucana: `init_chat_model` potrafi go
    zgadnąć z prefiksu nazwy, ale zgadywanie decyduje wtedy, z czyjego konta
    idzie rachunek. Wolimy to mieć napisane.
    """
    provider, _, name = model.partition(":")
    if not name:
        raise LlmUnavailable(
            f"Model {model!r} bez dostawcy. Podaj `dostawca:nazwa`, np. "
            f"{DEFAULT_MODEL!r}. Znane: {', '.join(sorted(PRICING))}."
        )
    return provider, name


def check_model(model: str) -> None:
    if model not in PRICING:
        raise LlmUnavailable(
            f"Nieznany model {model!r}. Rachunek kosztu jest wynikiem alfy, więc "
            f"model bez ceny w cenniku odrzucamy. Znane: {', '.join(sorted(PRICING))}."
        )


def check_key(provider: str) -> None:
    variable = API_KEYS.get(provider)
    if variable is None:
        raise LlmUnavailable(
            f"Dostawca {provider!r} nie ma wpisu w `API_KEYS` — dopisz nazwę "
            f"zmiennej z kluczem, zanim odpalisz przebieg."
        )
    if not os.environ.get(variable):
        raise LlmUnavailable(
            f"BRAK: {variable}. Wpisz klucz do .env (jest w .gitignore); "
            f"wzór stoi w .env.example. Wartość nigdy nie wchodzi do repozytorium."
        )


def chat_model(model: str = DEFAULT_MODEL, **kwargs):
    """Model rozmowy przez LangChain — jedyne wejście dla przebiegów pojedynczych.

    Zwraca `BaseChatModel`, więc wołający nie wie, czy pod spodem stoi OpenAI,
    czy Anthropic. Kontrakt widoczny na zewnątrz to `.invoke(messages)`
    i `.with_structured_output(...)`.
    """
    check_model(model)
    provider, name = split_model(model)
    check_key(provider)
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as e:
        raise LlmUnavailable(
            "BRAK: pakiet `langchain`. Uruchom `uv sync` w katalogu ingest/."
        ) from e
    try:
        return init_chat_model(name, model_provider=provider, **kwargs)
    except ImportError as e:
        package = PROVIDER_PACKAGES.get(provider, f"langchain-{provider}")
        raise LlmUnavailable(
            f"BRAK: pakiet `{package}` dla dostawcy {provider!r}. "
            f"Dopisz go do `ingest/pyproject.toml` i uruchom `uv sync`."
        ) from e


def messages(system: str, content) -> list:
    """(system, użytkownik) w postaci LangChaina — jedna budowa dla obu ścieżek.

    Import leniwy, tak jak reszta SDK: `db.prefill_hints` importuje `prefill`
    dla samych podpowiedzi w ekranie korekty i nie ma powodu ciągnąć wtedy
    całego LangChaina do procesu serwera.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    return [SystemMessage(system), HumanMessage(content)]


def usage_of(source) -> tuple[int, int]:
    """(tokeny wejścia, tokeny wyjścia) — z odpowiedzi LangChaina albo z wsadu.

    LangChain normalizuje rachunek do `usage_metadata` niezależnie od dostawcy;
    wsad wraca surowym JSON-em dostawcy, więc drugie wejście czyta nazwy OpenAI.
    Tokeny rozumowania modeli myślących siedzą w tokenach wyjścia i są po ich
    stawce — rachunek jest więc pełny, choć w odpowiedzi ich nie widać.
    """
    if source is None:
        return 0, 0
    usage = getattr(source, "usage_metadata", None)
    if usage:
        return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    if isinstance(source, dict):
        return (int(source.get("prompt_tokens", 0)),
                int(source.get("completion_tokens", 0)))
    return 0, 0


def report_path(name: str, given: str | None = None) -> Path:
    path = Path(given or (KORZEN_REPO / "data" / "reports"
                          / f"{name}-{time.strftime('%Y-%m-%d')}.txt"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ── przebieg wsadowy ───────────────────────────────────────────────────────
# Okno Batch API to 24 h, ale przebieg alfy ma się zamknąć w dniu pracy:
# po terminie wsad żyje dalej po stronie API, a konsola wraca do człowieka.
BATCH_POLL_SECONDS = 30
BATCH_TIMEOUT_SECONDS = 6 * 3600
MAX_BATCH_STUMBLES = 5
BATCH_ENDPOINT = "/v1/chat/completions"
BATCH_WINDOW = "24h"

# Wsad to jedyne miejsce poniżej LangChaina, więc kolejny dostawca to nowy
# adapter, a nie flaga.
BATCH_PROVIDERS = ("openai",)

# Stany, po których nie ma na co czekać — bez nich pętla dobijałaby do terminu
# przy wsadzie, który padł w pierwszej minucie.
BATCH_TERMINAL = {"failed", "expired", "cancelled"}


def batch_supported(model: str) -> bool:
    provider, _ = split_model(model)
    return provider in BATCH_PROVIDERS


def check_batch(model: str) -> None:
    provider, _ = split_model(model)
    if provider not in BATCH_PROVIDERS:
        raise LlmUnavailable(
            f"Dostawca {provider!r} nie ma tu wsadu. LangChain NIE abstrahuje "
            f"Batch API (`.batch()` to zrównoleglenie po stronie klienta, ta sama "
            f"cena), a adapter jest napisany dla: {', '.join(BATCH_PROVIDERS)}. "
            f"Odpal bez `--batch` — zapłacisz pełną stawkę, ale świadomie."
        )


def batch_client(model: str):
    """Surowy klient dostawcy — WYŁĄCZNIE do wsadu.

    Jedyne miejsce w ingeście, które omija LangChain. Powód stoi w `check_batch`:
    inaczej `--batch` znaczyłoby „to samo, tylko równolegle i za pełną cenę".
    """
    check_batch(model)
    provider, _ = split_model(model)
    check_key(provider)
    try:
        import openai
    except ImportError as e:
        raise LlmUnavailable(
            "BRAK: pakiet `openai` (Batch API). Uruchom `uv sync` w katalogu ingest/."
        ) from e
    return openai.OpenAI()


def batch_body(model: str, messages, *, max_tokens: int,
               response_format: dict | None = None) -> dict:
    """Wiadomości LangChaina → ciało żądania dostawcy dla wsadu.

    Wiadomości buduje się RAZ, w postaci LangChaina, i tak samo idą przez
    `.invoke()`. Tu tłumaczy je konwerter z `langchain_core`, żeby ścieżka
    wsadowa i pojedyncza nie rozjechały się treścią promptu — a to jest różnica,
    której pomiar S6/S7 by nie wychwycił, tylko pogorszył.
    """
    try:
        from langchain_core.messages import convert_to_openai_messages
    except ImportError as e:
        raise LlmUnavailable(
            "BRAK: pakiet `langchain-core`. Uruchom `uv sync` w katalogu ingest/."
        ) from e
    _, name = split_model(model)
    body: dict[str, object] = {
        "model": name,
        "messages": convert_to_openai_messages(messages),
        # `max_completion_tokens`, nie `max_tokens`: stara nazwa jest u OpenAI
        # odrzucana, a do limitu liczą się też tokeny rozumowania.
        "max_completion_tokens": max_tokens,
    }
    if response_format is not None:
        body["response_format"] = response_format
    return body


def batch_request(custom_id: str, body: dict,
                  endpoint: str = BATCH_ENDPOINT) -> dict:
    """Jeden wiersz pliku wsadowego."""
    return {"custom_id": custom_id, "method": "POST", "url": endpoint, "body": body}


def batch_payload(row: dict | None) -> tuple[dict | None, str]:
    """Wiersz wyniku → (ciało odpowiedzi, powód niepowodzenia).

    Dokładnie jedno z dwóch jest puste. Wiersze z pliku błędów wracają tą samą
    drogą co udane, więc wołający wie, DLACZEGO zadania nie ma — zamiast
    zgadywać z jego nieobecności.
    """
    if row is None:
        return None, "wsad: brak wyniku"
    if row.get("error"):
        return None, f"wsad: {row['error']}"
    response = row.get("response") or {}
    if response.get("status_code") != 200:
        return None, f"wsad: HTTP {response.get('status_code')}"
    return response.get("body") or {}, ""


def _jsonl(requests: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n"
                   for r in requests).encode("utf-8")


def _pending(status) -> int | str:
    """Ile żądań wsadu jeszcze się liczy — do jednej linii w konsoli."""
    counts = getattr(status, "request_counts", None)
    if counts is None:
        return "?"
    return (getattr(counts, "total", 0) - getattr(counts, "completed", 0)
            - getattr(counts, "failed", 0))


def _collect(client, status) -> dict[str, dict]:
    """Wyniki i błędy wsadu po `custom_id`.

    Kluczem jest `custom_id`, NIGDY pozycja na liście: wyniki wracają
    w dowolnej kolejności, a plik błędów to osobny plik.
    """
    out: dict[str, dict] = {}
    for file_id in (status.output_file_id, getattr(status, "error_file_id", None)):
        if not file_id:
            continue
        for line in client.files.content(file_id).text.splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["custom_id"]] = row
    return out


def run_batch(requests: list[dict], model: str = DEFAULT_MODEL, *,
              client=None,
              endpoint: str = BATCH_ENDPOINT,
              poll_seconds: int = BATCH_POLL_SECONDS,
              timeout_seconds: int = BATCH_TIMEOUT_SECONDS) -> dict[str, dict]:
    """Przebieg wsadowy: wysyła plik, czeka, oddaje wyniki po `custom_id`.

    Czekanie ma termin i znosi drgnięcia sieci: `while True` bez jednego
    i drugiego dawał się przerwać wyłącznie Ctrl-C, czyli kosztem całej
    opłaconej roboty.
    """
    client = client or batch_client(model)
    upload = client.files.create(
        file=("batch.jsonl", io.BytesIO(_jsonl(requests)), "application/jsonl"),
        purpose="batch")
    batch = client.batches.create(input_file_id=upload.id, endpoint=endpoint,
                                  completion_window=BATCH_WINDOW)
    print(f"  wsad {batch.id}: wysłany, żądań {len(requests)}")
    deadline = time.monotonic() + timeout_seconds
    stumbles = 0
    status = None
    while True:
        try:
            status = client.batches.retrieve(batch.id)
        except Exception as e:
            stumbles += 1
            if stumbles > MAX_BATCH_STUMBLES:
                raise LlmUnavailable(
                    f"Wsad {batch.id}: {MAX_BATCH_STUMBLES} razy z rzędu nie udało "
                    f"się zapytać o stan ({type(e).__name__}: {e}). Wsad liczy się "
                    f"dalej po stronie API pod tym identyfikatorem."
                ) from e
            print(f"  wsad {batch.id}: nie udało się zapytać o stan "
                  f"({type(e).__name__}), próba {stumbles}/{MAX_BATCH_STUMBLES}")
        else:
            stumbles = 0
            if status.status == "completed":
                break
            if status.status in BATCH_TERMINAL:
                # Czekanie do terminu na wsad, który już padł, to sześć godzin
                # ciszy zamiast komunikatu.
                raise LlmUnavailable(
                    f"Wsad {batch.id} skończył się stanem {status.status!r}. "
                    f"Nic nie wróciło — sprawdź wsad po tym identyfikatorze "
                    f"po stronie API."
                )
            print(f"  wsad {batch.id}: {status.status}, "
                  f"w toku {_pending(status)}")
        if time.monotonic() >= deadline:
            raise LlmUnavailable(
                f"Wsad {batch.id} nie skończył się w {timeout_seconds // 3600} h. "
                f"Nie przepadł — liczy się dalej po stronie API pod tym "
                f"identyfikatorem, a wyniki odbierze ponowny przebieg."
            )
        time.sleep(poll_seconds)
    return _collect(client, status)
