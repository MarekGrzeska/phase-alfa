#!/usr/bin/env sh
# Cały stos deweloperski jednym poleceniem: Postgres + Azurite + migracje,
# potem API i web z hot-reloadem.
#
#   ./scripts/dev-stack.sh
#
# Odpowiednik `scripts/dev-stack.ps1` dla macOS i Linuksa. Skrypt NIE powtarza
# logiki z `Taskfile.yml` — woła `task`. Dokłada tylko to, czego Taskfile
# z założenia nie robi: operacje na plikach (`.env`) i sprawdzenie, czy Docker stoi.

set -eu

# Korzeń repozytorium liczony od położenia skryptu — żeby dało się go wywołać
# z dowolnego katalogu.
cd "$(dirname "$0")/.."

fail() {
    echo "PRZERWANE: $1" >&2
    exit 1
}

command -v task > /dev/null 2>&1 ||
    fail "brak 'task' — zainstaluj: brew install go-task/tap/go-task (macOS) albo npm i -g @go-task/cli (wszedzie)"

# Docker musi ODPOWIADAĆ, a nie tylko być zainstalowany: przy wyłączonym silniku
# `docker --version` przechodzi, a `task up` wywala się dopiero po kilkunastu
# sekundach komunikatem, który nikogo nie prowadzi do przyczyny.
docker info > /dev/null 2>&1 ||
    fail "Docker nie odpowiada — uruchom Docker Desktop i spróbuj ponownie"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Utworzono .env z .env.example — porty i hasło bazy są w nim do zmiany."
fi

# `task setup` sprawdza komplet narzędzi (dotnet, node, pnpm, uv) i mówi, czego brak.
task setup || fail "task setup zgłosił brak narzędzia"

# Postgres + Azurite + migracje schematu.
task up || fail "task up nie podniósł kontenerów — sprawdź kolizje portów w .env"

echo
echo "Stos stoi. API i web startują poniżej — zatrzymuje je Ctrl+C."
echo "Kontenery zostają w tle; zatrzymuje je 'task down'."
echo

# Oba serwery stoją, dopóki ich nie ubijesz — to ostatnia komenda skryptu.
task dev
