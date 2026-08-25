using System.Reflection;
using Klucz.Contracts;
using Klucz.Corpus;
using Klucz.Grading;
using Klucz.Learning;

var builder = WebApplication.CreateBuilder(args);

// Konfiguracja: appsettings + zmienne środowiskowe. Adres bazy WYŁĄCZNIE ze
// zmiennych (patrz `DatabaseConnectionString`) — connection string nie ma prawa
// stać w pliku wersjonowanym.
builder.Configuration.AddEnvironmentVariables();

// Trzy linijki i ani słowa o wnętrzu modułów. Dołożenie czwartego modułu w A2
// ma być dopisaniem linijki, nie przebudową kompozycji.
builder.Services.AddCorpus(builder.Configuration);
builder.Services.AddGrading(builder.Configuration);
builder.Services.AddLearning(builder.Configuration);

builder.Services.AddOpenApi();

var app = builder.Build();

app.MapOpenApi();

// Gotowość procesu i stan bazy — OSOBNO. Proces potrafi stać i odpowiadać, gdy
// baza jest nieosiągalna; zlepienie tego w jeden status znaczy, że przy awarii
// nie widać, co się właściwie zepsuło. Kod 200 znaczy „API żyje", a pole
// `database` mówi, czy żyje cały system.
app.MapGet("/health", async (IDatabaseProbe database, CancellationToken ct) =>
{
    var alive = await database.IsAliveAsync(ct);
    var version = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "0.0.0";
    return new HealthResponse(alive ? "ok" : "degraded", alive, version);
})
.WithName("Health")
.WithSummary("Gotowość API i stan połączenia z bazą");

app.Run();

/// <summary>
/// Punkt zaczepienia dla <c>WebApplicationFactory</c> w testach.
/// </summary>
/// <remarks>
/// Program najwyższego poziomu ma klasę wygenerowaną i wewnętrzną; bez tej
/// deklaracji testy nie miałyby czego podać jako parametr typu, a wtedy jedyną
/// alternatywą jest <c>InternalsVisibleTo</c> — czyli otwieranie produktu na testy.
/// </remarks>
public partial class Program;
