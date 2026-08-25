using System.Reflection;
using Klucz.Contracts;
using Klucz.Corpus;
using Klucz.Grading;
using Klucz.Learning;

var builder = WebApplication.CreateBuilder(args);

builder.Configuration.AddEnvironmentVariables();

builder.Services.AddCorpus(builder.Configuration);
builder.Services.AddGrading(builder.Configuration);
builder.Services.AddLearning(builder.Configuration);

builder.Services.AddOpenApi();

var app = builder.Build();

// Tylko poza produkcją — klient TS bierze typy z wersjonowanego `artifacts/openapi.json`.
if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

// `InformationalVersion`, nie `Assembly.GetName().Version`: ta druga jest stałą `1.0.0.0`.
var version = Assembly.GetExecutingAssembly()
    .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
    ?? "0.0.0";

// Kod 200 znaczy „API żyje"; pole `database` mówi, czy żyje cały system.
app.MapGet("/health", async (IDatabaseProbe database, CancellationToken ct) =>
{
    var alive = await database.IsAliveAsync(ct);
    return new HealthResponse(alive ? "ok" : "degraded", alive, version);
})
.WithName("Health")
.WithSummary("Gotowość API i stan połączenia z bazą");

app.Run();

/// <summary>Punkt zaczepienia dla <c>WebApplicationFactory</c> — alternatywą jest <c>InternalsVisibleTo</c>.</summary>
public partial class Program;
