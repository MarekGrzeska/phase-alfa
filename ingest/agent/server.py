"""Serwer MCP „klucz" — jeden rejestr narzędzi, trzy wejścia.

- stdio: `task mcp` (`python -m agent.server`) — dla Claude Code i Claude Desktop;
- streamable HTTP: zamontowany pod `/mcp` w aplikacji ekranu korekty;
- in-memory: klient agenta w panelu (M4), przez `mcp.shared.memory`.

Na stdio protokół idzie standardowym wyjściem — żadne narzędzie nie ma prawa
niczego wypisać `print`em, bo rozjedzie strumień JSON-RPC.
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from agent.tools import corpus, database, ingest, knowledge, navigation, status

INSTRUCTIONS = """Narzędzia projektu Klucz (faza alfa): korpus kluczy CKE w PostgreSQL,
ekran korekty i inspektor na localhoście, przebiegi ingestu.

Zasady: korpusem jest widok `corpus_task`, tabela `task` zawiera też rekordy
nierozstrzygnięte. Więzy bazy są ostre celowo — rekordu odrzuconego przez więz
nie wymusza się. Zapis do korpusu wyłącznie narzędziami `task_*`, nigdy SQL-em obok.
Narzędzia z `confirm` w metadanych (task_decide, db_execute, zmiany w rekordach
korpusu) wykonują się dopiero po zgodzie człowieka w panelu: pierwsze wywołanie
zwraca prośbę `{"confirm": {...}}` — nie jest to błąd; poczekaj na decyzję i wywołaj
ponownie z `confirmation=<id>`. Przed płatnym przebiegiem z `--apply` obowiązuje
dry-run na jednym roczniku.
Zanim wyjaśnisz, jak coś działa, sprawdź w `docs_search` albo `code_search` —
nie zgaduj. Odpowiadaj po polsku."""


def build_server() -> FastMCP:
    # `streamable_http_path="/"`, bo aplikacja ekranu montuje ten serwer pod `/mcp`
    # i adres ma być dokładnie `/mcp`, a nie `/mcp/mcp`. `json_response=True`:
    # klient z terminala i tak nie czyta strumienia zdarzeń z jednego wywołania.
    # `log_level="WARNING"`: domyślne INFO wypisuje każde żądanie na stderr —
    # w terminalu Claude Code to szum, a w uvicornie dubluje jego własny log.
    mcp = FastMCP("klucz", instructions=INSTRUCTIONS, streamable_http_path="/",
                  json_response=True, log_level="WARNING")
    database.register(mcp)
    corpus.register(mcp)
    ingest.register(mcp)
    knowledge.register(mcp)
    status.register(mcp)
    navigation.register(mcp)
    return mcp


server = build_server()


def session_manager() -> StreamableHTTPSessionManager:
    """Nowy menedżer sesji HTTP dla tego serwera — jeden na cykl życia aplikacji.

    `run()` wolno wywołać raz na instancję, a aplikacja ekranu korekty startuje
    wiele razy w jednym procesie (każdy moduł testów stawia własnego klienta).
    Stąd fabryka, a nie wbudowany `server.session_manager`, który jest jeden na zawsze.
    """
    return StreamableHTTPSessionManager(
        app=server._mcp_server,
        json_response=server.settings.json_response,
        security_settings=server.settings.transport_security,
    )


def main() -> int:
    # Konsola Windows bez tego wybiera cp1250 — protokół po stdio jest w UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    server.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
