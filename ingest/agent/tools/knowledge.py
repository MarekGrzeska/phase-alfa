"""Wiedza o projekcie: dokumenty z `docs/`, `CLAUDE.md`, `DECYZJE.md` i kod źródłowy.

Agent ma tłumaczyć, jak co działa, z tego, co napisano — nie z pamięci modelu.
Indeks jest ręczny (słowa + nagłówki, bez embeddingów): piętnaście plików nie
potrzebuje infrastruktury ani kosztu. Budowany przy pierwszym użyciu, odświeżany,
gdy zmieni się czas modyfikacji któregoś pliku.
"""

from __future__ import annotations

import html
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from agent import limits
from correction import inspector
from sciezki import KORZEN_REPO

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

REPO_DOCS = (
    "README.md", "CLAUDE.md", "ingest/README.md", "ingest/schema/README.md",
    "backend/README.md", "web/README.md",
)
REPO_DOC_GLOBS = ("docs/*.md", "docs/*.html", "docs/review/*.html")

# Dokumenty nadrzędne leżą w `cke-mirror`. Katalog z `.env`, a gdy go nie ma —
# repozytorium obok, bo tak leży u autora.
MIRROR_DOCS_ENV = "CKE_MIRROR_DOCS"
MIRROR_DOC_FILES = ("docs/DECYZJE.md", "docs/LICZBY.md", "docs/README.md",
                    "research/README.md", "research/schema/README.md")
MIRROR_DOC_GLOBS = ("docs/projekt-klucz/*.html",)

# Kod, którego agent nie ma czytać: sekrety, dane, zależności, artefakty buildów.
EXCLUDED_DIRS = frozenset({".git", "node_modules", ".venv", "data", ".task", "__pycache__",
                           "static", "bin", "obj", "dist", ".pytest_cache", ".ruff_cache",
                           ".vs", "TestResults"})
EXCLUDED_NAMES = re.compile(r"^\.env(\..*)?$|\.lock$|-lock\.yaml$|\.dll$|\.pdb$|\.png$")
MAX_FILE_BYTES = 2_000_000
MAX_CODE_LINES = 400
MAX_MATCHES = 50


@dataclass
class Section:
    doc: str
    heading: str
    level: int
    text: str
    index: int
    path: Path

    @property
    def ref(self) -> str:
        return f"{self.doc}#{self.index}"


@dataclass
class Index:
    sections: list[Section]
    stamp: tuple
    df: Counter = field(default_factory=Counter)
    tokens: list[Counter] = field(default_factory=list)
    heading_tokens: list[set[str]] = field(default_factory=list)


# ------------------------------------------------------------------ parsowanie

class _TextExtractor(HTMLParser):
    """HTML → sekcje po nagłówkach h1–h3; `script`, `style`, `nav` pomijane."""

    SKIP: ClassVar[frozenset[str]] = frozenset({"script", "style", "nav", "svg"})
    HEADINGS: ClassVar[dict[str, int]] = {"h1": 1, "h2": 2, "h3": 3}

    def __init__(self) -> None:
        super().__init__()
        self.sections: list[tuple[str, int, list[str]]] = [("", 0, [])]
        self._skip = 0
        self._heading: int | None = None
        self._heading_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.HEADINGS and not self._skip:
            self._heading = self.HEADINGS[tag]
            self._heading_text = []
        elif tag in ("p", "li", "tr", "br", "div", "section", "pre", "td", "th") \
                and not self._skip:
            self.sections[-1][2].append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.HEADINGS and self._heading is not None:
            title = " ".join("".join(self._heading_text).split())
            self.sections.append((title, self._heading, []))
            self._heading = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._heading is not None:
            self._heading_text.append(data)
        else:
            self.sections[-1][2].append(data)


def _clean(text: str) -> str:
    text = html.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def sections_of_html(doc: str, path: Path, raw: str) -> list[Section]:
    parser = _TextExtractor()
    parser.feed(raw)
    out: list[Section] = []
    for title, level, chunks in parser.sections:
        text = _clean("".join(chunks))
        if not text and not title:
            continue
        out.append(Section(doc, title, level, text, len(out), path))
    return out


_MD_HEADING = re.compile(r"^(#{1,3})\s+(.*?)\s*#*$")


def sections_of_markdown(doc: str, path: Path, raw: str) -> list[Section]:
    out: list[Section] = []
    title, level, lines = "", 0, []
    fenced = False
    for line in raw.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        found = None if fenced else _MD_HEADING.match(line)
        if found:
            text = _clean("\n".join(lines))
            if text or title:
                out.append(Section(doc, title, level, text, len(out), path))
            title, level, lines = found.group(2), len(found.group(1)), []
        else:
            lines.append(line)
    text = _clean("\n".join(lines))
    if text or title:
        out.append(Section(doc, title, level, text, len(out), path))
    return out


# ------------------------------------------------------------------ źródła

def mirror_root() -> Path | None:
    given = os.environ.get(MIRROR_DOCS_ENV)
    candidates = [Path(given)] if given else []
    candidates.append(KORZEN_REPO.parent / "cke-mirror")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def document_files() -> list[tuple[str, Path]]:
    """(etykieta, ścieżka) dla każdego dokumentu; etykieta jest adresem w `docs_read`."""
    found: list[tuple[str, Path]] = []
    for name in REPO_DOCS:
        path = KORZEN_REPO / name
        if path.is_file():
            found.append((name, path))
    for pattern in REPO_DOC_GLOBS:
        for path in sorted(KORZEN_REPO.glob(pattern)):
            found.append((path.relative_to(KORZEN_REPO).as_posix(), path))
    mirror = mirror_root()
    if mirror is not None:
        for name in MIRROR_DOC_FILES:
            path = mirror / name
            if path.is_file():
                found.append((f"cke-mirror/{name}", path))
        for pattern in MIRROR_DOC_GLOBS:
            for path in sorted(mirror.glob(pattern)):
                found.append((f"cke-mirror/{path.relative_to(mirror).as_posix()}", path))
    return found


# ------------------------------------------------------------------ indeks

_WORD = re.compile(r"[0-9a-ząćęłńóśźż_]+", re.I)
STOP = frozenset([
    "i", "w", "z", "na", "do", "nie", "jest", "sie", "to", "ze", "a", "o", "od", "po", "za",
    "ale", "jak", "co", "dla", "przy", "the", "of", "and", "or", "is", "are", "in", "for", "by",
])


def _fold(word: str) -> str:
    """Polskie znaki zdjęte, żeby `zadanie` i `zadanie` z ogonkami były jednym słowem."""
    normalized = unicodedata.normalize("NFKD", word.lower())
    return "".join(c for c in normalized if not unicodedata.combining(c)).replace("ł", "l")


def tokenize(text: str) -> list[str]:
    """Słowa + przybliżone tematy (pierwsze 4 i 6 liter) — polska odmiana bez stemmera.

    `więz`, `więzy`, `więzów` spotykają się na `wiez`; `kryterium`, `kryteria`,
    `kryteriów` na `kryter`. Zgrubne celowo: indeks ma znaleźć sekcję, a nie
    ocenić semantykę — a fałszywe trafienia gasi waga idf.
    """
    out: list[str] = []
    for word in _WORD.findall(text):
        folded = _fold(word)
        if folded in STOP or len(folded) < 2:
            continue
        out.append(folded)
        for length in (4, 6):
            if len(folded) > length:
                out.append(folded[:length])
    return out


_INDEX: Index | None = None


def build_index() -> Index:
    files = document_files()
    sections: list[Section] = []
    for doc, path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".html":
            sections.extend(sections_of_html(doc, path, raw))
        else:
            sections.extend(sections_of_markdown(doc, path, raw))
    index = Index(sections, tuple((str(p), p.stat().st_mtime_ns) for _, p in files))
    for section in sections:
        words = Counter(tokenize(section.text))
        index.tokens.append(words)
        index.heading_tokens.append(set(tokenize(section.heading)))
        index.df.update(set(words) | index.heading_tokens[-1])
    return index


def index() -> Index:
    global _INDEX
    files = document_files()
    stamp = tuple((str(p), p.stat().st_mtime_ns) for _, p in files)
    if _INDEX is None or _INDEX.stamp != stamp:
        _INDEX = build_index()
    return _INDEX


def search(query: str, limit: int = 8) -> list[dict]:
    idx = index()
    terms = set(tokenize(query))
    if not terms:
        return []
    total = max(1, len(idx.sections))
    scored: list[tuple[float, Section]] = []
    for section, words, heading in zip(idx.sections, idx.tokens, idx.heading_tokens,
                                       strict=True):
        score = 0.0
        for term in terms:
            idf = math.log(1 + total / (1 + idx.df.get(term, 0)))
            tf = words.get(term, 0)
            if tf:
                score += idf * (1 + math.log(tf))
            if term in heading:
                score += 3 * idf
            if term in tokenize(section.doc):
                score += idf
        if score > 0:
            scored.append((score, section))
    scored.sort(key=lambda pair: -pair[0])
    return [{"ref": s.ref, "doc": s.doc, "heading": s.heading, "score": round(score, 2),
             "snippet": snippet(s.text, terms)} for score, s in scored[:limit]]


def snippet(text: str, terms: set[str], width: int = 300) -> str:
    lowered = _fold(text)
    start = 0
    for term in sorted(terms, key=len, reverse=True):
        at = lowered.find(term)
        if at >= 0:
            start = max(0, at - width // 3)
            break
    piece = text[start:start + width]
    return ("…" if start else "") + " ".join(piece.split()) + ("…" if start + width < len(text)
                                                               else "")


def read(doc: str, heading: str | None = None, max_chars: int = 12_000) -> dict:
    idx = index()
    own = [s for s in idx.sections if s.doc == doc]
    if not own:
        known = sorted({s.doc for s in idx.sections})
        raise ValueError(f"nie ma dokumentu {doc!r}; znane: {', '.join(known)}")
    if heading is not None:
        wanted = _fold(heading)
        chosen = [s for s in own if wanted in _fold(s.heading)]
        if heading.isdigit():
            chosen = [s for s in own if s.index == int(heading)] or chosen
        if not chosen:
            raise ValueError(f"w {doc} nie ma nagłówka pasującego do {heading!r}; "
                             f"nagłówki: {', '.join(s.heading for s in own if s.heading)}")
        own = chosen[:1]
    text = "\n\n".join(f"{'#' * max(1, s.level)} {s.heading}\n{s.text}" if s.heading else s.text
                       for s in own)
    body, truncated = limits.clip_text(text, max_chars)
    out = {"doc": doc, "text": body, "truncated": truncated,
           "headings": [{"ref": s.ref, "heading": s.heading} for s in own if s.heading]}
    if truncated:
        out["hint"] = "Dokument ucięty — podaj `heading`, żeby przeczytać jedną sekcję."
    return out


# ------------------------------------------------------------------ kod

def _allowed(path: Path) -> bool:
    parts = path.relative_to(KORZEN_REPO).parts
    return not (any(p in EXCLUDED_DIRS for p in parts) or EXCLUDED_NAMES.search(path.name))


def resolve_in_repo(relative: str) -> Path:
    candidate = (KORZEN_REPO / relative).resolve()
    if not candidate.is_relative_to(KORZEN_REPO):
        raise ValueError(f"ścieżka wychodzi poza repozytorium: {relative}")
    if not _allowed(candidate):
        raise ValueError(f"ta ścieżka jest poza zasięgiem agenta: {relative}")
    return candidate


def search_code(pattern: str, glob: str = "**/*", limit: int = MAX_MATCHES) -> dict:
    try:
        regex = re.compile(pattern, re.I)
    except re.error as e:
        raise ValueError(f"złe wyrażenie regularne: {e}") from e
    matches: list[dict] = []
    scanned = 0
    for path in sorted(KORZEN_REPO.glob(glob)):
        if not path.is_file() or not _allowed(path) or path.stat().st_size > MAX_FILE_BYTES:
            continue
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append({"path": path.relative_to(KORZEN_REPO).as_posix(),
                                "line": number, "text": line.strip()[:limits.MAX_CELL]})
                if len(matches) > limit:
                    return {"matches": matches[:limit], "truncated": True, "scanned": scanned,
                            "hint": "Więcej trafień niż limit — zawęź `glob` albo wzorzec."}
    return {"matches": matches, "truncated": False, "scanned": scanned}


def read_code(relative: str, start: int = 1, end: int | None = None) -> dict:
    path = resolve_in_repo(relative)
    if not path.is_file():
        raise ValueError(f"nie ma pliku: {relative}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    first = max(1, int(start))
    last = min(len(lines), int(end) if end else first + MAX_CODE_LINES - 1)
    last = min(last, first + MAX_CODE_LINES - 1)
    body = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(first, last + 1))
    text, truncated = limits.clip_text(body, 20_000)
    return {"path": path.relative_to(KORZEN_REPO).as_posix(), "start": first, "end": last,
            "total_lines": len(lines), "text": text,
            "truncated": truncated or last < len(lines)}


# ------------------------------------------------------------------ narzędzia

def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def docs_search(query: str, limit: int = 8) -> dict:
        """Szukaj w dokumentacji projektu: plany, przewodnik po bazie, przegląd ingestu,
        stan prac, `CLAUDE.md`, `DECYZJE.md`, `LICZBY.md`, know-how parsera.

        Wynik: sekcje z `ref` (do `docs_read`), nagłówkiem i urywkiem. Słowa kluczowe
        po polsku działają najlepiej; odmiana nie przeszkadza.
        """
        return {"results": search(query, max(1, min(int(limit), 25))),
                "documents": len({s.doc for s in index().sections})}

    @mcp.tool(annotations=READ_ONLY)
    def docs_read(doc: str, heading: str | None = None) -> dict:
        """Przeczytaj dokument albo jedną jego sekcję. `doc` jak w wyniku `docs_search`
        (np. `docs/database-guide.html`, `CLAUDE.md`, `cke-mirror/docs/DECYZJE.md`);
        `heading` to fragment nagłówka albo numer sekcji z `ref`."""
        return read(doc, heading)

    @mcp.tool(annotations=READ_ONLY)
    def docs_list() -> dict:
        """Spis dokumentów w bazie wiedzy z nagłówkami sekcji."""
        docs: dict[str, list[str]] = {}
        for section in index().sections:
            docs.setdefault(section.doc, [])
            if section.heading:
                docs[section.doc].append(section.heading)
        return {"documents": [{"doc": doc, "headings": headings[:40]}
                              for doc, headings in docs.items()]}

    @mcp.tool(annotations=READ_ONLY)
    def code_search(pattern: str, glob: str = "**/*.py", limit: int = MAX_MATCHES) -> dict:
        """Grep po kodzie repozytorium (wyrażenie regularne, bez rozróżniania wielkości
        liter). `glob` względem korzenia repo, np. `ingest/**/*.py`, `**/*.tsx`,
        `**/*.sql`. `.env`, `data/`, `node_modules`, `.venv` są poza zasięgiem."""
        return search_code(pattern, glob, max(1, min(int(limit), 200)))

    @mcp.tool(annotations=READ_ONLY)
    def code_read(path: str, start: int = 1, end: int | None = None) -> dict:
        """Przeczytaj plik z repozytorium (ścieżka względem korzenia, np.
        `ingest/correction/db.py`), najwyżej 400 linii naraz — podaj `start`/`end`."""
        return read_code(path, start, end)

    @mcp.tool(annotations=READ_ONLY)
    def explain_column(table: str, column: str) -> dict:
        """Skąd bierze się wartość w kolumnie: który proces ją pisze, co znaczy,
        co mówi o niej przewodnik po bazie."""
        written_by = inspector.source_of(table, column)
        if table not in inspector.SOURCES and column != "id":
            raise ValueError(f"nie znam tabeli {table!r}; znane: "
                             f"{', '.join(inspector.SOURCES)}")
        guide = [r for r in search(f"{table} {column}", 6)
                 if r["doc"] == "docs/database-guide.html"]
        return {"table": table, "column": column, "written_by": written_by,
                "table_note": inspector.TABLE_NOTES.get(table, ""),
                "guide": guide[:3]}

    @mcp.tool(annotations=READ_ONLY)
    def explain_check(key: str) -> dict:
        """Po co istnieje kontrola zdrowia danych i co zrobić z jej trafieniami."""
        check = inspector.CHECK_BY_KEY.get(key)
        if check is None:
            raise ValueError(f"nie ma takiej kontroli: {key}; znane: "
                             f"{', '.join(inspector.CHECK_BY_KEY)}")
        return {"key": key, "title": check.title, "why": check.why,
                "severity": check.severity, "table": check.table,
                "sql": " ".join(check.query.split()),
                "filtered_in_python": check.keep is not None,
                "url": f"/inspect/health/{key}"}
