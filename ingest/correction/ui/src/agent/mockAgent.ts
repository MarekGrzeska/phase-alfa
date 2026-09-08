/** Podróbka agenta: gotowe odpowiedzi puszczane po kawałku, bez żadnego modelu.
 *
 * Strumień jest tu po coś, a nie dla ozdoby. Panel ma pokazać, jak wygląda
 * odpowiedź RODZĄCA SIĘ w kawałkach — bo to jest kształt, z którym korektor
 * będzie pracował, i to on decyduje, czy tekst da się czytać w trakcie.
 * Na tym samym strumieniu widać też sens `remend`: niedomknięte `**` ma być
 * pogrubieniem od pierwszej klatki, a nie dwiema gwiazdkami w treści.
 */

/** Odpowiedź makiety: markdown pisany tak, jak pisze go model. */
const REPLIES: readonly string[] = [
  `Zadanie ma **trzy kryteria**, a punktacja rozkłada się tak:

| Kryterium | Punkty | Warunek |
| --- | ---: | --- |
| poprawna metoda | 1 | zapis wzoru |
| rachunek | 1 | wynik z jednostką |
| wniosek | 1 | odpowiedź pełnym zdaniem |

Progi w kluczu są *rozłączne*, więc suma nigdy nie przekroczy 3 pkt.`,

  `Sprawdziłem zapisy równoważne dla tego progu:

1. \`x = 2\` — postać podstawowa
2. \`x=2\` — bez spacji, ta sama treść
3. \`2 = x\` — odwrócona, też uznawana

Uwaga: zapis \`x ≈ 2\` **nie jest** równoważny — przybliżenie zmienia treść
odpowiedzi, a klucz mówi o wartości dokładnej.`,

  `> Klucz dopuszcza „każdy poprawny sposób rozwiązania".

To zdanie zmienia sposób oceniania: kryterium nie sprawdza METODY, tylko
czy wynik jest uzasadniony. W praktyce:

- brak wzoru, ale poprawny rachunek → **punkt należy się**
- wzór poprawny, rachunek błędny → punkt tylko za metodę

Szczegóły w zasadach oceniania CKE: <https://cke.gov.pl>`,

  `Nie mam dostępu do bazy — jestem makietą.

\`\`\`text
agent: brak podlaczenia
model: —
narzedzia: 0
\`\`\`

Kiedy podłączymy prawdziwego agenta, w tym miejscu pojawi się odpowiedź
oparta o **to zadanie**, które masz otwarte na ekranie.`,
];

/** Kolejna odpowiedź w kolejce — po treści pytania, żeby ta sama runda dawała to samo.
 *
 * Losowanie wyglądałoby żywiej, ale makieta, która przy każdym odświeżeniu
 * mówi co innego, jest nieprzydatna przy pokazywaniu jej komuś.
 */
export function mockReply(question: string, turn: number): string {
  const seed = question.trim().length + turn;
  return REPLIES[seed % REPLIES.length];
}

export interface MockStreamOptions {
  /** Odstęp między kawałkami w milisekundach. */
  readonly interval?: number;
  /** Ile znaków dokłada jeden kawałek. */
  readonly chunkSize?: number;
  readonly onChunk: (soFar: string) => void;
  readonly onDone: (full: string) => void;
}

export interface MockStream {
  /** Przerywa strumień. To, co zdążyło przyjść, zostaje na ekranie. */
  stop: () => void;
}

/** Puszcza tekst kawałkami, jak strumień z modelu.
 *
 * Kawałki lecą po ZNAKACH, nie po słowach: model tnie odpowiedź na tokeny,
 * które potrafią skończyć się w środku słowa albo w środku znacznika markdown,
 * a właśnie te miejsca są dla renderowania trudne.
 */
export function streamMockReply(text: string, options: MockStreamOptions): MockStream {
  const interval = options.interval ?? 24;
  const chunkSize = options.chunkSize ?? 6;
  let sent = 0;

  const timer = setInterval(() => {
    sent = Math.min(sent + chunkSize, text.length);
    options.onChunk(text.slice(0, sent));
    if (sent >= text.length) {
      clearInterval(timer);
      options.onDone(text);
    }
  }, interval);

  return {
    stop: () => clearInterval(timer),
  };
}
