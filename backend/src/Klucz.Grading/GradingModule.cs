using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Grading;

/// <summary>
/// Wejście modułu oceniania. Pusty, bo ocenianie wchodzi w A3 — ale wejście istnieje
/// od pierwszego commita, żeby kompozycja nie musiała się później zmieniać.
/// </summary>
/// <remarks>
/// Gdy <c>Grading</c> będzie potrzebował kryteriów z <c>Corpus</c>, dostanie port
/// <c>ICriteriaSource</c> w <c>Contracts</c>, a <c>Api</c> wstrzyknie implementację.
/// Moduły nie widzą się nawzajem i to jest pilnowane testem.
/// </remarks>
public static class GradingModule
{
    public static IServiceCollection AddGrading(this IServiceCollection services, IConfiguration configuration)
    {
        _ = configuration;
        return services;
    }
}
