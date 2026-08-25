"""Statystyka korekty — pomiar S8 („ile naprawdę kosztuje półautomat").

Podział ról jest celowy: zapytania oddają surowe wiersze, a liczby składa
funkcja czysta. Dzięki temu prognoza i mediana dają się przetestować bez bazy,
a to one, a nie SQL, decydują o rozstrzygnięciu z G2.2.2 (zawór po pilocie).
"""

from __future__ import annotations

from statistics import median

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


def collect(cur) -> dict:
    """Komplet liczb S8 — stan, czasy, prognoza, rozbicie na roczniki."""
    from correction import db

    counts = db.counts_by_status(cur)
    status = status_summary(counts)

    cur.execute(
        """SELECT extract(epoch FROM (finished_at - started_at)) AS seconds
           FROM correction_event WHERE action IN ('approve', 'correct')"""
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
    return {
        "status": status,
        "durations": durations,
        "forecast": forecast(status["pending"], durations["median"]),
        "years": cur.fetchall(),
    }


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
