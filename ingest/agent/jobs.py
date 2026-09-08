"""Przebiegi ingestu w tle: proces `task <nazwa> -- <flagi>`, log w pliku, rejestr w bazie.

Rejestr w `agent_job`, a log na dysku, bo `--reload` uvicorna restartuje proces
serwera: przebieg, który dalej pracuje, nie ma wtedy zginąć ani zniknąć z listy.
Uchwyt procesu żyje tylko w tym procesie — po restarcie o zadaniu wiemy tyle,
ile mówi log i baza, i mówimy to wprost, zamiast zgadywać, że skończyło.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from agent import context, limits
from sciezki import KORZEN_REPO

LOG_DIR = KORZEN_REPO / "data" / "reports" / "jobs"
TAIL = 80

# Uchwyty procesów uruchomionych w TYM procesie serwera.
PROCESSES: dict[int, subprocess.Popen] = {}


def task_binary() -> str:
    found = shutil.which("task")
    if found is None:
        raise ValueError("BRAK: `task` (go-task) w PATH — bez niego nie ma jak uruchomić przebiegu")
    return found


def start(cur, task: str, command: list[str], cwd: Path = KORZEN_REPO) -> dict:
    """Uruchamia polecenie w tle i zakłada wiersz w `agent_job`."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"{stamp}-{task.replace(':', '_')}.log"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    # Osobna grupa procesów: anulowanie ma trafić w przebieg, nie w serwer, a na
    # Windows tylko grupa przyjmuje CTRL_BREAK.
    extra = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
             else {"start_new_session": True})
    with log_path.open("wb") as log:
        log.write(f"$ {' '.join(command)}\n".encode())
        process = subprocess.Popen(  # noqa: S603 - polecenie z katalogu akcji, nie z żądania
            command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, env=env, **extra)
    cur.execute(
        """INSERT INTO agent_job (session_id, task, command, pid, log_path)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (context.session_id.get(), task, " ".join(command), process.pid,
         log_path.relative_to(KORZEN_REPO).as_posix()),
    )
    job_id = cur.fetchone()["id"]
    PROCESSES[job_id] = process
    return status(cur, job_id)


def _row(cur, job_id: int) -> dict:
    cur.execute("SELECT * FROM agent_job WHERE id = %s", (job_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"nie ma przebiegu #{job_id}")
    return row


def _settle(cur, row: dict) -> dict:
    """Dopisuje koniec przebiegu, gdy proces z tego serwera już wyszedł."""
    process = PROCESSES.get(row["id"])
    if row["finished_at"] is None and process is not None and process.poll() is not None:
        # Windows oddaje kody NTSTATUS bez znaku (CTRL_BREAK = 0xC000013A), a kolumna
        # jest 32-bitowa ze znakiem — ta sama liczba, zapisana tak, jak widzi ją C.
        code = process.returncode
        if code is not None and code >= 2**31:
            code -= 2**32
        cur.execute("UPDATE agent_job SET finished_at = now(), exit_code = %s WHERE id = %s "
                    "RETURNING *", (code, row["id"]))
        row = cur.fetchone()
        PROCESSES.pop(row["id"], None)
    return row


def status(cur, job_id: int) -> dict:
    row = _settle(cur, _row(cur, job_id))
    if row["finished_at"] is not None:
        state = "finished" if row["exit_code"] == 0 else "failed"
    elif row["id"] in PROCESSES:
        state = "running"
    else:
        state = "unknown"
    out = {**limits.jsonable(row), "state": state,
           "log_tail": tail(row["log_path"], 20)}
    if state == "unknown":
        out["note"] = ("proces uruchomiono przed restartem serwera — stan znany tylko "
                       "z logu; jeśli log się nie zmienia, przebieg skończył albo padł")
    return out


def tail(log_path: str, lines: int = TAIL) -> str:
    path = KORZEN_REPO / log_path
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-max(1, lines):])


def cancel(cur, job_id: int) -> dict:
    row = _settle(cur, _row(cur, job_id))
    process = PROCESSES.get(job_id)
    if row["finished_at"] is not None:
        raise ValueError(f"przebieg #{job_id} już się skończył (kod {row['exit_code']})")
    if process is None:
        raise ValueError(f"przebieg #{job_id} uruchomiono przed restartem serwera — "
                         f"zatrzymaj go ręcznie (pid {row['pid']})")
    if sys.platform == "win32":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
    return status(cur, job_id)


def list_jobs(cur, limit: int = 20) -> list[dict]:
    cur.execute("SELECT * FROM agent_job ORDER BY id DESC LIMIT %s", (limit,))
    rows = [_settle(cur, row) for row in cur.fetchall()]
    return [{**limits.jsonable(row),
             "state": ("finished" if row["exit_code"] == 0 else "failed")
             if row["finished_at"] is not None
             else ("running" if row["id"] in PROCESSES else "unknown")}
            for row in rows]
