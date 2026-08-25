using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Grading;

/// <summary>Pusty do A3; wejście istnieje od początku, żeby kompozycja się nie zmieniała.</summary>
public static class GradingModule
{
    public static IServiceCollection AddGrading(this IServiceCollection services, IConfiguration configuration)
    {
        _ = configuration;
        return services;
    }
}
