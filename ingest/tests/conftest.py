"""Fixture'y wspólne dla testów ingestu."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from schema.migrate import polaczenie as adres

psycopg = pytest.importorskip("psycopg")

RUNNER = Path(__file__).resolve().parents[1] / "schema" / "migrate.py"


def _migrate(url: str) -> None:
    """Migracje przez ten sam runner co produkcyjnie — nie przez `schema.sql` w teście.

    Gdyby test stawiał schemat własną ścieżką, przechodziłby także wtedy, gdy
    runner jest zepsuty, czyli mierzyłby coś innego, niż nazwa mówi.
    """
    result = subprocess.run(
        [sys.executable, str(RUNNER)],
        env={**os.environ, "DATABASE_URL": url, "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, f"migracje nie przeszły:\n{result.stdout}{result.stderr}"


@pytest.fixture(scope="module")
def fresh_database(request) -> str:
    """Pusta baza z kompletem migracji, jedna na moduł testowy.

    Osobna baza, a nie transakcja w deweloperskiej: ekran korekty łączy się
    SAM, więc danych z nieuwiecznionej transakcji by nie zobaczył, a pisanie
    do korpusu roboczego zostawiałoby po testach śmieci nie do odróżnienia
    od prawdziwych rekordów.
    """
    try:
        base = adres()
    except SystemExit as e:
        pytest.skip(f"brak konfiguracji bazy: {e}")

    try:
        admin = psycopg.connect(base, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        pytest.skip(f"baza nieosiągalna: {e}")

    name = "klucz_test_" + request.module.__name__.rsplit(".", 1)[-1]
    url = urlunsplit(urlsplit(base)._replace(path=f"/{name}"))
    with admin:
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{name}"')
        try:
            _migrate(url)
            yield url
        finally:
            with admin.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
