"""Skorupa strony: miejsce zaczepienia dla widoku i dla panelu agenta.

Widoki i panel są w Reakcie i mają własne testy (`correction/ui`, vitest).
Tutaj sprawdzamy to, czego tamte nie widzą: że każdy adres narzędzia oddaje
skorupę z NAZWĄ widoku i z kontenerem panelu, oraz skąd bierze się paczka.
"""

from __future__ import annotations

from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

TEMPLATES = Path(__file__).resolve().parents[1] / "correction" / "templates"


@pytest.fixture(scope="module")
def environment() -> jinja2.Environment:
    """Ten sam katalog szablonów co w aplikacji, bez bazy i bez serwera."""
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)),
        autoescape=True,
    )


def test_skorupa_niesie_kontenery_i_paczke(environment) -> None:
    """Widok, panel agenta, styl i skrypt — wszystko w jednym szablonie."""
    html = environment.get_template("app.html").render(title="Test", view="overview")
    assert 'id="root"' in html
    assert 'data-view="overview"' in html
    assert 'id="agent-root"' in html
    assert "/static/correction.js" in html
    assert "/static/correction.css" in html


def test_panel_stoi_poza_kolumna_tresci(environment) -> None:
    """Panel agenta jest kolumną wiersza, a nie elementem przewijanej treści.

    Gdyby siedział wewnątrz `.workspace-content`, odjeżdżałby w górę razem
    ze skanem klucza — a ma stać obok niego.
    """
    html = environment.get_template("app.html").render(title="Test", view="overview")
    content_end = html.index("</div>", html.index('id="root"'))
    assert html.index('id="agent-root"') > content_end
    assert html.index('class="workspace"') < html.index('id="root"')


def test_po_migracji_zostala_sama_skorupa() -> None:
    """Żaden widok nie jest już składany po stronie serwera.

    Szablon, który wróciłby do `templates/`, znaczyłby drugie miejsce, w którym
    powstaje ten sam ekran — a to jest stan, z którego właśnie wyszliśmy.
    """
    assert sorted(p.name for p in TEMPLATES.glob("*.html")) == ["app.html"]


@pytest.mark.integracyjny
@pytest.mark.parametrize(
    ("url", "view"),
    [
        ("/", "overview"),
        ("/task/{task}", "task"),
        ("/inspect", "inspect"),
        ("/inspect/health/asset_full_page", "inspectHealth"),
        ("/inspect/task", "inspectList"),
        ("/inspect/task/{task}", "inspectRecord"),
    ],
)
def test_kazdy_adres_oddaje_swoja_nazwe_widoku(url: str, view: str) -> None:
    """Front dobiera widok po `data-view`, więc to on musi być prawdziwy.

    Adres, który oddaje skorupę bez nazwy widoku albo z cudzą, kończy się pustą
    stroną — i to bez żadnego błędu w konsoli.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    pytest.importorskip("psycopg")
    from fastapi.testclient import TestClient

    from correction import db
    from correction.app import app

    with db.connect() as con, con.cursor() as cur:
        cur.execute("SELECT id FROM task ORDER BY id LIMIT 1")
        row = cur.fetchone()
    if row is None:
        pytest.skip("pusty korpus — nie ma zadania, na którym sprawdzić widoki")

    with TestClient(app) as client:
        response = client.get(url.format(task=row["id"]))
        assert response.status_code == 200, response.text[:200]
        assert f'data-view="{view}"' in response.text
        assert 'id="agent-root"' in response.text
