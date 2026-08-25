namespace Klucz.Contracts;

/// <summary>
/// Odpowiedź <c>/health</c>: gotowość procesu i stan bazy, osobno.
/// </summary>
/// <remarks>
/// Dwa pola zamiast jednego „OK", bo to są dwa różne zdarzenia: proces może
/// stać i odpowiadać, a baza być nieosiągalna. Zlepienie ich w jeden status
/// znaczy, że przy awarii nie widać, co się właściwie zepsuło.
///
/// Ten typ jest częścią KONTRAKTU — trafia do <c>openapi.json</c>, a stamtąd
/// do typów klienta TS. Zmiana pola bez regeneracji klienta łamie build.
/// </remarks>
/// <param name="Status">„ok" albo „degraded" — degraded znaczy: proces żyje, baza nie.</param>
/// <param name="Database">Czy baza odpowiedziała na ping.</param>
/// <param name="Version">Wersja zbudowanego API.</param>
public sealed record HealthResponse(string Status, bool Database, string Version);
