"""Menu ingestu: katalog akcji zgadza się z Taskfile i z `--help` modułów."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from cli import app
from cli.app import Action, Param, build_args, command_for, shell_line

TASKFILE = Path(__file__).resolve().parents[2] / "Taskfile.yml"

# Zadania z Taskfile są na początku linii, wcięte o dwie spacje, z dwukropkiem.
TASK_NAME = re.compile(r"^  ([a-z][a-z0-9:_-]*):\s*$", re.M)


def test_every_catalog_task_exists_in_taskfile():
    known = set(TASK_NAME.findall(TASKFILE.read_text(encoding="utf-8")))
    missing = [a.task for a in app.actions().values() if a.task not in known]
    assert not missing, f"w katalogu menu, ale nie w Taskfile: {missing}"


def test_catalog_has_no_duplicate_tasks():
    tasks = [a.task for g in app.CATALOG for a in g.actions]
    assert len(tasks) == len(set(tasks))


# Które zadanie Taskfile to który moduł — żeby zapytać go o `--help`.
MODULES = {
    "mirror": "mirror.cke_mirror",
    "ingest": "parsers.omap_e8.run",
    "parser:snapshot": "parsers.omap_e8.snapshot",
    "crops": "parsers.omap_e8.crops",
    "correction:report": "correction.report",
    "verify": "correction.verify",
    "prefill": "correction.prefill",
    "describe": "correction.describe",
    "frame": "correction.frame",
    "golden:generate": "golden.generate",
    "golden:grade": "golden.grade",
    "mathjson": "mathjson.fill",
    "corpus:report": "reports.corpus",
}


@pytest.mark.parametrize("task", sorted(MODULES))
def test_every_flag_in_catalog_is_accepted_by_the_module(task):
    """`--help` modułu jest źródłem prawdy o flagach; menu nie może wymyślać własnych."""
    action = app.actions()[task]
    result = subprocess.run(
        [sys.executable, "-m", MODULES[task], "--help"],
        capture_output=True, text=True, encoding="utf-8", check=False,
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    for param in action.params:
        assert param.flag in result.stdout, f"{task}: {param.flag} nie ma w --help"


def test_build_args_skips_empty_and_false():
    action = Action("x", "x", "x", (
        Param("--year", "r", "choice", choices=("2025",)),
        Param("--apply", "a", "bool"),
        Param("--limit", "l", "int"),
        Param("--compare", "c", "words"),
    ))
    args = build_args(action, {"--year": "2025", "--apply": False, "--limit": "",
                               "--compare": "a.json b.json"})
    assert args == ["--year", "2025", "--compare", "a.json", "b.json"]


def test_bool_flag_has_no_value_and_order_follows_catalog():
    action = Action("x", "x", "x", (Param("--apply", "a", "bool"), Param("--year", "r")))
    assert build_args(action, {"--year": "2025", "--apply": True}) == ["--apply", "--year", "2025"]


def test_command_without_args_has_no_double_dash():
    action = Action("corpus:report", "x", "x")
    assert command_for(action, []) == ["task", "corpus:report"]
    assert command_for(action, ["--copy-to-docs"]) == ["task", "corpus:report", "--",
                                                       "--copy-to-docs"]


def test_shell_line_quotes_spaces():
    assert shell_line(["task", "ingest", "--", "--report", "moj raport.txt"]) \
        == 'task ingest -- --report "moj raport.txt"'


def test_paid_and_destructive_actions_are_marked():
    catalog = app.actions()
    for task in ("verify", "prefill", "describe", "frame", "golden:generate", "golden:grade"):
        assert catalog[task].paid, task
    assert catalog["db:reset"].destructive
    assert catalog["correction"].foreground and catalog["db:psql"].foreground
