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

## Inspektor danych — drugi widok zadania, świadomie w Pythonie (8.09.2026)

`/inspect` w aplikacji ekranu korekty pokazuje każdą tabelę, każdy wiersz, jego
rodziców i dzieci po kluczach obcych, oraz **źródło w plikach**: stronę PDF z mirrora
(z ramką `bbox` narysowaną w SVG nad obrazem) i wycinek z bloba. Przeglądarka W2
ma już widok zadania — to jest dublowanie i jest zamierzone. Inspektor musi widzieć
`pending` (W2 czyta tylko `corpus_task`), otwierać PDF (C# nie może) i czytać bloba
lokalnie. Narzędzie badawcze dla jednej osoby, nie funkcja produktu.

Trzy rozstrzygnięcia, które z tego wynikają:

- **Nazwy tabel i kolumn z adresu nigdy nie trafiają do SQL-a.** Allowlista
  z `information_schema` przy pierwszym żądaniu, identyfikatory przez
  `sql.Identifier`, wartości filtrów jako parametry. Nieznana tabela → 404,
  nieznana kolumna → 400, zanim cokolwiek dotknie bazy.
- **„Źródło" jest wiedzą o kodzie, nie o wierszu.** Etykieta przy kolumnie mówi, który
  przebieg ją pisze (słownik `SOURCES`, spisany z każdego INSERT/UPDATE w repozytorium).
  Pochodzenie konkretnego wiersza inspektor podaje osobno i tylko tam, gdzie schemat
  je niesie: `reviewed_by`, `description_status`, `mathjson_status`, dziennik.
  Sugerowanie pewności, której schemat nie ma, byłoby gorsze niż jej brak.
- **Plik wskazany przez bazę, którego nie ma na dysku, to osobny stan.** Nie NULL,
  nie 404 — komunikat „pliku nie ma w mirrorze" w widoku i osobna kontrola w panelu
  zdrowia. To jest dokładnie ten błąd danych, po który inspektor powstał.

Panel zdrowia to `corpus:report` jako klikalne listy: każda liczba prowadzi do
wierszy, każdy wiersz do źródła. Kontrole z filtrem w Pythonie (istnienie pliku)
są droższe od SQL-a i liczone przy każdym wejściu na `/inspect` — przy 651
zasobach to ułamek sekundy, przy K6 trzeba będzie cache.

**Filtrowanie i sortowanie** (dołożone tego samego dnia) trzyma się trzech reguł:

- **Filtr stoi przy swojej kolumnie**, w wierszu pod nagłówkami: mały wybór operatora
  i pole wartości. Kolumny nie wybiera się z listy — wybiera ją miejsce, w którym się
  pisze. Domyślny operator bierze się z typu: „zawiera" po tekście, równość po liczbie,
  dacie i kluczu obcym.
- **Filtruje się samo, po zmianie pola** — i to jest jedyne miejsce w tej aplikacji
  z JavaScriptem. Ekran korekty nie ma go wcale (dlatego ramkę wpisuje się z siatki
  zamiast przeciągać myszą) i tak zostaje; inspektor dostaje `onchange="this.form.submit()"`
  na kontrolce, bo automatycznego wysyłania formularza w samym HTML-u nie ma.
  `onchange`, a nie `oninput`: przy wpisywaniu zdarzenie leci po opuszczeniu pola albo
  po Enterze, więc jedno zapytanie na filtr, a nie jedno na literę. Przycisk „Filtruj"
  zostaje w `<noscript>` — bez JS-a narzędzie dalej działa, tylko z kliknięciem.

  Konsekwencja dla adresu: przepisanie na postać kanoniczną musi zachodzić **także
  wtedy, gdy wszystkie pola są puste**, czyli gdy filtry właśnie zdjęto. Inaczej
  wybranie „—" w ostatniej liście zostawiałoby w pasku komplet pustych `op.*`,
  a „wstecz" wracało do adresu, który niczego nie filtruje.
- **Kolumna słownikowa daje wybór, nie wpisywanie**, i ma operatory zawężone do `=`,
  `≠` (plus „pusta"/„niepusta", gdy jest NULL-owalna). Wpisanie `aproved` zamiast
  `approved` dawałoby pustą listę wyglądającą jak brak danych — a inspektor powstał
  po to, żeby odróżniać brak danych od błędu.

  Słownikiem jest kolumna z **więzem CHECK** — wartości bierze się wtedy ze
  **schematu** (`pg_get_constraintdef`, postać `= ANY (ARRAY[…])`), nie z `SELECT
  DISTINCT`: status, którego dziś nie ma ani w jednym wierszu, wciąż jest legalny
  i ma dać się wybrać. Poza tym kolumna logiczna oraz taka, której dane wyraźnie
  się **powtarzają** — bo słownikiem czyni kolumnę powtarzalność, a nie mała liczba
  wartości: przy trzech wierszach w tabeli każda kolumna wyglądałaby na słownik.
  Stąd próg (≥20 wierszy, wartości co najmniej czterokrotnie się powtarzają,
  każda krótsza niż 40 znaków), który zostawia `criterion_condition.description`
  polem tekstowym, a `exam_form.variant` i `document.kind_source` zamienia w listę.

  Filtr wpisany ręcznie w adresie bywa szerszy niż to, co oferuje wiersz
  (`?kind__contains=clo`). Taki operator i taka wartość **dokładają się** do list
  przy renderowaniu — inaczej pierwsze kliknięcie „Filtruj" po cichu zmieniłoby
  zapytanie, które użytkownik napisał.
- **Adres jest stanem.** Kanonicznie: `?kolumna=wartość` (równość) albo
  `?kolumna__operator=wartość`. Stan widoku — `_sort`, `_dir`, `_page`, `_cols` —
  ma **podkreślnik na początku**, bo bez niego koliduje z nazwami kolumn: `page`
  istnieje w `task`, `task_version` i `asset`, więc `?page=11` znaczyło „strona 11"
  i po tej kolumnie nie dało się filtrować w ogóle, a wiersz filtrów wysyłał puste
  `page=` i cała lista wracała z **422**. Z tego samego powodu stan widoku czyta się
  z `query_params`, a nie przez parametry funkcji trasy: FastAPI odrzuca `_page=`
  pustym stringiem, a formularz wysyła puste pola przy każdym wysłaniu.
  Pole w wierszu filtrów nie
  umie zmienić swojej nazwy bez JavaScriptu, więc przysyła wartość pod nazwą kolumny,
  a operator obok, pod `op.<kolumna>` — i dostaje **303 na adres kanoniczny**. Dzięki
  temu adres z paska da się wkleić w notatce, a „wstecz" nie wraca do wysłanego
  formularza. Skrót bez operatora zostaje, bo tak wyglądają linki z widoku wiersza
  do dzieci. Prefiks `op.`, a nie sufiks, bo `kolumna__op` kolidowałoby z kanonicznym
  `kolumna__operator`.
- **Porównania idą po typie kolumny, nie po tekście.** `points > 2` ma znaczyć
  liczbę: `'9' > '10'` jest prawdą dla napisów i fałszem dla liczb. Równość
  i „zawiera" zostają na `::text`, bo ten sam mechanizm obsługuje wtedy jsonb
  i tablice. Wartość niepasująca do typu wraca zdaniem przy formularzu, nie
  pięćsetką — i **z jawnym `rollback()`**, bo odrzucone zapytanie zrywa transakcję
  i każde następne (choćby podpowiedzi do formularza) wracałoby z „current
  transaction is aborted".
- **Filtr odrzucony jest nazwany, nie pomijany.** Nieznana kolumna albo operator
  wypisuje się nad listą. Filtr, który nie działa, ale wygląda jakby działał,
  pokazywałby pełną tabelę jako wynik zapytania — to gorsze niż błąd.

Sortowanie dokłada klucz główny jako rozstrzygnięcie remisów: bez tego strona 2
potrafi powtórzyć wiersze ze strony 1, bo przy równych wartościach PostgreSQL
nie obiecuje stałej kolejności między zapytaniami.

**Rozmiar strony (25 / 50 / 100, domyślnie 50) zapamiętuje CIASTECZKO**, nie
`localStorage`: ustawia je serwer przy przekierowaniu, więc wybór przeżywa zamknięcie
przeglądarki, a ekran nie potrzebuje do tego ani linijki JavaScriptu. `_per` pojawia
się w adresie tylko po to, żeby trasa zapisała ciasteczko, i **znika po
przekierowaniu**: rozmiar strony jest ustawieniem przeglądarki, a nie częścią adresu,
którym się dzieli — link wklejony komuś innemu ma pokazać jego widok, nie mój.
Zmiana rozmiaru wraca na pierwszą stronę, bo przy 25 na stronie „strona 12" bywa już
za końcem listy. Wartość spoza listy — w adresie albo podłożona w ciasteczku —
schodzi do domyślnej, zamiast wywracać zapytanie `LIMIT`-em z bzdury.

## W2 — co czyta przeglądarka korpusu

**Wyłącznie widok `corpus_task`, nigdy `task`.** Definicja „co jest korpusem" stoi
w jednym miejscu schematu, zamiast być powtórzona w kodzie trzech warstw.

Wyjątek jest jeden i jest świadomy: `GET /corpus/progress` liczy po CAŁEJ tabeli
zadań, bo pulpit postępu odpowiada na pytanie „ile jeszcze zostało" — rekordy spoza
korpusu są tam treścią, nie szumem.

**Routing to adres i nic więcej** (`?view=…&form=…&task=…`). Biblioteka routingu
byłaby zależnością na jeden ekran narzędzia badawczego.

## Front ekranu korekty w Reakcie (8.09.2026) — odwołanie reguły „bez frameworka"

Ekran korekty i inspektor są w całości w Reakcie (`ingest/correction/ui`, Vite,
build do `static/`). Serwer oddaje jedną skorupę `app.html` z nazwą widoku
w `data-view` i dane przez `/api/*`.

**To jest odwrócenie wcześniejszego rozstrzygnięcia** („FastAPI + Jinja2, bez
kroku budowania i bez frameworka na froncie", i „jedyne miejsce z JavaScriptem"
przy filtrach inspektora). Powód: do ekranu wchodzi agent — okno rozmowy ze
strumieniem odpowiedzi i markdownem, na tym samym zestawie bibliotek co terminal
TradingCenter (`react-markdown`, `remark-gfm`, `remend`). Utrzymywanie tego
w wanilii kosztowałoby więcej niż krok budowania, który i tak jest w repozytorium
dla `web/`.

Co migracja ZACHOWAŁA, świadomie:

- **Nazwy pól formularza korekty** (`criterion.12.points`, `delete.answer.3`)
  i to, że niezaznaczonego pola wyboru po prostu nie ma. Rozstrzyga o nich
  `db.save`, a razem z nimi rozróżnienie „parser trafił sam" od „poprawione" —
  czyli pomiary S6 i S8. Formularz jest niekontrolowany i wysyła `FormData`.
- **Adresy list inspektora liczy `ListView`** i odsyła gotowe w `links`.
  Sklejane na froncie rozjechałyby się przy pierwszej nowej opcji.
- **Formatowanie wartości** (`format_value`) zostaje w Pythonie: po drodze przez
  JSON `bbox` i `jsonb` wyglądają tak samo, więc front dostaje gotowy tekst plus
  rodzaj komórki.
- **Adres jest stanem widoku**: filtr, strona podglądu PDF, zakres pracy — wszystko
  dalej w pasku, więc link da się wkleić w notatce, a „wstecz" działa.

Co się zmieniło:

- Postać kanoniczna adresu wraca w `links.canonical` zamiast przez przekierowanie
  303; front wpisuje ją do paska po odpowiedzi.
- Rozmiar strony inspektora pamięta `localStorage`, nie ciasteczko — to wybór
  człowieka po stronie przeglądarki, a nie stan sesji na serwerze.
- Po nieudanej walidacji serwer odsyła same powody (422 + `errors`), a nie
  formularz z nałożonymi wartościami: to, co człowiek wpisał, zostaje w przeglądarce.

---

---

## Do rozstrzygnięcia przez człowieka — nie da się tego zrobić kodem

| Decyzja | Czego wymaga | Gdzie stoi rachunek |
|---|---|---|
| **G2.2.2 — zawór po pilocie** | skorygowania rocznika 2025 w ekranie i odczytania mediany czasu | `task correction:report`, sekcja PROGNOZA: mediana × pozostałe zadania. Mieści się w ~2 tygodniach → A2 jedzie sekwencyjnie; nie → pilot staje się „wystarczającym A2" i odblokowuje A3 |
| **G2.5.1 — prefill w przepływie czy nie** | skorygowania ≥20 zadań otwartych w obu ramionach (z podpowiedzią i bez) | `task correction:report`, sekcja S6: zysk trafień w punktach procentowych i różnica mediany czasu |
| **G2.6 — `failed` schodzące ręcznie** | przejrzenia 100 odmów w ekranie korekty | raport `task mathjson`, rozbicie na powody — największa kategoria pierwsza |
| **Tor G — golden set** | 2–3 własnych odpowiedzi na każde z 56 zadań otwartych | `ingest/golden/`; A3 (G3.3) na tym stoi i tego nie da się kupić tokenami |
