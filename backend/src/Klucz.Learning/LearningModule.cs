using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Learning;

/// <summary>
/// Wejście modułu nauki (powtórki, postęp ucznia). Treść wchodzi w A4.
/// </summary>
public static class LearningModule
{
    public static IServiceCollection AddLearning(this IServiceCollection services, IConfiguration configuration)
    {
        _ = configuration;
        return services;
    }
}
