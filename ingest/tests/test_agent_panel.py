"""Panel agenta w szablonie wspólnym — makieta G-x, bez agenta za nią.

Sedno testu nie jest w tym, że panel się renderuje, tylko w tym, że siedzi
w `base.html`, czyli WSZĘDZIE: na ekranie korekty i w inspektorze. Gdyby ktoś
wstawił go do jednego widoku, ten test to złapie.
"""

from __future__ import annotations

from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

TEMPLATES = Path(__file__).resolve().parents[1] / "correction" / "templates"

# Szablony, które dziedziczą po `base.html` — czyli każdy ekran narzędzia.
SCREENS = [
    "index.html",
    "task.html",
    "inspect_index.html",
    "inspect_list.html",
    "inspect_record.html",
    "inspect_health.html",
]


@pytest.fixture(scope="module")
def environment() -> "jinja2.Environment":
    """Ten sam katalog szablonów co w aplikacji, bez bazy i bez serwera.

    Dane wchodzą jako `Undefined`, bo pytanie brzmi „czy panel jest w układzie",
    a nie „co pokazuje wiersz inspektora" — na to są testy integracyjne.
    """
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
    )


def test_panel_renderuje_sie_zwiniety(environment) -> None:
    """Stan początkowy to szyna, nie rozwinięta kolumna.

    Korektor otwiera to narzędzie po to, żeby patrzeć na skan klucza. Panel,
    który wita go rozwinięty, zabiera szerokość, o którą nikt nie prosił.
    """
    html = environment.get_template("agent_panel.html").render()
    assert 'id="agent-panel"' in html
    assert 'data-state="collapsed"' in html


def test_pole_wiadomosci_jest_wylaczone(environment) -> None:
    """Makieta ma wyglądać na niegotową — wysłanie wiadomości nie ma dokąd pójść."""
    html = environment.get_template("agent_panel.html").render()
    composer = html[html.index("agent-composer"):]
    assert composer.count("disabled") >= 2


def test_panel_siedzi_w_szablonie_wspolnym(environment) -> None:
    """Panel należy do narzędzia, nie do widoku — stąd `base.html`, nie ekran.

    Renderowane bez danych: `base.html` sam ich nie potrzebuje, a to on
    decyduje o układzie kolumn.
    """
    html = environment.get_template("base.html").render()
    assert 'class="workspace"' in html
    assert 'id="agent-panel"' in html


@pytest.mark.parametrize("screen", SCREENS)
def test_kazdy_ekran_dziedziczy_po_base(environment, screen: str) -> None:
    """Ekran poza `base.html` zostałby bez panelu — także ten w inspektorze."""
    source = environment.loader.get_source(environment, screen)[0]
    assert '{% extends "base.html" %}' in source, f"{screen} nie dziedziczy po base.html"
