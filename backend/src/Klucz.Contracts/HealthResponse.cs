namespace Klucz.Contracts;

/// <summary>
/// Odpowiedź <c>/health</c>. Część kontraktu: idzie do <c>openapi.json</c> i typów klienta TS.
/// </summary>
public sealed record HealthResponse(string Status, bool Database, string Version);
