"""Panel agenta wpięty w strony Jinja — miejsce zaczepienia, nie zachowanie.

Sam panel jest w Reakcie i ma własne testy (`correction/ui`, vitest). Tutaj
sprawdzamy to, czego tamte nie widzą: że każdy ekran narzędzia ma gdzie go
zamontować i skąd wziąć paczkę. Kontener wpięty do jednego widoku zamiast do
`base.html` zabrałby agenta inspektorowi i nikt by tego nie zauważył.
"""

from __future__ import annotations

from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

TEMPLATES = Path(__file__).resolve().parents[1] / "correction" / "templates"

# Szablony, które dziedziczą po `base.html` — czyli to, co zostało jeszcze
# na Jinja. Przegląd i formularz zadania zeszły już z tej listy: rysuje je
# `app.html` plus `main.tsx`. Zostaje inspektor.
SCREENS = [
    "inspect_index.html",
    "inspect_list.html",
    "inspect_record.html",
    "inspect_health.html",
]


@pytest.fixture(scope="module")
def environment() -> jinja2.Environment:
    """Ten sam katalog szablonów co w aplikacji, bez bazy i bez serwera."""
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
    )


@pytest.mark.parametrize("shell", ["base.html", "app.html"])
def test_kontener_i_paczka_sa_w_obu_skorupach(environment, shell: str) -> None:
    """Panel jest tak samo na stronach Jinja, jak na widokach Reacta.

    Dwie skorupy żyją obok siebie tylko na czas migracji — dopóki żyją, agent
    ma być na każdej, bo korektor przechodzi między nimi w jednej sesji.
    """
    html = environment.get_template(shell).render()
    assert 'id="agent-root"' in html
    assert '/static/correction.js' in html
    assert '/static/correction.css' in html


def test_kontener_stoi_poza_kolumna_tresci(environment) -> None:
    """Panel jest kolumną wiersza, a nie elementem przewijanej treści.

    Gdyby siedział wewnątrz `.workspace-content`, odjeżdżałby w górę razem
    ze skanem klucza — a ma stać obok niego.
    """
    html = environment.get_template("base.html").render()
    content_end = html.index("</main>")
    assert html.index('id="agent-root"') > content_end
    assert html.index('class="workspace"') < content_end


@pytest.mark.parametrize("screen", SCREENS)
def test_kazdy_ekran_dziedziczy_po_base(environment, screen: str) -> None:
    """Ekran poza `base.html` zostałby bez panelu — także ten w inspektorze."""
    source = environment.loader.get_source(environment, screen)[0]
    assert '{% extends "base.html" %}' in source, f"{screen} nie dziedziczy po base.html"


def test_aplikacja_wystawia_katalog_paczki() -> None:
    """`/static` jest zamontowane nawet wtedy, gdy paczki jeszcze nie zbudowano.

    Brak buildu ma zabrać sam panel, a nie wywalić ekran korekty przy starcie —
    korekta jest ścieżką krytyczną A2, front agenta nie.
    """
    pytest.importorskip("fastapi")
    from correction.app import app

    mounts = [route for route in app.routes if getattr(route, "name", "") == "static"]
    assert mounts, "aplikacja nie montuje /static"
    assert mounts[0].path == "/static"
