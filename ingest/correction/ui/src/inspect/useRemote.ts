import { useEffect, useState } from "react";

/** Pobranie danych widoku: wynik, powód porażki i nic więcej.
 *
 * Odpowiedź na PORZUCONE zapytanie nie ma prawa nadpisać świeższej — filtr
 * przełączony dwa razy pod rząd potrafi wrócić w odwrotnej kolejności.
 */
export function useRemote<T>(
  ask: () => Promise<T>,
  deps: readonly unknown[],
): { data: T | null; failure: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setFailure(null);
    ask()
      .then((next) => {
        if (current) setData(next);
      })
      .catch((error: Error) => {
        if (current) setFailure(error.message);
      });
    return () => {
      current = false;
    };
    // Zależności podaje wołający: to on wie, co w jego adresie znaczy „inne dane".
  }, deps);

  return { data, failure };
}
