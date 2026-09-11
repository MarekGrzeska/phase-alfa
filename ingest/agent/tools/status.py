"""Stan projektu w jednym wywołaniu: liczby korpusu, migracje, środowisko, raporty.

To samo, co człowiek składa z `corpus:report`, `correction:report`, `migrate:status`,
`git status` i zerknięcia do `.env` — tylko naraz. Wartości sekretów nigdy nie
wychodzą: o kluczu API mówimy „jest / nie ma".
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

import psycopg
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from psycopg.rows import tuple_row

from agent import limits
from correction import db, inspector, stats
from reports import corpus
from schema import migrate
from sciezki import KORZEN_REPO, korzen_mirrora, spis_urls

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
REPORTS = KORZEN_REPO / "data" / "reports"
SECRETS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
SETTINGS = ("DB_HOST", "DB_PORT", "DB_NAME", "MIRROR_ROOT", "BLOB_ROOT", "CORRECTION_PORT",
            "AGENT_MODEL")


def git_state() -> dict:
    def run(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", *args], cwd=KORZEN_REPO, capture_output=True,  # noqa: S603, S607
                                  text=True, encoding="utf-8", check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    head = run("log", "-1", "--format=%h %ad %s", "--date=short")
    changes = run("status", "--porcelain")
    return {"branch": run("branch", "--show-current"), "head": head,
            "uncommitted_files": len(changes.splitlines()) if changes is not None else None}


def environment() -> dict:
    mirror = korzen_mirrora()
    return {
        "env_file": (KORZEN_REPO / ".env").is_file(),
        "settings": {k: os.environ.get(k) for k in SETTINGS},
        "secrets_present": {k: bool(os.environ.get(k)) for k in SECRETS},
        "mirror_root": str(mirror), "mirror_exists": mirror.is_dir(),
        "mirror_index_exists": spis_urls().is_file(),
        "blob_root_exists": (KORZEN_REPO / os.environ.get("BLOB_ROOT", "data/blob")).is_dir(),
    }


def corpus_numbers(con: psycopg.Connection) -> dict:
    """Definicja „zrobione" z `reports.corpus` — para liczb (korpus, sparsowane)."""
    out = {}
    with con.cursor(row_factory=tuple_row) as cur:
        for group, checks in (("done", corpus.CHECKS), ("gaps", corpus.GAPS)):
            out[group] = [
                {"label": label,
                 "corpus": cur.execute(sql.format(scope="corpus_task")).fetchone()[0],
                 "parsed": cur.execute(sql.format(scope="task")).fetchone()[0]}
                for label, sql in checks]
    return out


def database_state() -> dict:
    try:
        con = db.connect()
    except (psycopg.OperationalError, SystemExit) as e:
        return {"reachable": False, "error": str(e)}
    with con:
        # `zastosowane` składa słownik z krotek — kursor słownikowy dałby mu klucze
        # kolumn zamiast wersji i każda migracja wyglądałaby na brakującą.
        with con.cursor(row_factory=tuple_row) as plain:
            plain.execute(migrate.TABELA)
            applied = set(migrate.zastosowane(plain))
        files = migrate.migracje(migrate.KATALOG)
        with con.cursor() as cur:
            numbers = stats.collect(cur)
            health = [{"key": i["check"].key, "count": i["count"],
                       "severity": i["check"].severity} for i in inspector.health(cur)]
            actors = corpus.by_actor(cur)
            years = corpus.per_year(cur)
        return {
            "reachable": True,
            "migrations": {"applied": len(applied & {v for v, _, _ in files}),
                           "total": len(files),
                           "missing": [v for v, _, _ in files if v not in applied]},
            "status": limits.jsonable(numbers["status"]),
            "durations": limits.jsonable(numbers["durations"]),
            "forecast": limits.jsonable(numbers["forecast"]),
            "assets": limits.jsonable(numbers["assets"]),
            "s6": limits.jsonable(numbers["s6"]), "s7": limits.jsonable(numbers["s7"]),
            "years": limits.jsonable(years),
            "reviewed_by": limits.jsonable(actors),
            "health": health,
            "corpus": corpus_numbers(con),
        }


def report_files() -> list[Path]:
    if not REPORTS.is_dir():
        return []
    return sorted((p for p in REPORTS.iterdir() if p.is_file()),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def project_status() -> dict:
        """Stan projektu naraz: gałąź i commit, środowisko (.env, klucze API jako
        jest/nie ma, mirror), baza (migracje, statusy zadań, kto rozstrzygnął,
        S6′/S7/S8′, zdrowie danych, definicja „zrobione" A2) i ostatnie raporty."""
        return {
            "git": git_state(),
            "environment": environment(),
            "database": database_state(),
            "reports": [{"name": p.name,
                         "modified": limits.jsonable(datetime.fromtimestamp(p.stat().st_mtime))}
                        for p in report_files()[:10]],
        }

    @mcp.tool(annotations=READ_ONLY)
    def report_list(limit: int = 30) -> dict:
        """Raporty z `data/reports/` (ingest, verify, corpus, correction…), najnowsze pierwsze."""
        files = report_files()[:max(1, min(int(limit), 200))]
        return {"reports": [{"name": p.name, "bytes": p.stat().st_size,
                             "modified": limits.jsonable(datetime.fromtimestamp(p.stat().st_mtime))}
                            for p in files]}

    @mcp.tool(annotations=READ_ONLY)
    def report_read(name: str, tail: int | None = None) -> dict:
        """Treść raportu z `data/reports/` po nazwie pliku; `tail` = tylko ostatnie N linii."""
        path = (REPORTS / name).resolve()
        if not path.is_relative_to(REPORTS.resolve()) or not path.is_file():
            raise ValueError(f"nie ma raportu {name!r} w data/reports/")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if tail:
            lines = lines[-int(tail):]
        text, truncated = limits.clip_text("\n".join(lines), 16_000)
        return {"name": name, "text": text, "truncated": truncated, "lines": len(lines)}
