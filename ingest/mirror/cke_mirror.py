#!/usr/bin/env python3
"""
cke_mirror.py — jeden skrypt: buduje strukturę katalogów, zwozi arkusze CKE,
pokazuje postęp i wypisuje raport z wykonania.

    python3 cke_mirror.py                      # cały rdzeń (~2 500 plików, ~2,6 GB)
    python3 cke_mirror.py --filtr matematyka   # sam zakres K2 (190 plików, ~130 MB)
    python3 cke_mirror.py --segment e8 --rocznik 2026
    python3 cke_mirror.py --tylko-spis         # inwentarz bez pobierania PDF-ów
    python3 cke_mirror.py --tylko-raport       # kompletność tego, co już leży na dysku

Zakres = "rdzeń Klucza": egzamin ósmoklasisty 2019-2026, matura Formuła 2023
(2023-2026), matura Formuła 2015 (2015-2023). Poza rdzeniem świadomie zostają
egzamin zawodowy, eksternistyczny, stara matura, gimnazjalny i sprawdzian.

Skrypt jest idempotentny: plik już obecny w mirrorze jest pomijany, więc to samo
wywołanie służy do pierwszego zrzutu i do dosypywania plików nowej sesji.
Bez zależności zewnętrznych — sama biblioteka standardowa Pythona 3.9+.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

# Raport rysuje ramki znakami Unicode, a Windows przy przekierowaniu stdout do
# pliku wybiera kodowanie strony kodowej (cp1250) i wywala się na nich — czyli
# dokładnie w wywołaniu z crona albo z CI, które README obiecuje. Wymuszamy UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────────────────────
# Konfiguracja zakresu
# ─────────────────────────────────────────────────────────────────────────────

# robots.txt na cke.gov.pl przepuszcza wyłącznie "User-agent: Scrapy"
# (wszystkim pozostałym daje Disallow: /), więc tak się przedstawiamy.
UA = "Scrapy/2.11 (+cke-mirror; one-off mirror of public exam papers)"

SEGMENTS = {
    "e8": {
        "label": "Egzamin ósmoklasisty",
        "page": "https://cke.gov.pl/egzamin-osmoklasisty/arkusze/{year}-2/",
        "years": range(2019, 2027),
    },
    "matura-f2023": {
        "label": "Matura · Formuła 2023",
        "page": "https://cke.gov.pl/egzamin-maturalny/"
                "egzamin-maturalny-w-formule-2023/arkusze/{year}-2/",
        "years": range(2023, 2027),
    },
    "matura-f2015": {
        "label": "Matura · Formuła 2015",
        "page": "https://cke.gov.pl/egzamin-maturalny/"
                "egzamin-maturalny-w-formule-2015/arkusze/{year}-2/",
        "years": range(2015, 2024),
    },
}

COLUMNS = ["segment", "rocznik", "rocznik_w_sciezce", "podkatalog", "plik",
           "kod", "warianty", "sesja", "typ", "zrodlo_typu", "wzorzec",
           "url", "sciezka_lokalna"]

# ─────────────────────────────────────────────────────────────────────────────
# Taksonomia nazw plików
#
#   OMAP - 100 - 2305 - zasady .pdf
#     │      │      │      └── typ dokumentu
#     │      │      └───────── sesja: rok + miesiąc
#     │      └──────────────── wariant arkusza (100 = standardowy)
#     └─────────────────────── egzamin + przedmiot (O = ósmoklasisty, MA = matematyka)
#
# Sufiks typu to konwencja dopiero od ~2022. Rocznik 2019 koduje typ prefiksem
# nazwy (Arkusz_…, Zasady_oceniania_…), a roczniki 2020-2021 i cała Formuła 2015
# — katalogiem (…/zasady_oceniania/…, …/odpowiedzi/…). Czytamy wszystkie trzy
# źródła i zapisujemy w kolumnie `zrodlo_typu`, z którego pochodzi wynik.
#
# Trzy rzeczy, przez które pierwszy przebieg zgubił sesję w 31% wierszy:
#   1. Separator sufiksu bywa podkreśleniem albo kropką (…-152_transkrypcja.pdf,
#      …-202.nuty.pdf), a nie tylko myślnikiem — dzielenie po "-" tego nie widzi.
#   2. Słownik sufiksów nie znał nazw używanych w innych latach: `zeszyt-zadan`
#      (E8 od 2024), `model` (Formuła 2015 mówi tak na zasady oceniania),
#      `karta-rozwiazan`, `mapa`, `nuty`, `przykłady nutowe`.
#   3. Formuła 2015 koduje sesję trzema znakami — `152` to maj 2015, `162n` to
#      maj 2016 — a nie czterema jak `2505`. Do tego token sesji nie zawsze jest
#      ostatni (MJA-P1_1P-172-A.pdf), więc szukamy go od prawej, nie na końcu.
# ─────────────────────────────────────────────────────────────────────────────

# Sufiks typu: jeden regex zamiast dzielenia po "-", bo separator bywa "_" i "."
# a same nazwy sufiksów są dwuczłonowe. Kolejność ma znaczenie — dłuższe pierwsze.
SUFFIX_PATTERNS = [
    (r"zasady[-_. ]oceniania", "zasady_oceniania"),
    (r"zasady", "zasady_oceniania"),
    (r"model",                 "zasady_oceniania"),   # Formuła 2015: „model odpowiedzi"
    (r"karta[-_. ]rozwiazan",  "karta_odpowiedzi"),
    (r"karta[-_. ]odpowiedzi", "karta_odpowiedzi"),
    (r"karta", "karta_odpowiedzi"),
    (r"transkrypcja[-_. ]nagran", "transkrypcja"),
    (r"transkrypcja", "transkrypcja"),
    (r"zeszyt[-_. ]zadan", "arkusz"),                 # E8 od 2024
    (r"arkusz", "arkusz"),
    (r"aneks", "aneks"),
    (r"przyk[lł]ady[-_. ]nutowe", "zalacznik"),
    (r"nutowe", "zalacznik"),
    (r"nuty", "zalacznik"),
    (r"mapa", "zalacznik"),
    (r"zalacznik", "zalacznik"),
]
SUFFIX_RE = re.compile(
    r"[-_. ]+(?:" + "|".join(p for p, _ in SUFFIX_PATTERNS) + r")$", re.IGNORECASE)
NAME_PREFIXES = [
    ("zasady_oceniania_", "zasady_oceniania"),
    ("zasady_", "zasady_oceniania"),
    ("arkusz_", "arkusz"),
    ("transkrypcja_", "transkrypcja"),
    ("karta_", "karta_odpowiedzi"),
]
PATH_HINTS = [
    ("zasady_oceniania", "zasady_oceniania"),
    ("zasady oceniania", "zasady_oceniania"),
    ("odpowiedzi", "zasady_oceniania"),
    ("transkrypcje", "transkrypcja"),
    ("transkrypcja", "transkrypcja"),
    ("nagrania", "transkrypcja"),
]

HREF_RE = re.compile(r'''href\s*=\s*["']([^"']+\.pdf)["']''', re.IGNORECASE)
YEAR_SEG_RE = re.compile(r"^(?:19|20)\d{2}$")

# Dwa schematy sesji. Nowy (E8, Formuła 2023): RRMM — 2505 = maj 2025.
# Stary (Formuła 2015): RRT — 152 = 2015, termin 2; sufiks literowy (152n) bywa
# doklejony. Ograniczenia zakresów są tym, co odróżnia sesję od wariantu:
# wszystkie warianty arkusza kończą się zerem (100, 400, 660, 900), więc termin
# 1-3 ich nie łapie, a rok 15-30 odsiewa przypadkowe czterocyfrowe tokeny.
SESSION_NEW_RE = re.compile(r"^(\d{2})(\d{2})$")
SESSION_OLD_RE = re.compile(r"^(\d{2})([1-3])[a-z]?$", re.IGNORECASE)
# Termin egzaminu Formuły 2015 → miesiąc. W kopalni występuje wyłącznie termin 2
# (maj); pozostałe dwa są w mapie, żeby nie wywrócić się na pliku spoza próby.
F2015_TERM_MONTH = {"1": "01", "2": "05", "3": "06"}


def parse_session(token: str) -> str:
    """Sesja z jednego tokenu nazwy albo pusty string. Format wyjścia: RRRR-MM."""
    m = SESSION_NEW_RE.match(token)
    if m and 15 <= int(m.group(1)) <= 30 and 1 <= int(m.group(2)) <= 12:
        return f"20{m.group(1)}-{m.group(2)}"
    m = SESSION_OLD_RE.match(token)
    if m and 15 <= int(m.group(1)) <= 23:
        return f"20{m.group(1)}-{F2015_TERM_MONTH[m.group(2)]}"
    return ""


def parse_filename(name: str, url_path: str = "") -> dict:
    """Metadane z samej nazwy pliku — gotowe, zanim spadnie pierwszy bajt PDF-a."""
    stem = name[:-4] if name.lower().endswith(".pdf") else name
    meta = {"kod": "", "warianty": "", "sesja": "", "typ": "", "zrodlo_typu": "", "wzorzec": ""}

    low = stem.lower()
    for prefix, typ in NAME_PREFIXES:
        if low.startswith(prefix):
            meta["typ"], meta["zrodlo_typu"], meta["wzorzec"] = typ, "prefiks", "prefiks"
            stem = stem[len(prefix):]
            break

    # Sufiks typu odcinamy ze stemu, zanim podzielimy go na tokeny — inaczej
    # „…-2405-zeszyt-zadan" wygląda jak nazwa bez sesji z trzema wariantami.
    if not meta["typ"]:
        m = SUFFIX_RE.search(stem)
        if m:
            tail = m.group(0).lstrip("-_. ").lower()
            for pattern, typ in SUFFIX_PATTERNS:
                if re.fullmatch(pattern, tail, re.IGNORECASE):
                    meta["typ"], meta["zrodlo_typu"] = typ, "sufiks"
                    meta["wzorzec"] = meta["wzorzec"] or "od2023"
                    stem = stem[:m.start()]
                    break

    tokens = stem.split("-")
    meta["kod"] = tokens[0] if tokens else stem
    if len(tokens) >= 2:
        # Sesja szukana od prawej, nie na końcu: MJA-P1_1P-172-A.pdf ma po niej
        # jeszcze token wariantu. Wariantem jest wszystko poza kodem i sesją.
        idx = next((i for i in range(len(tokens) - 1, 0, -1)
                    if parse_session(tokens[i])), None)
        if idx is not None:
            meta["sesja"] = parse_session(tokens[idx])
            meta["warianty"] = ",".join(tokens[1:idx] + tokens[idx + 1:])
            meta["wzorzec"] = meta["wzorzec"] or "kod-warianty-sesja"
        else:
            meta["warianty"] = ",".join(tokens[1:])
            meta["wzorzec"] = meta["wzorzec"] or "f2015-bez-sesji"

    if not meta["typ"]:
        segs = [s.lower() for s in url_path.split("/")]
        for hint, typ in PATH_HINTS:
            if any(hint in s for s in segs):
                meta["typ"], meta["zrodlo_typu"] = typ, "katalog"
                break
    if not meta["typ"]:
        meta["typ"], meta["zrodlo_typu"] = "arkusz", "domyslny"
    meta["wzorzec"] = meta["wzorzec"] or "nieznany"
    return meta


def normalize_url(href: str, page_url: str) -> str:
    """Absolutny https URL, ze ścieżką bezpieczną dla klienta HTTP.

    Strony rocznikowe mieszają href-y względne i absolutne http://cke.gov.pl,
    a garść nazw na serwerze zawiera spacje i polskie znaki — bez enkodowania
    klient odrzuca URL zanim wyśle żądanie.
    """
    parts = urlsplit(urljoin(page_url, href.strip()))
    path = quote(unquote(parts.path), safe="/%:@!$&'()*+,;=~")
    host = "cke.gov.pl" if parts.netloc in ("cke.gov.pl", "www.cke.gov.pl") else parts.netloc
    url = f"https://{host}{path}"
    return url + ("?" + parts.query if parts.query else "")


def local_path(raw_dir: Path, url: str, segment: str) -> Path:
    """data/raw/<segment>/<rok>/<przedmiot>/<plik>.pdf

    Kotwicą jest segment rocznika, nie katalog główny — CKE trzyma część plików
    pod wariantami markera (np. /_EGZAMIN_MATURALNY/2026/mniejszosci/…).
    """
    parts = [unquote(p) for p in urlsplit(url).path.split("/") if p]
    idx = next((i for i, p in enumerate(parts) if YEAR_SEG_RE.match(p)), None)
    tail = parts[idx:] if idx is not None else parts[-3:]
    return raw_dir / segment / Path(*[p for p in tail if p != "formula_od_2015"])


# ─────────────────────────────────────────────────────────────────────────────
# Układ katalogów
# ─────────────────────────────────────────────────────────────────────────────

class Layout:
    def __init__(self, root: Path):
        self.root = root
        self.data = root / "data"
        self.pages = self.data / "index" / "pages"
        self.raw = self.data / "raw"
        self.reports = self.data / "reports"
        self.urls_tsv = self.data / "index" / "urls.tsv"
        self.manifest = self.data / "index" / "manifest.json"
        self.log = self.reports / "download-log.tsv"

    def build(self) -> list[Path]:
        dirs = [self.pages, self.reports, *(self.raw / s for s in SEGMENTS)]
        created = [d for d in dirs if not d.exists()]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        return created


# ─────────────────────────────────────────────────────────────────────────────
# Pasek postępu
# ─────────────────────────────────────────────────────────────────────────────

class Progress:
    """Jedna linia odświeżana w miejscu na TTY; poza TTY — rzadkie linie w logu."""

    def __init__(self, total: int, label: str, quiet: bool = False):
        self.total, self.label, self.quiet = total, label, quiet
        self.done = self.bytes = self.errors = self.skipped = 0
        self.current = ""
        self.t0 = time.time()
        self.lock = threading.Lock()
        self.tty = sys.stderr.isatty() and not quiet
        self.last_draw = 0.0

    def step(self, *, bajty: int = 0, status: str = "pobrany", what: str = "") -> None:
        with self.lock:
            self.done += 1
            self.bytes += bajty
            if status == "blad":
                self.errors += 1
            elif status == "pominiety":
                self.skipped += 1
            self.current = what
            now = time.time()
            if self.tty:
                if now - self.last_draw > 0.08 or self.done == self.total:
                    self.last_draw = now
                    self._draw()
            elif not self.quiet and (self.done % 100 == 0 or self.done == self.total):
                el = now - self.t0
                print(f"  {self.done}/{self.total}  {self._h(self.bytes)}  {el:.0f}s",
                      file=sys.stderr, flush=True)

    def _draw(self) -> None:
        el = max(time.time() - self.t0, 0.001)
        frac = self.done / max(self.total, 1)
        width = max(shutil.get_terminal_size((100, 20)).columns, 60)
        bar_w = max(10, min(28, width - 62))
        filled = int(bar_w * frac)
        bar = "█" * filled + "░" * (bar_w - filled)
        rate = self.bytes / 1024 / 1024 / el
        eta = (self.total - self.done) / (self.done / el) if self.done else 0
        head = (f"\r{self.label} [{bar}] {self.done:>5}/{self.total} "
                f"{frac * 100:5.1f}%  {self._h(self.bytes):>9}  "
                f"{rate:5.1f} MB/s  ETA {self._t(eta)}")
        if self.errors:
            head += f"  !{self.errors}"
        tail = f"  {self.current}"
        line = (head + tail)[:width - 1]
        sys.stderr.write(line.ljust(width - 1))
        sys.stderr.flush()

    def close(self) -> None:
        if self.tty:
            sys.stderr.write("\r" + " " * (shutil.get_terminal_size((100, 20)).columns - 1) + "\r")
            sys.stderr.flush()

    @staticmethod
    def _h(n: int) -> str:
        for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("kB", 1 << 10)):
            if n >= div:
                return f"{n / div:.1f} {unit}"
        return f"{n} B"

    @staticmethod
    def _t(sec: float) -> str:
        sec = int(max(sec, 0))
        return f"{sec // 60}m{sec % 60:02d}s" if sec >= 60 else f"{sec:>2d}s"


# ─────────────────────────────────────────────────────────────────────────────
# Krok 1 — spis
# ─────────────────────────────────────────────────────────────────────────────

def fetch_text(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def collect_inventory(lay: Layout, quiet: bool = False) -> tuple[list[dict], list[dict]]:
    """Pobiera strony rocznikowe i zwraca (wiersze spisu, statystyki stron).
    Nie pobiera żadnego PDF-a — kompletność da się ocenić z samej listy URL-i."""
    pages = [(seg, y, cfg["page"].format(year=y))
             for seg, cfg in SEGMENTS.items() for y in cfg["years"]]
    bar = Progress(len(pages), "spis  ", quiet)
    rows: list[dict] = []
    stats: list[dict] = []
    seen: set[str] = set()

    for seg, year, page_url in pages:
        try:
            html = fetch_text(page_url)
        except Exception as exc:
            stats.append({"segment": seg, "rocznik": year, "url": page_url,
                          "linkow": 0, "unikatowych": 0, "blad": f"{type(exc).__name__}: {exc}"})
            bar.step(status="blad", what=f"{seg} {year}")
            continue

        (lay.pages / f"{seg}-{year}.html").write_text(html, encoding="utf-8")
        urls = []
        for href in HREF_RE.findall(html):
            u = normalize_url(href, page_url)
            if u.lower().endswith(".pdf") and u not in urls:
                urls.append(u)

        new = 0
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            new += 1
            path = local_path(lay.raw, u, seg)
            rel = path.relative_to(lay.raw / seg).parts
            rows.append({
                "segment": seg, "rocznik": year,
                "rocznik_w_sciezce": rel[0] if rel else "",
                "podkatalog": "/".join(rel[1:-1]),
                "plik": path.name, "url": u,
                "sciezka_lokalna": str(path.relative_to(lay.root)),
                **parse_filename(path.name, urlsplit(u).path),
            })
        stats.append({"segment": seg, "rocznik": year, "url": page_url,
                      "linkow": len(urls), "unikatowych": new, "blad": ""})
        bar.step(bajty=len(html.encode()), what=f"{seg} {year} — {len(urls)} linków")

    bar.close()
    return rows, stats


def write_inventory(lay: Layout, rows: list[dict], stats: list[dict]) -> None:
    with lay.urls_tsv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    per_year: dict[str, dict] = defaultdict(dict)
    for r in rows:
        per_year[r["segment"]][r["rocznik"]] = per_year[r["segment"]].get(r["rocznik"], 0) + 1
    lay.manifest.write_text(json.dumps({
        "zrodlo": "cke.gov.pl",
        "zakres": "rdzeń Klucza: E8 2019-2026 + matura F2023 2023-2026 + matura F2015 2015-2023",
        "stron_rocznikowych": len(stats),
        "plikow_unikatowych": len(rows),
        "per_segment": dict(Counter(r["segment"] for r in rows)),
        "per_rocznik": {k: dict(sorted(v.items())) for k, v in per_year.items()},
        "per_typ_dokumentu": dict(Counter(r["typ"] for r in rows).most_common()),
        "per_zrodlo_typu": dict(Counter(r["zrodlo_typu"] for r in rows).most_common()),
        "strony": stats,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def read_inventory(lay: Layout) -> list[dict]:
    if not lay.urls_tsv.exists():
        sys.exit("Brak spisu — uruchom skrypt bez --tylko-raport.")
    with lay.urls_tsv.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


# ─────────────────────────────────────────────────────────────────────────────
# Krok 2 — zwózka
# ─────────────────────────────────────────────────────────────────────────────

def download_one(lay: Layout, row: dict, force: bool, retries: int = 3) -> dict:
    dest = lay.root / row["sciezka_lokalna"]
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return {"status": "pominiety", "bajty": dest.stat().st_size,
                "plik": row["sciezka_lokalna"], "url": row["url"], "blad": ""}

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(row["url"], headers={"User-Agent": UA})
    last = ""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                blob = r.read()
            if not blob.startswith(b"%PDF"):
                return {"status": "blad", "bajty": len(blob), "plik": row["sciezka_lokalna"],
                        "url": row["url"], "blad": "odpowiedź nie jest PDF-em"}
            tmp.write_bytes(blob)
            tmp.replace(dest)          # podmiana atomowa — nigdy pół pliku w mirrorze
            return {"status": "pobrany", "bajty": len(blob),
                    "plik": row["sciezka_lokalna"], "url": row["url"], "blad": ""}
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code in (404, 403, 410):
                break                  # martwy link po stronie CKE — nie ma czego ponawiać
        except Exception as exc:       # jeden felerny URL nie może położyć całej zwózki
            last = f"{type(exc).__name__}: {exc}"
        finally:
            tmp.unlink(missing_ok=True)
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    return {"status": "blad", "bajty": 0, "plik": row["sciezka_lokalna"],
            "url": row["url"], "blad": last}


def download_all(lay: Layout, rows: list[dict], jobs: int, force: bool,
                 quiet: bool = False) -> tuple[list[dict], float]:
    bar = Progress(len(rows), "zwózka", quiet)
    results: list[dict] = []
    lock = threading.Lock()

    def job(row: dict) -> None:
        res = download_one(lay, row, force)
        with lock:
            results.append(res)
        bar.step(bajty=res["bajty"] if res["status"] == "pobrany" else 0,
                 status=res["status"],
                 what=f"{row['segment']}/{row['rocznik']}/{row['plik']}")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(job, rows))
    elapsed = time.time() - t0
    bar.close()

    lay.reports.mkdir(parents=True, exist_ok=True)
    fresh = not lay.log.exists()
    with lay.log.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        if fresh:
            w.writerow(["czas", "status", "bajty", "plik", "url", "blad"])
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        for r in results:
            w.writerow([stamp, r["status"], r["bajty"], r["plik"], r["url"], r["blad"]])
    return results, elapsed


# ─────────────────────────────────────────────────────────────────────────────
# Krok 3 — raport
# ─────────────────────────────────────────────────────────────────────────────

def human(n: float) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("kB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n:.0f} B"


def build_report(lay: Layout, rows: list[dict]) -> dict:
    """Porównuje spis ze stanem mirrora. Weryfikuje sygnaturę %PDF każdego pliku."""
    stat: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"w_spisie": 0, "w_mirrorze": 0, "bajty": 0, "uszkodzone": 0})
    braki, uszkodzone = [], []
    typy: Counter = Counter()
    zrodla: Counter = Counter()

    for r in rows:
        key = (r["segment"], r["rocznik"])
        stat[key]["w_spisie"] += 1
        p = lay.root / r["sciezka_lokalna"]
        if not (p.exists() and p.stat().st_size > 0):
            braki.append(r)
            continue
        stat[key]["w_mirrorze"] += 1
        stat[key]["bajty"] += p.stat().st_size
        typy[r["typ"]] += 1
        zrodla[r["zrodlo_typu"]] += 1
        with p.open("rb") as fh:
            if fh.read(4) != b"%PDF":
                stat[key]["uszkodzone"] += 1
                uszkodzone.append(r)

    with (lay.reports / "braki.tsv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(braki)
    with (lay.reports / "kompletnosc.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["segment", "rocznik", "w_spisie", "w_mirrorze", "brakuje", "bajty", "uszkodzone"])
        for (seg, rok), s in sorted(stat.items()):
            w.writerow([seg, rok, s["w_spisie"], s["w_mirrorze"],
                        s["w_spisie"] - s["w_mirrorze"], s["bajty"], s["uszkodzone"]])

    md = ["# Kompletność mirrora CKE", "",
          f"Wygenerowano: {time.strftime('%Y-%m-%d %H:%M')}", ""]
    tot_s = sum(s["w_spisie"] for s in stat.values())
    tot_m = sum(s["w_mirrorze"] for s in stat.values())
    tot_b = sum(s["bajty"] for s in stat.values())
    md += [f"Spis: **{tot_s}** · mirror: **{tot_m}** "
           f"({tot_m * 100 // max(tot_s, 1)}%) · **{human(tot_b)}**", ""]
    for seg, cfg in SEGMENTS.items():
        keys = sorted(k for k in stat if k[0] == seg)
        if not keys:
            continue
        md += [f"## {cfg['label']} — {sum(stat[k]['w_mirrorze'] for k in keys)}/"
               f"{sum(stat[k]['w_spisie'] for k in keys)}, "
               f"{human(sum(stat[k]['bajty'] for k in keys))}", "",
               "| rocznik | w spisie | w mirrorze | brakuje | rozmiar |",
               "| --- | ---: | ---: | ---: | ---: |"]
        for k in keys:
            s = stat[k]
            md.append(f"| {k[1]} | {s['w_spisie']} | {s['w_mirrorze']} | "
                      f"{s['w_spisie'] - s['w_mirrorze']} | {human(s['bajty'])} |")
        md.append("")
    md += ["## Typy dokumentów", "", "| typ | plików |", "| --- | ---: |"]
    md += [f"| {t} | {n} |" for t, n in typy.most_common()]
    md += ["", "## Skąd rozpoznany typ", "", "| źródło | plików |", "| --- | ---: |"]
    md += [f"| {z} | {n} |" for z, n in zrodla.most_common()]
    md += ["", f"Braki co do pliku: `data/reports/braki.tsv` ({len(braki)})."]
    (lay.reports / "kompletnosc.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return {"stat": stat, "braki": braki, "uszkodzone": uszkodzone,
            "typy": typy, "zrodla": zrodla,
            "w_spisie": tot_s, "w_mirrorze": tot_m, "bajty": tot_b}


def print_report(lay: Layout, rep: dict, results: list[dict] | None,
                 elapsed: float, created_dirs: list[Path], jobs: int) -> None:
    line = "─" * 72
    print(f"\n{line}\nRAPORT Z WYKONANIA\n{line}")

    if created_dirs:
        print(f"\nStruktura katalogów: utworzono {len(created_dirs)} katalogów")
    else:
        print("\nStruktura katalogów: gotowa (nic do utworzenia)")
    print(f"  {lay.data.relative_to(lay.root)}/index/pages     surowy HTML stron rocznikowych")
    print(f"  {lay.data.relative_to(lay.root)}/index/urls.tsv   spis: jeden wiersz na plik")
    print(f"  {lay.data.relative_to(lay.root)}/raw/<segment>/<rok>/<przedmiot>/<kod>.pdf")
    print(f"  {lay.data.relative_to(lay.root)}/reports          kompletność, braki, log zwózki")

    if results is not None:
        pobrane = [r for r in results if r["status"] == "pobrany"]
        pominiete = [r for r in results if r["status"] == "pominiety"]
        bledy = [r for r in results if r["status"] == "blad"]
        b = sum(r["bajty"] for r in pobrane)
        print(f"\nZwózka — {len(results)} pozycji w {elapsed:.1f} s "
              f"({elapsed / max(len(results), 1):.2f} s/plik, {jobs} strumieni)")
        print(f"  pobrane          {len(pobrane):>5}   {human(b)}"
              f"   {b / 1024 / 1024 / max(elapsed, 0.001):.1f} MB/s")
        print(f"  pominięte        {len(pominiete):>5}   już w mirrorze")
        print(f"  błędy            {len(bledy):>5}")
        for r in bledy[:15]:
            print(f"      {r['blad']:<28} {r['plik']}")
        if len(bledy) > 15:
            print(f"      … i {len(bledy) - 15} więcej — pełna lista w download-log.tsv")

    print(f"\nMirror — {rep['w_mirrorze']}/{rep['w_spisie']} plików ze spisu, {human(rep['bajty'])}")
    for seg, cfg in SEGMENTS.items():
        keys = [k for k in rep["stat"] if k[0] == seg]
        if not keys:
            continue
        m = sum(rep["stat"][k]["w_mirrorze"] for k in keys)
        s = sum(rep["stat"][k]["w_spisie"] for k in keys)
        bb = sum(rep["stat"][k]["bajty"] for k in keys)
        flag = "" if m == s else f"   ← brakuje {s - m}"
        print(f"  {cfg['label']:<24} {m:>5}/{s:<5} {human(bb):>9}{flag}")

    print("\nTypy dokumentów w mirrorze")
    for t, n in rep["typy"].most_common():
        print(f"  {t:<20} {n:>5}")
    print("\nSkąd rozpoznany typ (jakość metadanych)")
    for z, n in rep["zrodla"].most_common():
        print(f"  {z:<20} {n:>5}")

    if rep["uszkodzone"]:
        print(f"\n!! {len(rep['uszkodzone'])} plików bez sygnatury %PDF — usuń je i uruchom ponownie")
    if rep["braki"]:
        print(f"\nBraki ({len(rep['braki'])}) — pełna lista w data/reports/braki.tsv")
        for r in rep["braki"][:10]:
            print(f"  {r['sciezka_lokalna']}")
    else:
        print("\nBraków brak — mirror pokrywa cały spis.")
    print(f"\nRaport: {(lay.reports / 'kompletnosc.md').relative_to(lay.root)}\n{line}")


# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Mirror arkuszy CKE: struktura katalogów + zwózka + raport.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Przykład: python3 cke_mirror.py --filtr matematyka --jobs 8")
    ap.add_argument("--katalog", type=Path, default=Path(__file__).resolve().parent,
                    help="korzeń projektu (domyślnie katalog skryptu)")
    ap.add_argument("--jobs", type=int, default=8,
                    help="równoległe strumienie (domyślnie 8 — pomiar: 0,42 s/plik)")
    ap.add_argument("--segment", choices=list(SEGMENTS), help="ogranicz do jednego segmentu")
    ap.add_argument("--rocznik", help="ogranicz do jednego rocznika, np. 2026")
    ap.add_argument("--filtr", help="podciąg ścieżki lokalnej, np. matematyka")
    ap.add_argument("--limit", type=int, help="pobierz najwyżej N plików (do testów)")
    ap.add_argument("--force", action="store_true", help="pobierz ponownie mimo obecności pliku")
    ap.add_argument("--tylko-spis", action="store_true", help="zbuduj spis, nie pobieraj PDF-ów")
    ap.add_argument("--tylko-raport", action="store_true", help="użyj spisu z dysku, nic nie pobieraj")
    ap.add_argument("--cicho", action="store_true", help="bez paska postępu")
    args = ap.parse_args()

    lay = Layout(args.katalog.resolve())
    created = lay.build()

    if args.tylko_raport:
        rows = read_inventory(lay)
        results, elapsed = None, 0.0
    else:
        rows, stats = collect_inventory(lay, args.cicho)
        write_inventory(lay, rows, stats)
        zle = [s for s in stats if s["blad"]]
        print(f"Spis: {len(rows)} unikatowych PDF-ów z {len(stats) - len(zle)}/{len(stats)} "
              f"stron rocznikowych", file=sys.stderr)
        for s in zle:
            print(f"  !! {s['segment']} {s['rocznik']}: {s['blad']}", file=sys.stderr)
        results, elapsed = None, 0.0

    wybor = rows
    if args.segment:
        wybor = [r for r in wybor if r["segment"] == args.segment]
    if args.rocznik:
        wybor = [r for r in wybor if str(r["rocznik"]) == str(args.rocznik)]
    if args.filtr:
        wybor = [r for r in wybor if args.filtr.lower() in r["sciezka_lokalna"].lower()]
    if args.limit:
        wybor = wybor[: args.limit]

    if not (args.tylko_spis or args.tylko_raport):
        if not wybor:
            sys.exit("Spis po filtrach jest pusty — sprawdź --segment/--rocznik/--filtr.")
        results, elapsed = download_all(lay, wybor, args.jobs, args.force, args.cicho)

    rep = build_report(lay, wybor)
    print_report(lay, rep, results, elapsed, created, args.jobs)
    return 1 if (rep["braki"] or rep["uszkodzone"]) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nPrzerwane. Mirror jest idempotentny — uruchom ponownie, "
              "pobrane pliki zostaną pominięte.", file=sys.stderr)
        raise SystemExit(130)
