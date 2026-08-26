using Klucz.Contracts;
using Klucz.Corpus;
using Microsoft.AspNetCore.Http.HttpResults;

namespace Klucz.Api;

/// <summary>
/// Endpointy przeglądarki korpusu (W2.1). Trasy stoją tutaj, a nie w module:
/// zależność idzie w jedną stronę i pilnuje tego <c>Nikt_nie_zalezy_od_Api</c>.
/// Api dostaje z modułu gotowy port <see cref="ICorpusReader"/> i o Npgsql
/// nie wie nic.
/// </summary>
public static class CorpusApi
{
    public static IEndpointRouteBuilder MapCorpus(this IEndpointRouteBuilder app)
    {
        var corpus = app.MapGroup("/corpus").WithTags("Corpus");

        corpus.MapGet("/forms", (ICorpusReader reader, CancellationToken ct)
                => reader.ListFormsAsync(ct))
            .WithName("ListForms")
            .WithSummary("Formy arkusza obecne w korpusie — z liczbą zatwierdzonych zadań");

        corpus.MapGet("/forms/{id:int}/tasks", (int id, ICorpusReader reader, CancellationToken ct)
                => reader.ListTasksAsync(id, ct))
            .WithName("ListFormTasks")
            .WithSummary("Zadania jednej formy: numer, pula punktów, rodzaj, czy ma rysunek");

        // `Results<Ok<T>, NotFound>`, a nie `Results.Ok(...)`: to pierwsze niesie TYP
        // do dokumentu OpenAPI, drugie gubi go i klient TS dostaje `unknown`.
        corpus.MapGet("/tasks/{id:int}", async Task<Results<Ok<TaskDetail>, NotFound>> (
                    int id, ICorpusReader reader, CancellationToken ct)
                => await reader.GetTaskAsync(id, ct) is { } task
                    ? TypedResults.Ok(task)
                    : TypedResults.NotFound())
            .WithName("GetTask")
            .WithSummary("Pełne drzewo zadania: wersje, kryteria, wymagania, reguły");

        corpus.MapGet("/assets/{id:int}", async Task<Results<FileStreamHttpResult, NotFound>> (
                int id, ICorpusReader reader, IBlobStore blobs, CancellationToken ct) =>
            {
                var path = await reader.GetAssetPathAsync(id, ct);
                if (path is null)
                {
                    return TypedResults.NotFound();
                }

                try
                {
                    // Ochrona przed wyjściem poza korzeń składu siedzi w `IBlobStore`
                    // i to jest jej pierwszy prawdziwy konsument.
                    var content = await blobs.OpenAsync(path, ct);
                    return TypedResults.File(content, "image/png");
                }
                catch (Exception e) when (e is FileNotFoundException or ArgumentException)
                {
                    // Wiersz w bazie jest, pliku nie ma — tak wygląda korpus po
                    // `task db:reset` albo przed `task crops`. To 404, nie 500.
                    return TypedResults.NotFound();
                }
            })
            .WithName("GetAsset")
            .WithSummary("Wycinek PNG strumieniem przez skład blobów");

        corpus.MapGet("/progress", (ICorpusReader reader, CancellationToken ct)
                => reader.GetProgressAsync(ct))
            .WithName("GetProgress")
            .WithSummary("Postęp korekty per rocznik i statystyka półautomatu");

        return app;
    }
}
