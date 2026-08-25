# Cały stos deweloperski jednym poleceniem: Postgres + Azurite + migracje,
# potem API i web z hot-reloadem.
#
#   pwsh scripts/dev-stack.ps1          # albo: powershell -File scripts\dev-stack.ps1
#
# Skrypt NIE powtarza logiki z `Taskfile.yml` — woła `task`, bo to jedno wejście
# do wszystkich pętli i ma działać tak samo na Windows, macOS i w CI. Dokłada
# tylko to, czego Taskfile z założenia nie robi: operacje na plikach (`.env`)
# i sprawdzenie, czy Docker w ogóle stoi.

$ErrorActionPreference = 'Stop'

# Korzeń repozytorium liczony od położenia skryptu — żeby dało się go wywołać
# z dowolnego katalogu, także z profilu edytora.
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Fail([string]$message) {
    Write-Host "PRZERWANE: $message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command task -ErrorAction SilentlyContinue)) {
    Fail "brak `task` — zainstaluj: winget install Task.Task"
}

# Docker musi ODPOWIADAĆ, a nie tylko być zainstalowany: przy wyłączonym silniku
# `docker --version` przechodzi, a `task up` wywala się dopiero po kilkunastu
# sekundach komunikatem o pipie, który nikogo nie prowadzi do przyczyny.
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw }
} catch {
    Fail "Docker nie odpowiada — uruchom Docker Desktop i spróbuj ponownie"
}

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Utworzono .env z .env.example — porty i hasło bazy są w nim do zmiany." -ForegroundColor Yellow
}

# `task setup` sprawdza komplet narzędzi (dotnet, node, pnpm, uv) i mówi, czego brak.
task setup
if ($LASTEXITCODE -ne 0) { Fail "task setup zgłosił brak narzędzia" }

# Postgres + Azurite + migracje schematu.
task up
if ($LASTEXITCODE -ne 0) { Fail "task up nie podniósł kontenerów — sprawdź kolizje portów w .env" }

Write-Host ""
Write-Host "Stos stoi. API i web startują poniżej — zatrzymuje je Ctrl+C." -ForegroundColor Green
Write-Host "Kontenery zostają w tle; zatrzymuje je 'task down'." -ForegroundColor Green
Write-Host ""

# Oba serwery stoją, dopóki ich nie ubijesz — to ostatnia komenda skryptu.
task dev
