"""Budowniczy adresów agenta: każdy widok odpowiada trasie ekranu korekty.

Model nie skleja adresów sam — dostaje je stąd. Więc to tutaj musi pęknąć,
gdy ktoś zmieni trasę w `correction/app.py` albo składnię filtrów inspektora.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent import urls

APP = Path(__file__).resolve().parents[1] / "correction" / "app.py"
ROUTE = re.compile(r'@app\.get\("([^"]+)"')


def app_routes() -> set[str]:
    return set(ROUTE.findall(APP.read_text(encoding="utf-8")))


def route_pattern(route: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\{[a-z_]+\}", r"[^/]+", route) + "$")


EXAMPLES = {
    "overview": ({"view": "overview", "scope": {"year": 2025, "code": "OMAP"},
                  "status": "pending"}, "/?status=pending&year=2025&code=OMAP"),
    "next": ({"view": "next", "scope": {"variant": "100"}}, "/next?variant=100"),
    "task": ({"view": "task", "id": 42, "page": 7, "scope": {"year": 2025}},
             "/task/42?page=7&year=2025"),
    "inspect": ({"view": "inspect"}, "/inspect"),
    "inspect_list": ({"view": "inspect_list", "table": "task",
                      "filters": {"kind": "open_short", "max_points__gt": 2,
                                  "reviewed_at__null": None},
                      "sort": "number", "direction": "desc", "page": 2, "all_columns": True},
                     "/inspect/task?kind=open_short&max_points__gt=2&reviewed_at__null="
                     "&_sort=number&_dir=desc&_cols=all&_page=2"),
    "inspect_record": ({"view": "inspect_record", "table": "asset", "id": 9, "pdf_page": 3},
                       "/inspect/asset/9?_pdfpage=3"),
    "health": ({"view": "health", "key": "asset_full_page"}, "/inspect/health/asset_full_page"),
    "document_pdf": ({"view": "document_pdf", "document_id": 5, "page": 12},
                     "/inspect/document/5.pdf#page=12"),
    "document_page": ({"view": "document_page", "document_id": 5, "page": 12},
                      "/inspect/document/5/page/12.png"),
}


def test_every_view_has_an_example():
    assert set(EXAMPLES) == set(urls.VIEWS)


@pytest.mark.parametrize("view", sorted(EXAMPLES))
def test_view_builds_expected_url(view):
    target, expected = EXAMPLES[view]
    assert urls.build(target) == expected


@pytest.mark.parametrize("view", sorted(EXAMPLES))
def test_every_url_matches_a_route_in_app(view):
    """Adres bez trasy to pusta strona bez błędu — dokładnie to, czego nie chcemy."""
    path = urls.build(EXAMPLES[view][0]).split("?")[0].split("#")[0]
    assert any(route_pattern(route).match(path) for route in app_routes()), path


def test_unknown_view_is_named():
    with pytest.raises(urls.BadTarget, match="nieznany widok"):
        urls.build({"view": "nope"})


@pytest.mark.parametrize("target", [
    {"view": "task"},
    {"view": "task", "id": "42"},
    {"view": "task", "id": 0},
    {"view": "inspect_record", "table": "task;drop", "id": 1},
    {"view": "inspect_list", "table": "task", "filters": {"kind__nope": "x"}},
    {"view": "inspect_list", "table": "task", "filters": {"kind or 1=1": "x"}},
    {"view": "health", "key": "nope"},
])
def test_bad_target_is_rejected_before_any_url(target):
    with pytest.raises(urls.BadTarget):
        urls.build(target)


def test_empty_scope_adds_nothing():
    assert urls.build({"view": "task", "id": 1, "scope": {"year": "", "code": None}}) == "/task/1"
