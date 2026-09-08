"""Baza wiedzy agenta: cięcie dokumentów na sekcje, szukanie, zasięg czytania kodu."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.tools import knowledge


def test_markdown_splits_on_headings_and_skips_fenced_hashes():
    raw = "wstęp\n\n# Tytuł\ntreść\n```\n# to nie nagłówek\n```\n## Pod\nreszta\n"
    sections = knowledge.sections_of_markdown("d.md", Path("d.md"), raw)
    assert [(s.heading, s.level) for s in sections] == [("", 0), ("Tytuł", 1), ("Pod", 2)]
    assert "# to nie nagłówek" in sections[1].text
    assert sections[2].text == "reszta"


def test_html_splits_on_headings_and_drops_script_style_nav():
    raw = ("<html><head><style>p{}</style><script>x()</script></head><body>"
           "<nav>spis</nav><h1>Baza</h1><p>Akapit &amp; treść.</p>"
           "<h2>Tabela task</h2><table><tr><td>kolumna</td><td>opis</td></tr></table>"
           "</body></html>")
    sections = knowledge.sections_of_html("d.html", Path("d.html"), raw)
    assert [s.heading for s in sections] == ["Baza", "Tabela task"]
    assert "Akapit & treść." in sections[0].text
    assert "spis" not in sections[0].text and "x()" not in sections[0].text
    assert "kolumna opis" in sections[1].text.replace("\n", " ")


def test_tokenize_folds_polish_and_adds_stem():
    tokens = knowledge.tokenize("Kryteriów Zadanie więzy")
    assert "kryteriow" in tokens and "kryter" in tokens
    assert "zadanie" in tokens and "zada" in tokens
    assert "wiezy" in tokens and "wiez" in tokens


def test_search_finds_the_section_about_sharp_constraints():
    """Pytanie po polsku, w odmianie — ma trafić w `CLAUDE.md`, nie w cokolwiek."""
    hits = knowledge.search("czy wolno poluzować więz unique w kryterium", 5)
    assert hits, "indeks pusty — dokumenty repozytorium nie zostały znalezione"
    assert any(h["doc"] == "CLAUDE.md" and "ostre" in h["heading"] for h in hits), hits


def test_read_section_by_heading_fragment_and_by_index():
    by_name = knowledge.read("CLAUDE.md", "Granica warstw")
    assert "C# nie otwiera PDF-a" in by_name["text"]
    ref = by_name["headings"][0]["ref"]
    by_index = knowledge.read("CLAUDE.md", ref.split("#")[1])
    assert by_index["text"] == by_name["text"]


def test_read_unknown_document_names_the_known_ones():
    with pytest.raises(ValueError, match=r"CLAUDE\.md"):
        knowledge.read("nope.md")


@pytest.mark.parametrize("path", [".env", ".env.example", "../cke-mirror/docs/DECYZJE.md",
                                  "ingest/.venv/pyvenv.cfg", "data/reports/x.txt",
                                  "ingest/uv.lock"])
def test_code_read_refuses_secrets_data_and_paths_outside_repo(path):
    with pytest.raises(ValueError):
        knowledge.read_code(path)


def test_code_read_returns_numbered_window_and_marks_truncation():
    out = knowledge.read_code("ingest/correction/db.py", 1, 5)
    assert out["start"] == 1 and out["end"] == 5 and out["truncated"] is True
    assert out["text"].splitlines()[0].startswith("    1  ")


def test_code_search_scans_only_allowed_files():
    out = knowledge.search_code("OPENAI_API_KEY=", "**/*")
    assert all(not m["path"].startswith(".env") for m in out["matches"])
    hit = knowledge.search_code(r"^def decide\(", "ingest/correction/*.py")
    assert [m["path"] for m in hit["matches"]] == ["ingest/correction/db.py"]
