using System.Net;
using System.Net.Http.Json;
using Klucz.Corpus;
using Klucz.Corpus.Infrastructure;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Npgsql;

namespace Klucz.Tests;

/// <summary>
/// Przeglądarka korpusu (W2.1). Sedno tych testów nie jest w tym, że endpoint
/// odpowiada 200, tylko w tym, że czyta po widoku <c>corpus_task</c>: zadanie
/// czekające na korektę NIE JEST korpusem i nie ma prawa się tu pokazać.
/// </summary>
public sealed class CorpusTests : IAsyncLifetime
{
    // Rocznik z przyszłości i własny URL: wiersze testu mają być odróżnialne
    // od korpusu na maszynie deweloperskiej, także gdy sprzątanie zawiedzie.
    private const string DocumentUrl = "test://corpus-api";
    private const short Year = 2099;

    private int _formId;
    private int _approvedTaskId;
    private int _pendingTaskId;
    private int _assetId;

    public async Task InitializeAsync()
    {
        if (!Available)
        {
            return;
        }

        await using var connection = await OpenAsync();
        await CleanupAsync(connection);

        var regime = await ScalarAsync(connection, """
            INSERT INTO requirement_regime (code, name, session_from)
            VALUES ('test-pp', 'Podstawa testowa', '2099-01-01')
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """);

        var requirement = await ScalarAsync(connection, $"""
            INSERT INTO requirement (regime_id, kind, stage, path, content)
            VALUES ({regime}, 'specific', 'VII-VIII', 'TEST.1', 'oblicza pole figury')
            ON CONFLICT (regime_id, kind, stage, path) DO UPDATE SET content = EXCLUDED.content
            RETURNING id
            """);

        var document = await ScalarAsync(connection, $"""
            INSERT INTO document (segment, year, code, variants, session, kind, kind_source,
                                  url, path, pages)
            VALUES ('e8', {Year}, 'TEST', '100', '2099-05-01', 'marking_scheme', 'suffix',
                    '{DocumentUrl}', 'test.pdf', 30)
            RETURNING id
            """);

        _formId = await ScalarAsync(connection, $"""
            INSERT INTO exam_form (regime_id, exam, subject, code, variant, version, session)
            VALUES ({regime}, 'e8', 'matematyka', 'TEST', '100', 'X', '2099-05-01')
            RETURNING id
            """);

        _approvedTaskId = await ScalarAsync(connection, $"""
            INSERT INTO task (marking_scheme_id, number, position, max_points, kind,
                              page, review_status)
            VALUES ({document}, '20', 20, 3, 'open_short', 12, 'approved')
            RETURNING id
            """);

        _pendingTaskId = await ScalarAsync(connection, $"""
            INSERT INTO task (marking_scheme_id, number, position, max_points, kind,
                              page, review_status)
            VALUES ({document}, '21', 21, 2, 'open_short', 13, 'pending')
            RETURNING id
            """);

        await ExecuteAsync(connection,
            $"INSERT INTO task_requirement VALUES ({_approvedTaskId}, {requirement})");

        var version = await ScalarAsync(connection, $"""
            INSERT INTO task_version (task_id, exam_form_id, content, page)
            VALUES ({_approvedTaskId}, {_formId}, 'Treść zadania testowego', 12)
            RETURNING id
            """);

        await ExecuteAsync(connection, $"""
            INSERT INTO task_version (task_id, exam_form_id, content, page)
            VALUES ({_pendingTaskId}, {_formId}, 'Treść zadania czekającego', 13)
            """);

        await ExecuteAsync(connection, $"""
            INSERT INTO model_answer (task_version_id, part, answer)
            VALUES ({version}, '20.1', 'PRAWDA')
            """);

        _assetId = await ScalarAsync(connection, $"""
            INSERT INTO asset (task_version_id, kind, path, page, bbox,
                               description, description_status)
            VALUES ({version}, 'drawing', 'TEST/2099/z20-0.png', 12,
                    ARRAY[100, 50, 300, 200]::numeric[], 'Kwadrat o boku 15 cm.', 'approved')
            RETURNING id
            """);

        var criterion = await ScalarAsync(connection, $"""
            INSERT INTO criterion (task_id, points, label, position)
            VALUES ({_approvedTaskId}, 3, 'pełne rozwiązanie', 1)
            RETURNING id
            """);

        var condition = await ScalarAsync(connection, $"""
            INSERT INTO criterion_condition (criterion_id, description, position)
            VALUES ({criterion}, 'poprawne obliczenie pola', 1)
            RETURNING id
            """);

        await ExecuteAsync(connection, $"""
            INSERT INTO condition_expression (condition_id, expression, position,
                                              mathjson, mathjson_status)
            VALUES ({condition}, 'P = 15^2', 1, '["Equal","P",["Power",15,2]]'::jsonb, 'auto')
            """);

        await ExecuteAsync(connection, $"""
            INSERT INTO rule (marking_scheme_id, kind, content, tasks_from, tasks_to, position)
            VALUES ({document}, 'result_only', 'Sam wynik to 0 punktów.', '16', '21', 1)
            """);

        await ExecuteAsync(connection, $"""
            INSERT INTO example_solution (task_id, points, method, content, position)
            VALUES ({_approvedTaskId}, 3, 'I', '15 · 15 = 225', 1)
            """);
    }

    public async Task DisposeAsync()
    {
        if (!Available)
        {
            return;
        }

        await using var connection = await OpenAsync();
        await CleanupAsync(connection);
    }

    [RequiresDatabaseFact]
    public async Task Form_list_counts_only_approved_tasks()
    {
        await using var application = new WebApplicationFactory<Program>();

        var forms = await application.CreateClient()
            .GetFromJsonAsync<List<FormSummary>>("/corpus/forms");

        var form = Assert.Single(forms!, f => f.Id == _formId);
        Assert.Equal("TEST", form.Code);
        Assert.Equal(1, form.Tasks);
        Assert.Equal(3, form.Points);
    }

    [RequiresDatabaseFact]
    public async Task Task_waiting_for_review_is_not_corpus()
    {
        await using var application = new WebApplicationFactory<Program>();
        var client = application.CreateClient();

        var tasks = await client.GetFromJsonAsync<List<TaskSummary>>(
            $"/corpus/forms/{_formId}/tasks");

        Assert.Contains(tasks!, t => t.Id == _approvedTaskId);
        Assert.DoesNotContain(tasks!, t => t.Id == _pendingTaskId);

        var direct = await client.GetAsync($"/corpus/tasks/{_pendingTaskId}");

        Assert.Equal(HttpStatusCode.NotFound, direct.StatusCode);
    }

    [RequiresDatabaseFact]
    public async Task Task_detail_carries_the_whole_tree()
    {
        await using var application = new WebApplicationFactory<Program>();

        var task = await application.CreateClient()
            .GetFromJsonAsync<TaskDetail>($"/corpus/tasks/{_approvedTaskId}");

        Assert.NotNull(task);
        Assert.Equal("20", task!.Number);

        var version = Assert.Single(task.Versions);
        Assert.Equal("Treść zadania testowego", version.Content);
        Assert.Equal("PRAWDA", Assert.Single(version.Answers).Answer);
        Assert.Equal("approved", Assert.Single(version.Assets).DescriptionStatus);

        // Trzy poziomy dysjunkcji NIESPŁASZCZONE — po to powstał ten model.
        var criterion = Assert.Single(task.Criteria);
        var condition = Assert.Single(criterion.Conditions);
        var expression = Assert.Single(condition.Expressions);
        Assert.Equal("P = 15^2", expression.Expression);
        Assert.NotNull(expression.MathJson);
        Assert.Equal("auto", expression.MathJsonStatus);

        Assert.Equal("TEST.1", Assert.Single(task.Requirements).Path);
        Assert.Equal("I", Assert.Single(task.Solutions).Method);
        // Zakres reguły „16–21" obejmuje zadanie 20 — porównanie jest LICZBOWE,
        // a nie po krańcach przedziału.
        Assert.Equal("result_only", Assert.Single(task.Rules).Kind);
    }

    [RequiresDatabaseFact]
    public async Task Asset_without_a_file_is_404_not_500()
    {
        await using var application = new WebApplicationFactory<Program>();

        var response = await application.CreateClient().GetAsync($"/corpus/assets/{_assetId}");

        // Wiersz w bazie jest, pliku w blobie nie ma — tak wygląda korpus po
        // `task db:reset`. Odpowiedzią jest 404, nie awaria API.
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [RequiresDatabaseFact]
    public async Task Progress_counts_the_whole_parsed_corpus()
    {
        await using var application = new WebApplicationFactory<Program>();

        var progress = await application.CreateClient()
            .GetFromJsonAsync<CorpusProgress>("/corpus/progress");

        Assert.NotNull(progress);
        var year = Assert.Single(progress!.Years, y => y.Year == Year);

        // Pulpit postępu pyta „ile jeszcze zostało", więc rekordy spoza korpusu
        // są tu treścią, nie szumem: oba zadania mają się liczyć.
        Assert.Equal(2, year.Total);
        Assert.Equal(1, year.Approved);
        Assert.Equal(1, year.Pending);
    }

    private static bool Available => new RequiresDatabaseFactAttribute().Skip is null;

    private static async Task<NpgsqlConnection> OpenAsync()
    {
        var configuration = new ConfigurationBuilder().AddEnvironmentVariables().Build();
        var connection = new NpgsqlConnection(DatabaseConnectionString.FromEnvironment(configuration));
        await connection.OpenAsync();
        return connection;
    }

    /// <summary>`Convert`, nie rzutowanie: część kluczy głównych to `smallserial`.</summary>
    private static async Task<int> ScalarAsync(NpgsqlConnection connection, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        return Convert.ToInt32(await command.ExecuteScalarAsync());
    }

    private static async Task ExecuteAsync(NpgsqlConnection connection, string sql)
    {
        await using var command = new NpgsqlCommand(sql, connection);
        await command.ExecuteNonQueryAsync();
    }

    /// <summary>
    /// Sprzątanie po roczniku 2099. Kolejność ma znaczenie: `task.marking_scheme_id`
    /// celowo NIE ma kaskady (przeładowanie klucza ma przechodzić przez bramkę
    /// korekty w ładowarce), więc zadania trzeba skasować przed dokumentem.
    /// </summary>
    private static async Task CleanupAsync(NpgsqlConnection connection)
    {
        const string documents = $"(SELECT id FROM document WHERE url = '{DocumentUrl}')";

        await ExecuteAsync(connection, $"DELETE FROM task WHERE marking_scheme_id IN {documents}");
        await ExecuteAsync(connection, $"DELETE FROM document WHERE url = '{DocumentUrl}'");
        await ExecuteAsync(connection, "DELETE FROM exam_form WHERE session = '2099-05-01'");
        await ExecuteAsync(connection, """
            DELETE FROM requirement WHERE regime_id IN
              (SELECT id FROM requirement_regime WHERE code = 'test-pp')
            """);
        await ExecuteAsync(connection, "DELETE FROM requirement_regime WHERE code = 'test-pp'");
    }
}
