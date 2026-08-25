namespace Klucz.Contracts;

/// <summary>
/// Port stoi w Contracts, bo pyta o to <c>Klucz.Api</c>, któremu nie wolno wiedzieć o Npgsql.
/// </summary>
public interface IDatabaseProbe
{
    /// <summary>Nie rzuca — zwraca fałsz.</summary>
    Task<bool> IsAliveAsync(CancellationToken ct = default);
}
