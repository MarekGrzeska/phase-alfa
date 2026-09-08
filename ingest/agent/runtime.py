"""Pętla agenta: model przez LangChain, narzędzia przez klienta MCP in-memory.

Jedna tura = `run_turn` (wiadomość korektora) albo `resume_turn` (decyzja
człowieka po przerwaniu). Obie strumieniują zdarzenia dla panelu: `token`,
`tool_call`, `tool_result`, `ui`, `confirm`, `usage`, `done`, `error`.

Potwierdzenia: narzędzie zwraca `{"confirm": {...}}` (M2). Interceptor wywołań
MCP widzi to i ZATRZYMUJE graf (`interrupt`) — panel dostaje zdarzenie `confirm`,
a po decyzji `resume_turn` wznawia dokładnie ten krok: `accept` woła narzędzie
ponownie z `confirmation=<id>`, `reject` oddaje modelowi odmowę. Graf po wznowieniu
wykonuje węzeł od początku, więc pierwsze wywołanie jest pamiętane po id wywołania
i nie zakłada drugiej prośby.

Graf trzyma stan w pamięci procesu (`InMemorySaver`). Po restarcie serwera historia
wraca z bazy (`agent_message`), a przerwanie w toku przepada — potwierdzenie
w bazie zostaje i można poprosić ponownie.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent

from agent import audit, context, conversation, limits, prompts
from agent.server import server
from correction import db, llm

AGENT_MODELS = ("openai:gpt-5.6-luna", "openai:gpt-5.6-terra", "openai:gpt-5.6-sol")
MODEL_LABELS = {"openai:gpt-5.6-luna": "luna", "openai:gpt-5.6-terra": "terra",
                "openai:gpt-5.6-sol": "sol"}
FALLBACK_MODEL = "openai:gpt-5.6-terra"
MOCK = "mock"

# Jeden na proces: wątki grafu = sesje; przeżywa żądania, nie restart.
CHECKPOINTER = InMemorySaver()
# Migawka stanu liczona raz na sesję — prompt ma być stały, żeby dało się go cache'ować.
SNAPSHOTS: dict[int, dict] = {}
# Sesje, w których właśnie biegnie tura — druga wiadomość naraz dostaje 409.
RUNNING: set[int] = set()
# id wywołania narzędzia → prośba o zgodę; graf po wznowieniu wykonuje węzeł
# od początku i bez tego prosiłby drugi raz.
PENDING_CONFIRMS: dict[str, dict] = {}
# id wywołania narzędzia → wiersz `agent_message` i argumenty (do dziennika).
CALL_MESSAGES: dict[str, int] = {}
CALL_ARGS: dict[str, dict] = {}
# id wywołania → potwierdzenie, które o nim rozstrzygnęło (do dziennika).
CONFIRMED_CALLS: dict[str, int] = {}


class AgentError(Exception):
    """Błąd konfiguracji albo stanu sesji — z komunikatem dla człowieka."""


def agent_error(exc: BaseException) -> AgentError | None:
    """`AgentError` także wtedy, gdy grupa zadań anyio opakowała go w `ExceptionGroup`.

    Sesja MCP in-memory biegnie w grupie zadań, więc wyjątek z ciała `async with`
    wychodzi z niej jako grupa — `except AgentError` by go nie zobaczył.
    """
    if isinstance(exc, AgentError):
        return exc
    for inner in getattr(exc, "exceptions", ()):
        found = agent_error(inner)
        if found is not None:
            return found
    return None


# ------------------------------------------------------------------ konfiguracja

def default_model() -> str:
    return os.environ.get("AGENT_MODEL") or FALLBACK_MODEL


def model_available(model: str) -> str | None:
    """`None`, gdy model da się uruchomić; inaczej powód po polsku."""
    try:
        llm.check_model(model)
        llm.check_key(llm.split_model(model)[0])
    except llm.LlmUnavailable as e:
        return str(e)
    return None


def config() -> dict:
    wanted = default_model()
    models = []
    for model in AGENT_MODELS:
        input_rate, output_rate = llm.PRICING[model]
        models.append({"id": model, "label": MODEL_LABELS[model],
                       "input_usd": input_rate, "output_usd": output_rate,
                       "unavailable": model_available(model)})
    mode = "live"
    reason = None
    if wanted == MOCK:
        mode, reason = "mock", "AGENT_MODEL=mock w .env"
    elif all(m["unavailable"] for m in models):
        mode, reason = "mock", models[0]["unavailable"]
    return {"models": models, "default": wanted if wanted in AGENT_MODELS else FALLBACK_MODEL,
            "mode": mode, "reason": reason}


def check_model(model: str) -> None:
    if model not in AGENT_MODELS:
        raise AgentError(f"model {model!r} spoza listy; do wyboru: {', '.join(AGENT_MODELS)}")
    why = model_available(model)
    if why:
        raise AgentError(why)


def chat_model_for(model: str) -> BaseChatModel:
    """Model rozmowy — osobna funkcja, żeby testy podstawiły model skryptowany.

    `use_responses_api`: modele gpt-5.6 odrzucają narzędzia funkcyjne na
    `/v1/chat/completions` („Function tools with reasoning_effort are not
    supported… use /v1/responses"). Przebiegi `verify`/`prefill` tego nie widzą,
    bo używają structured output bez narzędzi.
    """
    check_model(model)
    provider, _ = llm.split_model(model)
    extra = {"use_responses_api": True} if provider == "openai" else {}
    return llm.chat_model(model, **extra)


# ------------------------------------------------------------------ narzędzia

def text_of(result: CallToolResult) -> str:
    return "".join(c.text for c in result.content if isinstance(c, TextContent))


def parse_json(text: str) -> dict | None:
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


class ConfirmInterceptor:
    """Zamienia `{"confirm"}` z narzędzia na przerwanie grafu i wznawia po decyzji."""

    async def __call__(self, request, handler):
        runtime = request.runtime
        call_id = getattr(runtime, "tool_call_id", None)
        if call_id is None:
            return await handler(request)

        asked = PENDING_CONFIRMS.get(call_id)
        if asked is None:
            result = await handler(request)
            asked = parse_json(text_of(result)) if not result.isError else None
            if not asked or "confirm" not in asked:
                return result
            PENDING_CONFIRMS[call_id] = asked
        # `interrupt` przy pierwszym przejściu rzuca i wychodzi z węzła; po wznowieniu
        # graf wykonuje węzeł od nowa i tu dostajemy decyzję.
        decision = interrupt({"confirm": asked["confirm"], "tool": request.name,
                              "args": request.args, "tool_call_id": call_id})
        PENDING_CONFIRMS.pop(call_id, None)
        confirmation_id = asked["confirm"]["id"]
        CONFIRMED_CALLS[call_id] = confirmation_id
        if decision.get("decision") != "accept":
            return ToolMessage(
                content=f"Człowiek odrzucił potwierdzenie #{confirmation_id} dla `{request.name}`. "
                        "Nie wykonano. Nie ponawiaj tego wywołania bez wyraźnej prośby.",
                name=request.name, tool_call_id=call_id, status="error")
        return await handler(request.override(
            args={**request.args, "confirmation": confirmation_id}))


# ------------------------------------------------------------------ zdarzenia

def _chunk_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part)
                       for part in content)
    return ""


def _tool_result_payload(message: ToolMessage) -> dict:
    text = _chunk_text(message.content)
    parsed = parse_json(text)
    return {"id": message.tool_call_id, "name": message.name, "is_error":
            message.status == "error", "text": limits.clip_text(text, 4000)[0],
            "ui": parsed.get("ui") if parsed else None}


def _usage(message: AIMessage) -> tuple[int, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def _history(rows: list[dict]) -> list[BaseMessage]:
    """Historia z bazy → wiadomości dla grafu, gdy proces stracił jego stan."""
    out: list[BaseMessage] = []
    for row in rows:
        if row["role"] == "operator":
            out.append(HumanMessage(row["content"]))
        elif row["role"] == "agent" and row["content"]:
            out.append(AIMessage(row["content"]))
    return out


def _persist(cur, session_id: int, new_messages: list[BaseMessage], model: str) -> dict:
    """Nowe wiadomości grafu → `agent_message` i `agent_tool_call`. Zwraca zużycie.

    Argumenty wywołania niesie wiadomość modelu, wynik — wiadomość narzędzia;
    łączy je id wywołania, a przez `CALL_*` także wtedy, gdy wynik przyszedł
    dopiero po wznowieniu (inna tura, ten sam id).
    """
    spend = llm.Spend(model=model)
    for message in new_messages:
        if isinstance(message, AIMessage):
            input_tokens, output_tokens = _usage(message)
            spend.add(input_tokens, output_tokens)
            calls = [{"id": c["id"], "name": c["name"], "args": c["args"]}
                     for c in message.tool_calls]
            row = conversation.add_message(
                cur, session_id, "agent", _chunk_text(message.content), calls or None,
                input_tokens, output_tokens)
            for call in message.tool_calls:
                CALL_MESSAGES[call["id"]] = row
                CALL_ARGS[call["id"]] = call["args"]
        elif isinstance(message, ToolMessage):
            payload = _tool_result_payload(message)
            audit.record(cur, message.name or "?", CALL_ARGS.pop(message.tool_call_id, {}),
                         payload["text"], is_error=payload["is_error"],
                         confirmation_id=CONFIRMED_CALLS.pop(message.tool_call_id, None),
                         message_id=CALL_MESSAGES.pop(message.tool_call_id, None),
                         force=True)
    return {"input_tokens": spend.input_tokens, "output_tokens": spend.output_tokens,
            "usd": round(spend.dollars, 4), "model": model}


# ------------------------------------------------------------------ tury

def _config(session_id: int) -> dict:
    return {"configurable": {"thread_id": str(session_id)}}


async def _stream(agent, payload, session_id: int, model: str) -> AsyncIterator[dict]:
    """Zdarzenia z grafu; na końcu utrwala nowe wiadomości i oddaje `usage`."""
    conf = _config(session_id)
    state = await agent.aget_state(conf)
    before = len(state.values.get("messages", [])) if state.values else 0
    if isinstance(payload, dict):
        before += len(payload["messages"])
    waiting = None

    async for mode, data in agent.astream(payload, conf, stream_mode=["messages", "updates"]):
        if mode == "messages":
            chunk, _meta = data
            if isinstance(chunk, AIMessage):
                text = _chunk_text(chunk.content)
                if text:
                    yield {"type": "token", "text": text}
            continue
        for node, update in data.items():
            if node == "__interrupt__":
                for item in update:
                    waiting = item.value
                    yield {"type": "confirm", **item.value}
                continue
            for message in (update or {}).get("messages", []) if isinstance(update, dict) else []:
                if isinstance(message, AIMessage) and message.tool_calls:
                    for call in message.tool_calls:
                        yield {"type": "tool_call", "id": call["id"], "name": call["name"],
                               "args": call["args"]}
                elif isinstance(message, ToolMessage):
                    payload_out = _tool_result_payload(message)
                    yield {"type": "tool_result", **payload_out}
                    if payload_out["ui"]:
                        yield {"type": "ui", **payload_out["ui"]}

    state = await agent.aget_state(conf)
    new_messages = list(state.values.get("messages", []))[before:]
    with db.connect() as con, con.transaction(), con.cursor() as cur:
        usage = _persist(cur, session_id, new_messages, model)
    yield {"type": "usage", **usage}
    yield {"type": "done", "state": "waiting" if waiting else "finished"}


async def _agent_for(session: dict, mcp_session, chat_model: BaseChatModel | None):
    from langchain.agents import create_agent
    from langchain_mcp_adapters.tools import load_mcp_tools

    tools = await load_mcp_tools(mcp_session, tool_interceptors=[ConfirmInterceptor()],
                                 server_name="klucz")
    model = chat_model or chat_model_for(session["model"])
    snap = SNAPSHOTS.get(session["id"])
    if snap is None:
        snap = SNAPSHOTS[session["id"]] = prompts.snapshot()
    return create_agent(model, tools, system_prompt=prompts.system_prompt(snap),
                        checkpointer=CHECKPOINTER)


def _enter(session: dict) -> None:
    if session["id"] in RUNNING:
        raise AgentError("w tej rozmowie właśnie biegnie odpowiedź — poczekaj na `done`")
    RUNNING.add(session["id"])
    context.session_id.set(session["id"])
    context.model.set(session["model"])


async def run_turn(session: dict, text: str, screen: dict | None = None,
                   chat_model: BaseChatModel | None = None) -> AsyncIterator[dict]:
    """Wiadomość korektora → zdarzenia odpowiedzi. Kontekst ekranu idzie w treści tury."""
    _enter(session)
    try:
        with db.connect() as con, con.transaction(), con.cursor() as cur:
            conversation.update_screen(cur, session["id"], screen)
            conversation.set_title(cur, session["id"], text.strip().splitlines()[0])
            conversation.add_message(cur, session["id"], "operator", text)
            history = conversation.messages(cur, session["id"])[:-1]
        async with create_connected_server_and_client_session(server) as mcp_session:
            agent = await _agent_for(session, mcp_session, chat_model)
            state = await agent.aget_state(_config(session["id"]))
            fresh = not state.values
            human = HumanMessage(f"{prompts.screen_line(screen)}\n\n{text}")
            payload = {"messages": ([*_history(history), human] if fresh else [human])}
            async for event in _stream(agent, payload, session["id"], session["model"]):
                yield event
    except BaseException as e:
        known = agent_error(e)
        if known is None:
            raise
        yield {"type": "error", "message": str(known)}
    finally:
        RUNNING.discard(session["id"])


async def resume_turn(session: dict, confirmation_id: int, decision: str,
                      chat_model: BaseChatModel | None = None) -> AsyncIterator[dict]:
    """Decyzja człowieka → wznowienie przerwanego kroku i dalsze zdarzenia."""
    _enter(session)
    try:
        async with create_connected_server_and_client_session(server) as mcp_session:
            agent = await _agent_for(session, mcp_session, chat_model)
            state = await agent.aget_state(_config(session["id"]))
            if not state.tasks or not any(t.interrupts for t in state.tasks):
                raise AgentError("ta rozmowa na nic nie czeka — nie ma czego wznawiać "
                                 "(po restarcie serwera zadaj pytanie ponownie)")
            command = Command(resume={"decision": decision, "confirmation_id": confirmation_id})
            async for event in _stream(agent, command, session["id"], session["model"]):
                yield event
    except BaseException as e:
        known = agent_error(e)
        if known is None:
            raise
        yield {"type": "error", "message": str(known)}
    finally:
        RUNNING.discard(session["id"])
