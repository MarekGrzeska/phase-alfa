using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Klucz.Learning;

/// <summary>Pusty do A4.</summary>
public static class LearningModule
{
    public static IServiceCollection AddLearning(this IServiceCollection services, IConfiguration configuration)
    {
        _ = configuration;
        return services;
    }
}
