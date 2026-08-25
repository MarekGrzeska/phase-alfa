namespace Klucz.Contracts;

/// <summary>
/// Pytanie „czy baza odpowiada" — zadawane przez health check.
/// </summary>
/// <remarks>
/// Port stoi tutaj, a nie w module, bo pyta o to <c>Klucz.Api</c>, któremu nie
/// wolno wiedzieć, że pod spodem jest Npgsql. Implementacja mieszka w
/// <c>Klucz.Corpus.Infrastructure</c> — jedynym miejscu, które dotyka bazy.
/// </remarks>
public interface IDatabaseProbe
{
    /// <summary>Czy baza odpowiada na najprostsze zapytanie. Nie rzuca — zwraca fałsz.</summary>
    Task<bool> IsAliveAsync(CancellationToken ct = default);
}
