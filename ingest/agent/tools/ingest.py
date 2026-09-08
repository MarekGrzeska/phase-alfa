"""Akcje ingestu jako narzędzia — generowane z katalogu `task menu`, nie pisane ręcznie.

Każda pozycja `CATALOG` (poza `foreground`) staje się `ingest_<zadanie>` z parametrami
z jej `Param`. Flagi składa to samo `build_args`, polecenie to samo `command_for`,
więc agent uruchamia dokładnie to, co człowiek wybrałby w menu. Płatne i kasujące
wymagają zgody człowieka; przebieg biegnie w tle jako `agent_job`.
"""

from __future__ import annotations

import inspect
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from agent import audit, confirm, jobs
from cli import app as catalog
from cli.app import Action, Param, build_args, command_for, shell_line
from correction import db

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
RUNS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False,
                       openWorldHint=True)
DESTROYS = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False,
                           openWorldHint=True)

KIND_TYPES = {"text": str | None, "int": int | None, "bool": bool | None,
              "choice": str | None, "words": str | None}


def tool_name(action: Action) -> str:
    return "ingest_" + action.task.replace(":", "_")


def param_name(param: Param) -> str:
    return param.flag.lstrip("-").replace("-", "_")


def description(action: Action) -> str:
    lines = [f"{action.title} — {action.about}"]
    if action.paid:
        lines.append("PŁATNE (z budżetu badawczego): wymaga zgody człowieka. "
                     "Przed `apply` obowiązuje dry-run na jednym roczniku.")
    if action.destructive:
        lines.append("KASUJE DANE: wymaga zgody człowieka.")
    if action.params:
        lines.append("Parametry:")
        for p in action.params:
            choices = f" [{', '.join(p.choices)}]" if p.choices else ""
            hint = f" — {p.hint}" if p.hint else ""
            lines.append(f"- {param_name(p)} ({p.kind}{choices}): {p.prompt}{hint}")
    lines.append("Zwraca przebieg w tle: sprawdzaj `job_status`, czytaj `job_log`, "
                 "raport końcowy przez `report_read`.")
    return "\n".join(lines)


def answers_of(action: Action, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Argumenty narzędzia → odpowiedzi menu ({flaga: wartość}) dla `build_args`."""
    answers: dict[str, Any] = {}
    for param in action.params:
        value = kwargs.get(param_name(param))
        if value is None:
            continue
        if param.kind == "choice" and value != "" and str(value) not in param.choices:
            raise ValueError(f"{param_name(param)}: {value!r} spoza listy "
                             f"[{', '.join(param.choices)}]")
        if param.kind == "int" and not str(value).isdigit():
            raise ValueError(f"{param_name(param)}: {value!r} to nie liczba")
        answers[param.flag] = value
    return answers


def make_tool(action: Action):
    name = tool_name(action)

    def run(**kwargs: Any) -> dict:
        confirmation = kwargs.pop("confirmation", None)
        answers = answers_of(action, kwargs)
        args = build_args(action, answers)
        command = command_for(action, args)
        line = shell_line(command)
        arguments = {"args": args}
        with db.connect() as con, con.transaction(), con.cursor() as cur:
            if action.paid or action.destructive:
                why = ("płatny przebieg z żywym modelem" if action.paid
                       else "przebieg kasujący dane")
                notes = [line, f"-- {why}"]
                if action.paid and "--apply" in args:
                    notes.append("-- UWAGA: `--apply` rozstrzyga w bazie; reguła z 4.09: "
                                 "najpierw dry-run na jednym roczniku")
                asked = confirm.ensure(cur, confirmation, name, arguments,
                                       f"Uruchomić: {action.title}", "\n".join(notes))
                if asked is not None:
                    return asked
            jobs.task_binary()
            job = jobs.start(cur, action.task, [jobs.task_binary(), *command[1:]])
            audit.record(cur, name, arguments, {"job": job["id"]},
                         confirmation_id=confirmation)
        return {"job": job, "command": line,
                "hint": "Przebieg biegnie w tle. `job_status(id)` po chwili; `job_log(id)` "
                        "pokaże wyjście; raport końcowy w `report_read`."}

    parameters = [
        inspect.Parameter(param_name(p), inspect.Parameter.KEYWORD_ONLY,
                          default=None, annotation=KIND_TYPES[p.kind])
        for p in action.params
    ]
    parameters.append(inspect.Parameter("confirmation", inspect.Parameter.KEYWORD_ONLY,
                                        default=None, annotation=int | None))
    run.__signature__ = inspect.Signature(parameters, return_annotation=dict)  # type: ignore[attr-defined]
    run.__name__ = name
    run.__annotations__ = {**{p.name: p.annotation for p in parameters}, "return": dict}
    run.__doc__ = description(action)
    return run


def register(mcp: FastMCP) -> None:
    for group in catalog.CATALOG:
        for action in group.actions:
            if action.foreground:
                continue
            mcp.add_tool(make_tool(action), name=tool_name(action),
                         description=description(action),
                         annotations=DESTROYS if action.destructive else RUNS,
                         meta={"confirm": action.paid or action.destructive,
                               "task": action.task, "group": group.title})

    @mcp.tool(annotations=READ_ONLY)
    def job_status(id: int) -> dict:
        """Stan przebiegu w tle: running / finished / failed / unknown, kod wyjścia,
        ostatnie linie logu."""
        with db.connect() as con, con.transaction(), con.cursor() as cur:
            return jobs.status(cur, id)

    @mcp.tool(annotations=READ_ONLY)
    def job_log(id: int, tail: int = jobs.TAIL) -> dict:
        """Ostatnie `tail` linii logu przebiegu (stdout+stderr)."""
        with db.connect() as con, con.transaction(), con.cursor() as cur:
            row = jobs.status(cur, id)
        return {"id": id, "state": row["state"], "log_path": row["log_path"],
                "text": jobs.tail(row["log_path"], max(1, min(int(tail), 400)))}

    @mcp.tool(annotations=READ_ONLY)
    def job_list(limit: int = 20) -> dict:
        """Przebiegi uruchomione przez agenta, najnowsze pierwsze."""
        with db.connect() as con, con.transaction(), con.cursor() as cur:
            return {"jobs": jobs.list_jobs(cur, max(1, min(int(limit), 100)))}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                          idempotentHint=True, openWorldHint=False))
    def job_cancel(id: int) -> dict:
        """Przerywa przebieg uruchomiony w tym procesie serwera (CTRL_BREAK / SIGTERM)."""
        with db.connect() as con, con.transaction(), con.cursor() as cur:
            row = jobs.cancel(cur, id)
            audit.record(cur, "job_cancel", {"id": id}, {"state": row["state"]})
        return row
