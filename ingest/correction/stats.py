"""Statystyka korekty — pomiar S8 („ile naprawdę kosztuje półautomat").

Podział ról jest celowy: zapytania oddają surowe wiersze, a liczby składa
funkcja czysta. Dzięki temu prognoza i mediana dają się przetestować bez bazy,
a to one, a nie SQL, decydują o rozstrzygnięciu z G2.2.2 (zawór po pilocie).
"""

from __future__ import annotations

from statistics import median

from correction import assets, db

# Formularz otwarty i porzucony na noc wchodzi do dziennika jako „praca".
# Mediana jest odporna na takie wiersze i to ona jest tu liczbą wiodącą;
# suma stoi obok jako rachunek brutto, świadomie zawyżony.
LONG_SESSION_SECONDS = 30 * 60


def status_summary(counts: dict[str, int]) -> dict:
    """Stan bieżący korpusu: ile rozstrzygnięte i jaki udział parser trafił sam."""
    decided = counts["approved"] + counts["corrected"] + counts["rejected"]
    total = decided + counts["pending"]
    usable = counts["approved"] + counts["corrected"]
    return {
        "counts": counts,
        "total": total,
        "decided": decided,
        "pending": counts["pending"],
        "done_share": decided / total if total else 0.0,
        # Udział trafień parsera liczony po rekordach, które WESZŁY do korpusu.
        # Odrzucone nie są ani trafieniem, ani poprawką — są dziurą i mają
        # własny licznik.
        "hit_share": counts["approved"] / usable if usable else 0.0,
        "rejected": counts["rejected"],
    }


def duration_summary(seconds: list[float]) -> dict:
    """Czas korekty z dziennika. Puste wejście ma dać zera, nie wyjątek."""
    if not seconds:
        return {"events": 0, "median": 0.0, "total": 0.0, "long": 0}
    return {
        "events": len(seconds),
        "median": median(seconds),
        "total": sum(seconds),
        "long": sum(1 for s in seconds if s > LONG_SESSION_SECONDS),
    }


def forecast(pending: int, median_seconds: float) -> dict:
    """Ile jeszcze godzin — rachunek dla decyzji o zaworze, nie wróżba.

    Mnoży się mediana, a nie średnia: jedno zadanie zostawione na noc
    w otwartej karcie potrafi podnieść średnią o rząd wielkości i zamienić
    prognozę w argument za czymkolwiek.
    """
    return {
        "tasks": pending,
        "seconds": pending * median_seconds,
        "hours": pending * median_seconds / 3600,
    }


def arm_summary(rows: list[dict]) -> dict:
    """Jedno ramię eksperymentu S6: ile zadań, ile trafień parsera, jaki czas.

    Funkcja czysta, bo to ona rozstrzyga o decyzji „prefill w przepływie czy
    nie" (G2.2.2) — a decyzja podjęta na liczbie policzonej w SQL-u, którego
    nikt nie przetestował, jest wrażeniem w przebraniu.
    """
    decided = [r for r in rows if r["review_status"] in ("approved", "corrected")]
    seconds = [float(r["seconds"]) for r in rows if r.get("seconds") is not None]
    return {
        "tasks": len(rows),
        "decided": len(decided),
        "hits": sum(1 for r in decided if r["review_status"] == "approved"),
        "hit_share": (sum(1 for r in decided if r["review_status"] == "approved")
                      / len(decided)) if decided else 0.0,
        "median": median(seconds) if seconds else 0.0,
    }


def s6(cur) -> dict:
    """Pomiar S6: korekta Z PODPOWIEDZIĄ modelu kontra korekta bez niej.

    Ramię wyznacza istnienie wiersza w `prefill_suggestion` — nie pamięć,
    kiedy prefill był włączony.
    """
    cur.execute(
        """SELECT t.id, t.review_status,
                  EXISTS (SELECT 1 FROM prefill_suggestion p WHERE p.task_id = t.id)
                      AS prefilled,
                  (SELECT extract(epoch FROM (e.finished_at - e.started_at))
                     FROM correction_event e
                    WHERE e.task_id = t.id AND e.action IN ('approve', 'correct')
                      AND e.actor = 'human'
                    ORDER BY e.id DESC LIMIT 1) AS seconds
           FROM task t
           WHERE t.kind <> 'closed' AND t.reviewed_by = 'human'"""
    )
    rows = cur.fetchall()
    with_hint = arm_summary([r for r in rows if r["prefilled"]])
    without = arm_summary([r for r in rows if not r["prefilled"]])
    return {
        "with_prefill": with_hint,
        "without_prefill": without,
        "hit_share_gain": with_hint["hit_share"] - without["hit_share"],
        # Ujemna różnica czasu znaczy „z podpowiedzią SZYBCIEJ" — tak jest
        # czytelniej niż iloraz, bo mediana bywa zerem, dopóki ramię jest puste.
        "median_gain": with_hint["median"] - without["median"],
    }


def s7(counts: dict[str, int]) -> dict:
    """Pomiar S7: odsetek opisów rysunków zatwierdzonych BEZ poprawki.

    `manual` stoi poza ilorazem: w mianowniku obniżałby S7 za każdym razem,
    gdy człowiek opisał rysunek sam — czyli za pracę, o którą pomiar nie pyta.
    """
    approved = counts.get("description_approved", 0)
    corrected = counts.get("description_corrected", 0)
    decided = approved + corrected
    return {
        "total": counts.get("total", 0),
        "decided": decided,
        "approved": approved,
        "corrected": corrected,
        "manual": counts.get("description_manual", 0),
        "auto": counts.get("description_auto", 0),
        "none": counts.get("description_none", 0),
        "hit_share": approved / decided if decided else 0.0,
    }


def collect(cur) -> dict:
    """Komplet liczb S8 — stan, czasy, prognoza, rozbicie na roczniki."""
    counts = db.counts_by_status(cur)
    status = status_summary(counts)

    cur.execute(
        """SELECT extract(epoch FROM (finished_at - started_at)) AS seconds
           FROM correction_event
           WHERE action IN ('approve', 'correct') AND actor = 'human'"""
    )
    durations = duration_summary([float(r["seconds"]) for r in cur.fetchall()])

    cur.execute(
        """SELECT d.year,
                  count(*) FILTER (WHERE t.review_status = 'pending')   AS pending,
                  count(*) FILTER (WHERE t.review_status = 'approved')  AS approved,
                  count(*) FILTER (WHERE t.review_status = 'corrected') AS corrected,
                  count(*) FILTER (WHERE t.review_status = 'rejected')  AS rejected,
                  count(*) AS total
           FROM task t
           JOIN document d ON d.id = t.marking_scheme_id
           GROUP BY d.year ORDER BY d.year"""
    )
    years = cur.fetchall()
    asset_counts = assets.counts(cur)
    return {
        "status": status,
        "durations": durations,
        "forecast": forecast(status["pending"], durations["median"]),
        "years": years,
        "assets": asset_counts,
        "s6": s6(cur),
        "s7": s7(asset_counts),
    }


def s6_lines(measure: dict, rule: str) -> list[str]:
    with_hint, without = measure["with_prefill"], measure["without_prefill"]
    lines = ["S6 — PREFILL LLM: KOREKTA Z PODPOWIEDZIĄ KONTRA BEZ", rule,
             f"  {'ramię':<18} {'zadań':>7} {'rozstrz.':>9} {'bez popr.':>10}"
             f" {'mediana':>9}"]
    for label, arm in (("z podpowiedzią", with_hint), ("bez podpowiedzi", without)):
        lines.append(f"  {label:<18} {arm['tasks']:>7} {arm['decided']:>9}"
                     f" {100 * arm['hit_share']:>9.1f}% {arm['median']:>8.0f}s")
    if not with_hint["decided"] or not without["decided"]:
        lines.append("  (pomiar niegotowy — puste ramię; uruchom `task prefill`"
                     " i skoryguj obie próby)")
    else:
        lines.append(f"  zysk trafień: {100 * measure['hit_share_gain']:+.1f} pkt proc.,"
                     f" czas: {measure['median_gain']:+.0f} s na zadanie")
    return lines


def s7_lines(measure: dict, rule: str) -> list[str]:
    lines = ["S7 — OPISY RYSUNKÓW ZATWIERDZONE BEZ POPRAWKI", rule,
             f"  zasobów razem          : {measure['total']}",
             f"  bez opisu              : {measure['none']}",
             f"  opis z modelu (auto)   : {measure['auto']}",
             f"  zatwierdzone bez zmian : {measure['approved']}",
             f"  poprawione             : {measure['corrected']}",
             f"  własne człowieka       : {measure['manual']}  (poza S7 —"
             " model nic tu nie proponował)"]
    if measure["decided"]:
        lines.append(f"  S7                     : {100 * measure['hit_share']:.1f}%"
                     " opisów modelu przyjętych bez poprawki")
    else:
        lines.append("  S7                     : brak rozstrzygnięć — pomiar niegotowy")
    return lines


def as_text(numbers: dict) -> str:
    """Raport tekstowy — ta sama treść co na ekranie, do `data/reports/`."""
    status, durations, ahead = (numbers["status"], numbers["durations"],
                                numbers["forecast"])
    rule = "─" * 74
    lines = [
        "KOREKTA — STAN KORPUSU",
        rule,
        f"  zadań razem            : {status['total']}",
        f"  rozstrzygniętych       : {status['decided']}"
        f" ({100 * status['done_share']:.1f}%)",
        f"  do zatwierdzenia       : {status['pending']}",
        f"  zatwierdzone bez zmian : {status['counts']['approved']}",
        f"  poprawione             : {status['counts']['corrected']}",
        f"  odrzucone              : {status['counts']['rejected']}",
        "",
        f"  S8 — trafienia parsera : {100 * status['hit_share']:.1f}%"
        " rekordów korpusu bez ręcznej poprawki",
        "",
        "CZAS KOREKTY (z dziennika)",
        rule,
        f"  rozstrzygnięć w dzienniku : {durations['events']}",
        f"  mediana na zadanie        : {durations['median']:.0f} s",
        f"  suma                      : {durations['total'] / 3600:.1f} h",
        f"  sesji dłuższych niż {LONG_SESSION_SECONDS // 60} min : {durations['long']}"
        " (zawyżają sumę, nie medianę)",
        "",
        "WYCINKI GRAFICZNE",
        rule,
        f"  zasobów razem          : {numbers['assets']['total']}",
        f"  z dociągniętą ramką    : {numbers['assets']['framed']}",
        f"  z plikiem PNG w blobie : {numbers['assets']['cropped']}",
        "",
        *s6_lines(numbers["s6"], rule),
        "",
        *s7_lines(numbers["s7"], rule),
        "",
        "PROGNOZA",
        rule,
        f"  zostało {ahead['tasks']} zadań × mediana = {ahead['hours']:.1f} h",
        "",
        "POKRYCIE PER ROCZNIK",
        rule,
        f"  {'rocznik':<8} {'razem':>8} {'czeka':>8} {'bez zmian':>10}"
        f" {'poprawki':>9} {'odrzuty':>8}",
    ]
    for row in numbers["years"]:
        lines.append(
            f"  {row['year']:<8} {row['total']:>8} {row['pending']:>8}"
            f" {row['approved']:>10} {row['corrected']:>9} {row['rejected']:>8}"
        )
    return "\n".join(lines) + "\n"
