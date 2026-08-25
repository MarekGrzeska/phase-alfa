---
name: przeglad-kodu
description: Tworzy przegląd kodu (code review) po polsku na podstawie diffa bieżącego brancha i/lub zrealizowanego planu .md, zapisuje go jako samodzielny dokument HTML w katalogu review/. Komentarze posortowane od najważniejszych, każdy z oznaczonym stopniem ważności, wskazaniem pliku i miejsca w kodzie, napisany prostym językiem. Używaj, gdy użytkownik prosi o: "przegląd kodu", "code review", "zrób review", "sprawdź brancha", "oceń co zrobiłem", "/przeglad-kodu".
---

# Przegląd kodu po polsku → dokument HTML

Cel: dać autorowi listę **konkretnych rzeczy do naprawienia**, uporządkowaną tak,
żeby dało się iść od góry i w każdej chwili przestać, nie tracąc niczego ważnego.

Dokument ma być czytelny dla człowieka, który wraca do kodu po tygodniu — nie dla
maszyny i nie dla recenzenta, który już wie, o co chodzi.

---

## 1. Zbierz materiał

Zawsze ustal **zakres** przed czytaniem czegokolwiek.

```bash
git branch --show-current
git merge-base HEAD main                  # punkt odbicia
git diff --stat main...HEAD               # co się zmieniło
git diff main...HEAD                      # pełny diff
git log --oneline main..HEAD              # commity na branchu
```

Gdy branch to `main` albo brak punktu odniesienia — recenzuj `git diff HEAD` albo
ostatni commit, i **napisz w dokumencie, co dokładnie recenzowałeś**.

**Plan `.md`, jeśli istnieje.** Znajdź plan, który ten branch realizuje
(`docs/plan-*.md`, opis w commicie, nazwa brancha). Plan zmienia przegląd
z „czy kod jest dobry" na **„czy kod robi to, co zapowiadał"** — i to jest
cenniejsze pytanie. Szukaj wtedy:

- punktów planu, które są w kodzie **niezrobione**, choć commit twierdzi inaczej;
- rzeczy w kodzie, których **plan nie przewidywał** (nie zawsze źle — ale ma być świadome);
- miejsc, gdzie **plan sam jest już nieaktualny**, bo rzeczywistość go poprawiła
  (to też zgłoś: nieaktualny plan myli następną osobę).

**Nie recenzuj z samego diffa.** Otwórz pliki, w których diff coś zmienia — komentarz
oparty na trzech linijkach kontekstu myli się najczęściej.

**Sprawdzaj, a nie zgaduj.** Jeśli podejrzewasz, że coś się zachowuje inaczej,
niż wygląda (biblioteka, shell, baza) — **uruchom to i sprawdź**. Ustalenie
potwierdzone przebiegiem waży w tym dokumencie dziesięć razy tyle co przypuszczenie,
a ustalenie niepotwierdzone opisz uczciwie jako niepewne.

---

## 2. Na co patrzeć

Kolejność wg wartości, nie wg tego, co łatwo zauważyć:

1. **Czy to działa** — błędy logiczne, przypadki brzegowe, rzeczy, które wywalą się
   przy drugim uruchomieniu albo na czyimś komputerze.
2. **Czy to cicho kłamie** — najgroźniejsza kategoria. Kod, który zgłasza sukces,
   choć nic nie zrobił; test, który przechodzi zawsze; komunikat niezgodny ze stanem
   faktycznym; wynik, który wygląda poprawnie i taki nie jest.
3. **Czy da się to złamać niechcący** — brak walidacji, brak więzu, założenie
   niezapisane nigdzie poza czyjąś głową.
4. **Czy zgadza się z planem i decyzjami** — patrz `docs/plan-*.md` i `DECYZJE.md`.
5. **Czy da się to utrzymać** — powtórzenia, które się rozjadą, nazwy mylące,
   martwy kod.

### Wymiary specyficzne dla tego projektu

Sprawdzaj je zawsze, bo w tym repozytorium łamią się najczęściej:

| Wymiar | Pytanie kontrolne |
|---|---|
| **Granica Python ↔ C#** | Czy C# gdziekolwiek dotyka PDF-a? Czy Python obsługuje ruch użytkownika? Obie odpowiedzi mają brzmieć „nie". |
| **Wieloplatformowość** | Czy to zadziała na Windows i na macOS? Uwaga na: `rm`/`cp`/`mkdir` w skryptach, `python` vs `python3`, wielkość liter w ścieżkach, CRLF, zaszyte porty. |
| **Więzy bazy** | Czy schemat dalej odrzuca złe dane? Poluzowanie więzu, żeby parser przeszedł, to błąd, nie naprawa. |
| **Kontrakt OpenAPI** | Czy zmiana w API pociągnęła regenerację klienta TS? Dryf ma łamać build. |
| **Ścieżki w bazie** | Czy są **względne**? Ścieżka absolutna albo z literą dysku zabija przenośność korpusu. |
| **Testy, które nic nie sprawdzają** | Czy ten test da się zobaczyć na czerwono? Jeśli nie — jest dekoracją. Szukaj `|| echo`, `|| true`, pustych asercji, `try/except: pass`. |

---

## 3. Stopnie ważności

Cztery, i tylko cztery. Więcej stopni znaczy, że nikt ich nie rozróżnia.

| Stopień | Kiedy | Co to znaczy dla autora |
|---|---|---|
| **KRYTYCZNY** | Jest zepsute albo zaraz zepsuje: utrata danych, cichy fałszywy wynik, dziura bezpieczeństwa, złamana granica architektury | Napraw przed scaleniem |
| **ISTOTNY** | Zadziała dziś, ale ugryzie: błąd ujawniający się warunkowo, test, który nie sprawdza, komunikat niezgodny ze stanem, rozjazd z planem | Napraw teraz albo zapisz jako dług z terminem |
| **DROBNY** | Realna niedoskonałość o małym zasięgu: powtórzenie, które się rozjedzie, mylące nazewnictwo, brakujący przypadek brzegowy o niskim ryzyku | Napraw przy okazji |
| **DO ROZWAŻENIA** | Nie błąd — propozycja albo pytanie. Autor ma prawo odpowiedzieć „nie" i zamknąć temat | Decyzja autora |

**Zasady przydzielania stopnia**

- Stopień wynika ze **skutku**, nie z tego, jak długo trwa naprawa. Literówka
  w nazwie zmiennej środowiskowej, przez którą nic nie działa, jest KRYTYCZNA.
- Błąd **utajony** (dziś nieszkodliwy, bo dotyczy kodu, który dopiero powstanie)
  to najwyżej ISTOTNY — ale napisz wprost, **kiedy** ugryzie.
- Nie ma stopnia dla stylu. Jeśli formater albo linter to złapie, nie pisz o tym.
- Jeśli wahasz się między dwoma stopniami — wybierz niższy i napisz dlaczego.

---

## 4. Jak pisać komentarz

Każdy komentarz ma **cztery części**, w tej kolejności:

1. **Co jest nie tak** — jedno zdanie, prostym językiem.
2. **Dlaczego to problem** — co się realnie stanie i kiedy.
3. **Gdzie** — plik i linia albo nazwa funkcji. Zawsze konkretnie.
4. **Jak to naprawić** — propozycja, najlepiej z fragmentem kodu.

**Prostym językiem** znaczy:

- Zdania, nie równoważniki. Pełne słowa, nie skróty.
- Bez żargonu, którego nie da się uniknąć. „Połączenie do bazy nie jest zamykane"
  zamiast „leak connection handle w scope".
- Nazwy techniczne (funkcji, plików, bibliotek) zostają dokładne — upraszczasz
  język, nie treść.
- Pokaż skutek na konkretnym przykładzie: *„jeśli druga migracja się wywali,
  zobaczysz na ekranie, że pierwsza weszła — a nie wejdzie"*.

**Czego nie pisać**

- Ogólników („warto rozważyć poprawę czytelności").
- Komentarzy o rzeczach, których nie sprawdziłeś — albo sprawdź, albo napisz,
  że to przypuszczenie.
- Pochwał rozsianych między uwagami. Co jest dobre, idzie do jednej sekcji na końcu.
- Powtórzeń tego samego problemu w pięciu plikach — jeden komentarz, lista miejsc.

---

## 5. Kolejność

Sortuj **malejąco wg ważności**, a wewnątrz stopnia wg tego, jak szeroko coś sięga
(ile plików, ilu przyszłych zmian dotknie) i jak pewny jesteś ustalenia
(potwierdzone przebiegiem przed przypuszczeniem).

Numeruj komentarze od 1 w górę **przez cały dokument**, nie od nowa w każdej sekcji —
żeby dało się powiedzieć „zrobiłem 1, 2 i 5".

---

## 6. Dokument wyjściowy

**Miejsce i nazwa:** `review/RRRR-MM-DD-<branch>.html`
(np. `review/2026-08-25-feat-g1.1-fundament.html`). Katalog `review/` utwórz, jeśli nie ma.

**Forma:** jeden samodzielny plik HTML — cały CSS w środku, żadnych zewnętrznych
zasobów poza Google Fonts. Ma się otwierać podwójnym kliknięciem.

**Wygląd:** trzymaj język wizualny reszty dokumentacji projektu (zobacz
`docs/projekt-klucz/*.html` w repozytorium `cke-mirror`). Skopiuj zestaw zmiennych
CSS z `szablon.html` — obsługuje tryb jasny i ciemny, w tym ustawienie systemowe.

**Struktura dokumentu:**

1. **Nagłówek** — co recenzowano (branch, zakres commitów, plan), data, jedno zdanie
   podsumowania: czy to nadaje się do scalenia i co blokuje.
2. **Liczby** — ile komentarzy w każdym stopniu, ile plików, ile linii diffa.
3. **Spis** — tabela: numer, stopień, jednozdaniowy tytuł, plik. Klikalna
   (kotwice do komentarzy niżej).
4. **Komentarze** — po kolei, każdy jako karta z numerem, znacznikiem stopnia,
   tytułem, lokalizacją, opisem i propozycją naprawy.
5. **Zgodność z planem** — tabela punktów planu: zrobione / częściowo / nie /
   plan nieaktualny. Pomiń całą sekcję, jeśli planu nie było.
6. **Co jest dobre** — krótko i konkretnie. Nie kurtuazja: rzeczy warte utrzymania
   przy kolejnych zmianach.
7. **Stopka** — czym recenzowano, jakie polecenia sprawdzono, co zostało poza zakresem.

**Rzeczy obowiązkowe w treści:**

- Fragment kodu przy każdym komentarzu, gdzie to ma sens — kilka linii, nie cały plik.
- Przy ustaleniu potwierdzonym uruchomieniem: **pokaż wynik przebiegu**. To jest
  różnica między przeglądem a opinią.
- Jeśli czegoś nie sprawdziłeś, bo się nie dało — napisz to w stopce, zamiast milczeć.

---

## 7. Po zapisaniu

Powiedz użytkownikowi w odpowiedzi:

- gdzie leży plik,
- ile jest komentarzy w podziale na stopnie,
- **trzy najważniejsze rzeczy** własnymi słowami — tak, żeby dało się zdecydować,
  czy otwierać dokument teraz, czy później.

Nie streszczaj całego dokumentu w odpowiedzi. Od tego jest dokument.
