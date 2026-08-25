namespace Klucz.Tests;

/// <summary>
/// Test wymagający żywej bazy. Bez niej POMIJANY — z widocznym powodem.
/// </summary>
/// <remarks>
/// Pominięcie musi być widać w wyniku przebiegu. Test, który po cichu przechodzi,
/// bo bazy nie było, jest nieodróżnialny od testu, który nic nie sprawdza
/// (CLAUDE.md). W CI baza stoi, więc tam ten test ma się wykonać naprawdę.
/// </remarks>
public sealed class FaktZBazaAttribute : FactAttribute
{
    public FaktZBazaAttribute()
    {
        if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("DB_HOST"))
            && string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("DATABASE_URL")))
        {
            Skip = "brak DB_HOST/DATABASE_URL — test wymaga bazy (`task up`)";
        }
    }
}
