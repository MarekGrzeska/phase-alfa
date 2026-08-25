using Microsoft.Extensions.Configuration;
using Npgsql;

namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Adres bazy — wyłącznie z konfiguracji, nigdy z kodu.
/// </summary>
/// <remarks>
/// Ta sama reguła co w <c>ingest/schema/migrate.py</c>: adres SKŁADANY z części
/// (<c>DB_HOST</c>, <c>DB_PORT</c>, …), a nie wpisany w całości. Numer portu stał
/// wcześniej w <c>.env</c> dwa razy — raz dla Dockera, raz w gotowym adresie — i przy
/// kolizji portów zmieniało się jedno z nich, a objaw („baza nieosiągalna") nie
/// wskazywał na przyczynę.
///
/// <c>DATABASE_URL</c> ma pierwszeństwo i służy do wskazania innej bazy niż
/// deweloperska. Npgsql nie czyta adresów w formie <c>postgresql://</c>, więc
/// rozkładamy je tutaj na części — inaczej ten sam <c>.env</c> działałby dla Pythona
/// i nie działał dla C#.
/// </remarks>
public static class PolaczenieBazy
{
    private static readonly string[] Czesci =
        ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"];

    public static string ZeSrodowiska(IConfiguration konfiguracja)
    {
        var url = konfiguracja["DATABASE_URL"];
        if (!string.IsNullOrWhiteSpace(url))
        {
            return ZAdresu(url);
        }

        var brakuje = Czesci.Where(k => string.IsNullOrWhiteSpace(konfiguracja[k])).ToArray();
        if (brakuje.Length > 0)
        {
            throw new InvalidOperationException(
                $"BRAK zmiennych: {string.Join(", ", brakuje)}. " +
                "Skopiuj .env.example do .env (albo ustaw je w środowisku).");
        }

        return new NpgsqlConnectionStringBuilder
        {
            Host = konfiguracja["DB_HOST"],
            Port = int.Parse(konfiguracja["DB_PORT"]!),
            Database = konfiguracja["DB_NAME"],
            Username = konfiguracja["DB_USER"],
            Password = konfiguracja["DB_PASSWORD"],
        }.ConnectionString;
    }

    /// <summary>`postgresql://user:haslo@host:port/baza` → format, który rozumie Npgsql.</summary>
    public static string ZAdresu(string url)
    {
        var adres = new Uri(url);
        var uzytkownik = adres.UserInfo.Split(':', 2);

        return new NpgsqlConnectionStringBuilder
        {
            Host = adres.Host,
            Port = adres.IsDefaultPort ? 5432 : adres.Port,
            Database = adres.AbsolutePath.TrimStart('/'),
            Username = Uri.UnescapeDataString(uzytkownik[0]),
            Password = uzytkownik.Length > 1 ? Uri.UnescapeDataString(uzytkownik[1]) : null,
        }.ConnectionString;
    }
}
