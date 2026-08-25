using System.Reflection;
using Klucz.Contracts;
using Klucz.Corpus;
using Klucz.Grading;
using Klucz.Learning;

var builder = WebApplication.CreateBuilder(args);

// Konfiguracja: appsettings + zmienne środowiskowe. Adres bazy WYŁĄCZNIE ze
// zmiennych (patrz `PolaczenieBazy`) — connection string nie ma prawa stać
// w pliku wersjonowanym.
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
app.MapGet("/health", async (IDatabaseProbe baza, CancellationToken ct) =>
{
    var odpowiada = await baza.OdpowiadaAsync(ct);
    var wersja = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "0.0.0";
    return new HealthResponse(odpowiada ? "ok" : "degraded", odpowiada, wersja);
})
.WithName("Health")
.WithSummary("Gotowość API i stan połączenia z bazą");

app.Run();

/// <summary>
/// Punkt zaczepienia dla `WebApplicationFactory` w testach.
/// </summary>
/// <remarks>
/// Program najwyższego poziomu ma klasę wygenerowaną i wewnętrzną; bez tej
/// deklaracji testy nie miałyby czego podać jako parametr typu, a wtedy jedyną
/// alternatywą jest `InternalsVisibleTo` — czyli otwieranie produktu na testy.
/// </remarks>
public partial class Program;
