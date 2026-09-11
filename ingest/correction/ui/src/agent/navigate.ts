/** Przejścia między stronami — osobny moduł, bo w jsdom `location.assign` nie działa,
 *  a testy panelu chcą wiedzieć, DOKĄD agent zaprowadził, nie próbować tam iść. */

export function assign(url: string): void {
  window.location.assign(url);
}

export function open(url: string): void {
  window.open(url, "_blank", "noopener");
}
