# Rozstrzygnięcia zapadłe w A2

Materiał do przeniesienia do `DECYZJE.md` w repozytorium `cke-mirror` — ten plik
jest miejscem przejściowym, nie drugim źródłem prawdy. Przy sprzeczności obowiązuje
`DECYZJE.md`.

Każda pozycja ma tę samą budowę: **co rozstrzygnięto**, **dlaczego tak**, i — gdzie
to możliwe — **liczba, która o tym rozstrzygnęła**. Decyzja bez liczby albo bez
powodu wraca po miesiącu jako pytanie.

---

## G2.3.2 — luki rekonstrukcji, per luka

**Kryterium rozstrzygnięcia: błąd CICHY naprawia się w kodzie, błąd WIDOCZNY wolno
zostawić korekcie ręcznej.** Obowiązuje też dla przyszłych luk.

| Luka | Rozstrzygnięcie | Dlaczego |
|---|---|---|
| liczby mieszane (`1⅔ km` → `12/3 km`) | **naprawa w kodzie** | `12/3` wygląda jak poprawny ułamek o innej wartości — przeszłoby korektę niezauważone. Wzorzec jest regularny: ułamek tuż za cyfrą |
| pierwiastki (zasięg „daszka") | **korekta ręczna** | geometria daszka jest niejednoznaczna, wystąpień mało, a brak domknięcia zasięgu rzuca się w oczy przy zapisie w ekranie |

Test `xfail` liczb mieszanych zgasł na zielono. Test pierwiastków **zostaje na
czerwono** z powodem „ŚWIADOMIE: korekta ręczna" — dzień, w którym zacznie
przechodzić, ma być widoczny. Konwerter MathJSON odmawia zapisów z pierwiastkiem
wprost, zamiast zgadywać zasięg.

## G2.3.1 — brak kryteriów przy zadaniach zamkniętych: norma czy dziura

**Rozstrzyga POMIAR Z DOKUMENTU, nie rocznik wpisany w kod.** Pytanie brzmi: czy
w TYM kluczu którekolwiek zadanie zamknięte ma kryteria. Żadne nie ma → norma
dokumentu. Część ma, część nie → parser przegapił sekcję i to jest ostrzeżenie.

Powód na pomiar zamiast rocznika: w 2019 r. warianty 800 i Q00 kryteria dla zadań
zamkniętych **mają**, choć sześć pozostałych kluczy tego rocznika nie ma.

Liczba: 90 zadań w 6 kluczach rocznika 2019. Wcześniej wchodziły do raportu jako
90 rzekomych dziur i chowały te prawdziwe.

## G2.4.1 — czym rysunek różni się od tabeli

**Pełna szerokość kolumny tekstu = tabela albo linijka strony, nie rysunek.**
Rysunek jest wcięty albo wyśrodkowany.

Liczby: wykres z 2025 r. zajmuje 0,86 szerokości kolumny, tabela odpowiedzi
„Prawda / Fałsz" — 0,99. Próg 0,97 rozdziela je z zapasem.

**Filtrowania po wykrytych tabelach NIE MA i to jest decyzja, nie przeoczenie:**
pdfplumber widzi w wykresie słupkowym tabelę o dziewięciu wierszach, więc odsiewanie
po nich skasowałoby właśnie tę grafikę, o którą chodzi.

Zmierzona skuteczność na całym korpusie: **558 z 607 zasobów (92%) dostało ramkę
z automatu, 49 (8%) czeka na ręczne dociągnięcie.** Ręczna ramka zostaje jako zawór
nr 3 z Planu Implementacji.

## G2.4 — cięcie PNG poza transakcją ładowania

Dysk nie cofa się razem z transakcją, więc plik wycięty przed nieudanym zapisem
zostawałby na miejscu z ramką, której w bazie nie ma — a w ekranie wyglądałby
na gotowy. Cięcie idzie po pętli ładowania, z osobnego narzędzia (`task crops`),
i jest idempotentne.

To samo narzędzie sprząta bloba (`--prune`), bo `task db:reset` kasuje wolumen
Postgresa, ale **zostawia pliki PNG**. Czyszczenie robi narzędzie, nie `rm`
w Taskfile — na Windows go nie ma.

## G2.6 — MathJSON: gdzie stoi normalizacja, a gdzie parser

**Parsowanie w Node** (`@cortex-js/compute-engine`), bo to referencyjna implementacja
MathJSON i ten sam silnik, którego użyje `EvaluateClosed` w A3 — parsowanie tą samą
biblioteką eliminuje dryf dialektu między ingestem a silnikiem oceniania.

**Normalizacja tekstu CKE na LaTeX w Pythonie**, bo to TAM rodzą się pomyłki
(`∶` U+2236 to dzielenie, przecinek jest dziesiętny, ułamek z rekonstrukcji jest
liniowy) i tam da się je przetestować bez uruchamiania Node'a, czyli także w CI.

**Zapisujemy postać NIEKANONICZNĄ** (`canonical: false`): to, co napisał klucz,
a nie to, co silnik uznał za porządek. Kanonizacja jest odwracalna i robi ją
konsument; ekran korekty ma pokazać zapis rozpoznawalny dla człowieka, który
czyta go właśnie z PDF-a.

**Zawężenie do `condition_expression`** zgodnie z planem: `model_answer` zadań
zamkniętych to litery `BD`/`FP`, gdzie MathJSON nic nie wnosi.

**`failed` jest stanem jawnym, nie NULL-em.** Zapis, którego konwerter nie ugryzł,
ma być widoczny w ekranie jako robota do zrobienia. Doszła kolumna `mathjson_error`
z powodem po polsku — bez niej `failed` mówi „nie da się", a człowiek i tak musi
zrobić diagnozę drugi raz.

Zmierzone: **414 z 514 zapisów (80,5%) przekonwertowanych automatem**, 100 świadomych
odmów z rozbiciem na powody. Żaden zapis nie został w stanie `none`.

## G2.5 — LLM proponuje, człowiek zatwierdza

Nic z modelu nie wchodzi do korpusu z pominięciem bramki ekranu korekty.
Provenance niesie **schemat**, nie pamięć autora: podpowiedzi kryteriów leżą
w osobnej tabeli `prefill_suggestion` (nigdy w `criterion`), a opisy rysunków
w `asset.description` ze statusem `auto`.

**Model i dostawca są parametrem przebiegu, nie stałą w kodzie.** Wywołania idą
przez LangChain (`init_chat_model`), więc `--model dostawca:nazwa` wystarczy, żeby
zamienić `openai:gpt-5.6-terra` ($2/$12 za MTok) na `anthropic:claude-opus-5` ($5/$25)
bez dotykania `prefill.py` i `describe.py`.

**Parą pomiarową S6/S7 jest `gpt-5.6-terra` kontra `gpt-5.6-luna`** ($0,20/$1,20) —
ta sama rodzina modeli przy **dziesięciokrotnej różnicy ceny**. Porównanie w jednej
rodzinie zawęża pytanie do „czy słabszy wystarczy", zamiast mieszać różnicę modelu
z różnicą dostawcy. Czy wystarczy, rozstrzygają liczby S6 i S7, a nie założenie.

**Batch API zostaje poza LangChainem — świadomie.** `Runnable.batch()` to
zrównoleglenie po stronie klienta: te same żądania, ta sama cena. Rabat −50% daje
osobny endpoint dostawcy, którego LangChain nie abstrahuje, więc `--batch` schodzi
do surowego SDK i ma dziś adapter dla `openai`. Cena tej decyzji: wsad sam buduje
schemat i ciało żądania. Cena decyzji odwrotnej byłaby wyższa — pełna stawka za
1436 zadań i 607 zasobów, i to bez śladu w raporcie, bo nazwa `batch` zgadzałaby się
w obu przypadkach.

**Ramię eksperymentu S6 wyznacza istnienie wiersza w `prefill_suggestion`**, a nie
pamięć, kiedy prefill był włączony. Bez tego S6 trzeba by rekonstruować z kalendarza.

**Wywołań LLM nie ma w CI.** Testy chodzą na utrwalonych odpowiedziach; przebieg
z żywym modelem jest ręczny i płatny.

## G2.5.2 — `corrected` w statusie opisu rysunku

S7 brzmi „odsetek opisów zatwierdzonych **bez poprawki**", a stany
`none`/`auto`/`approved` tego nie mierzą: opis przyjęty w całości i opis przepisany
od nowa wyglądały w bazie identycznie. Migracja 0007 dokłada `corrected` — ten sam
argument, który w 0004 rozdzielił `approved` i `corrected` na zadaniu.

O statusie rozstrzyga **porównanie z bazą**, nie deklaracja: trafieniem modelu jest
wyłącznie opis z modelu przyjęty bez zmiany. Inaczej S7 dałoby się przekłamać
kliknięciem.

## W2 — co czyta przeglądarka korpusu

**Wyłącznie widok `corpus_task`, nigdy `task`.** Definicja „co jest korpusem" stoi
w jednym miejscu schematu, zamiast być powtórzona w kodzie trzech warstw.

Wyjątek jest jeden i jest świadomy: `GET /corpus/progress` liczy po CAŁEJ tabeli
zadań, bo pulpit postępu odpowiada na pytanie „ile jeszcze zostało" — rekordy spoza
korpusu są tam treścią, nie szumem.

**Routing to adres i nic więcej** (`?view=…&form=…&task=…`). Biblioteka routingu
byłaby zależnością na jeden ekran narzędzia badawczego.

---

## Do rozstrzygnięcia przez człowieka — nie da się tego zrobić kodem

| Decyzja | Czego wymaga | Gdzie stoi rachunek |
|---|---|---|
| **G2.2.2 — zawór po pilocie** | skorygowania rocznika 2025 w ekranie i odczytania mediany czasu | `task correction:report`, sekcja PROGNOZA: mediana × pozostałe zadania. Mieści się w ~2 tygodniach → A2 jedzie sekwencyjnie; nie → pilot staje się „wystarczającym A2" i odblokowuje A3 |
| **G2.5.1 — prefill w przepływie czy nie** | skorygowania ≥20 zadań otwartych w obu ramionach (z podpowiedzią i bez) | `task correction:report`, sekcja S6: zysk trafień w punktach procentowych i różnica mediany czasu |
| **G2.6 — `failed` schodzące ręcznie** | przejrzenia 100 odmów w ekranie korekty | raport `task mathjson`, rozbicie na powody — największa kategoria pierwsza |
| **Tor G — golden set** | 2–3 własnych odpowiedzi na każde z 56 zadań otwartych | `ingest/golden/`; A3 (G3.3) na tym stoi i tego nie da się kupić tokenami |
