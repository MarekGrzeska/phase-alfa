using System.Text.Json.Nodes;
using Microsoft.Extensions.Configuration;
using Npgsql;

namespace Klucz.Corpus.Infrastructure;

/// <summary>
/// Odczyt korpusu plain SQL-em. Żadnego EF — C# ten schemat tylko czyta, a każde
/// zapytanie idzie po widoku <c>corpus_task</c>, nie po <c>task</c>.
/// </summary>
public sealed class PostgresCorpusReader(IConfiguration configuration) : ICorpusReader
{
    // Leniwie, jak w sondzie: dokument OpenAPI powstaje przy buildzie, a generator
    // startuje w tym celu aplikację — odczyt adresu w konstruktorze kazałby
    // `dotnet build` mieć bazę.
    private readonly Lazy<string> _connectionString = new(
        () => DatabaseConnectionString.FromEnvironment(configuration),
        LazyThreadSafetyMode.PublicationOnly);

    private async Task<NpgsqlConnection> OpenAsync(CancellationToken ct)
    {
        var connection = new NpgsqlConnection(_connectionString.Value);
        await connection.OpenAsync(ct);
        return connection;
    }

    public async Task<IReadOnlyList<FormSummary>> ListFormsAsync(CancellationToken ct = default)
    {
        // Zadania liczone z podzapytania DISTINCT, nie `count(DISTINCT ...)` razem
        // z `sum(...)`: forma z dwiema wersjami ma każde zadanie dwa razy, więc
        // suma punktów bez odsiania duplikatów byłaby podwojona.
        const string sql = """
            SELECT f.id, f.code, f.variant, f.version, f.session,
                   count(*)::int AS tasks, coalesce(sum(k.max_points), 0)::int AS points
            FROM exam_form f
            JOIN (SELECT DISTINCT tv.exam_form_id, t.id, t.max_points
                    FROM task_version tv
                    JOIN corpus_task t ON t.id = tv.task_id) k
              ON k.exam_form_id = f.id
            GROUP BY f.id, f.code, f.variant, f.version, f.session
            ORDER BY f.session DESC, f.code, f.variant, f.version NULLS FIRST
            """;

        await using var connection = await OpenAsync(ct);
        await using var command = new NpgsqlCommand(sql, connection);
        await using var reader = await command.ExecuteReaderAsync(ct);

        var out_ = new List<FormSummary>();
        while (await reader.ReadAsync(ct))
        {
            out_.Add(new FormSummary(
                reader.GetInt32(0), reader.GetString(1), reader.GetString(2),
                reader.IsDBNull(3) ? null : reader.GetString(3),
                reader.GetFieldValue<DateOnly>(4), reader.GetInt32(5), reader.GetInt32(6)));
        }

        return out_;
    }

    public async Task<IReadOnlyList<TaskSummary>> ListTasksAsync(
        int formId, CancellationToken ct = default)
    {
        const string sql = """
            SELECT t.id, t.number, t.max_points, t.kind,
                   EXISTS (SELECT 1 FROM task_version v
                             JOIN asset a ON a.task_version_id = v.id
                            WHERE v.task_id = t.id) AS has_asset,
                   (SELECT count(*)::int FROM task_version v WHERE v.task_id = t.id) AS versions
            FROM corpus_task t
            WHERE EXISTS (SELECT 1 FROM task_version v
                           WHERE v.task_id = t.id AND v.exam_form_id = @form)
            ORDER BY t.position
            """;

        await using var connection = await OpenAsync(ct);
        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("form", formId);
        await using var reader = await command.ExecuteReaderAsync(ct);

        var out_ = new List<TaskSummary>();
        while (await reader.ReadAsync(ct))
        {
            out_.Add(new TaskSummary(
                reader.GetInt32(0), reader.GetString(1), reader.GetInt32(2),
                reader.GetString(3), reader.GetBoolean(4), reader.GetInt32(5)));
        }

        return out_;
    }

    public async Task<TaskDetail?> GetTaskAsync(int taskId, CancellationToken ct = default)
    {
        await using var connection = await OpenAsync(ct);

        var head = await ReadTaskHeadAsync(connection, taskId, ct);
        if (head is null)
        {
            return null;
        }

        var versions = await ReadVersionsAsync(connection, taskId, ct);
        var criteria = await ReadCriteriaAsync(connection, taskId, ct);
        var requirements = await ReadRequirementsAsync(connection, taskId, ct);
        var solutions = await ReadSolutionsAsync(connection, taskId, ct);
        var rules = await ReadRulesAsync(connection, taskId, ct);

        return head with
        {
            Versions = versions,
            Criteria = criteria,
            Requirements = requirements,
            Solutions = solutions,
            Rules = rules,
        };
    }

    private async Task<TaskDetail?> ReadTaskHeadAsync(
        NpgsqlConnection connection, int taskId, CancellationToken ct)
    {
        const string sql = """
            SELECT t.id, t.number, t.max_points, t.kind, t.review_status, t.page
            FROM corpus_task t WHERE t.id = @task
            """;

        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("task", taskId);
        await using var reader = await command.ExecuteReaderAsync(ct);

        if (!await reader.ReadAsync(ct))
        {
            return null;
        }

        return new TaskDetail(
            reader.GetInt32(0), reader.GetString(1), reader.GetInt32(2), reader.GetString(3),
            reader.GetString(4), reader.IsDBNull(5) ? null : reader.GetInt16(5),
            [], [], [], [], []);
    }

    private async Task<IReadOnlyList<TaskVersion>> ReadVersionsAsync(
        NpgsqlConnection connection, int taskId, CancellationToken ct)
    {
        const string sql = """
            SELECT v.id, f.code, f.variant, f.version, v.content, v.page
            FROM task_version v
            JOIN exam_form f ON f.id = v.exam_form_id
            WHERE v.task_id = @task
            ORDER BY f.variant, f.version NULLS FIRST
            """;

        var rows = new List<(int Id, string Code, string Variant, string? Version,
                             string? Content, int? Page)>();
        await using (var command = new NpgsqlCommand(sql, connection))
        {
            command.Parameters.AddWithValue("task", taskId);
            await using var reader = await command.ExecuteReaderAsync(ct);
            while (await reader.ReadAsync(ct))
            {
                rows.Add((reader.GetInt32(0), reader.GetString(1), reader.GetString(2),
                          reader.IsDBNull(3) ? null : reader.GetString(3),
                          reader.IsDBNull(4) ? null : reader.GetString(4),
                          reader.IsDBNull(5) ? null : reader.GetInt16(5)));
            }
        }

        var answers = await ReadAnswersAsync(connection, taskId, ct);
        var assets = await ReadAssetsAsync(connection, taskId, ct);

        return rows.Select(row => new TaskVersion(
            row.Id, row.Code, row.Variant, row.Version, row.Content, row.Page,
            answers.TryGetValue(row.Id, out var a) ? a : [],
            assets.TryGetValue(row.Id, out var s) ? s : [])).ToList();
    }

    private async Task<Dictionary<int, List<ModelAnswer>>> ReadAnswersAsync(
        NpgsqlConnection connection, int taskId, CancellationToken ct)
    {
        const string sql = """
            SELECT m.task_version_id, m.id, m.part, m.answer
            FROM model_answer m
            JOIN task_version v ON v.id = m.task_version_id
            WHERE v.task_id = @task
            ORDER BY m.part NULLS FIRST, m.id
            """;

        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("task", taskId);
        await using var reader = await command.ExecuteReaderAsync(ct);

        var out_ = new Dictionary<int, List<ModelAnswer>>();
        while (await reader.ReadAsync(ct))
        {
            var answer = new ModelAnswer(
                reader.GetInt32(1), reader.IsDBNull(2) ? null : reader.GetString(2),
                reader.GetString(3));
            AddTo(out_, reader.GetInt32(0), answer);
        }

        return out_;
    }

    private async Task<Dictionary<int, List<Asset>>> ReadAssetsAsync(
        NpgsqlConnection connection, int taskId, CancellationToken ct)
    {
        const string sql = """
            SELECT a.task_version_id, a.id, a.kind, a.description, a.description_status
            FROM asset a
            JOIN task_version v ON v.id = a.task_version_id
            WHERE v.task_id = @task
            ORDER BY a.id
            """;

        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("task", taskId);
        await using var reader = await command.ExecuteReaderAsync(ct);

        var out_ = new Dictionary<int, List<Asset>>();
        while (await reader.ReadAsync(ct))
        {
            var asset = new Asset(
                reader.GetInt32(1), reader.GetString(2),
                reader.IsDBNull(3) ? null : reader.GetString(3), reader.GetString(4));
            AddTo(out_, reader.GetInt32(0), asset);
        }

        return out_;
    }

    private async Task<IReadOnlyList<Criterion>> ReadCriteriaAsync(
        NpgsqlConnection connection, int taskId, CancellationToken ct)
    {
        // Trzy poziomy dysjunkcji NIESPŁASZCZONE — po to powstał ten model.
        // Jedno zapytanie z LEFT JOIN-ami, bo próg bez warunków i warunek bez
        // zapisów są normalnym stanem klucza, nie brakiem.
        const string sql = """
            SELECT c.id, c.points, c.label, c.description,
                   cc.id, cc.description,
                   ce.id, ce.expression, ce.mathjson, ce.mathjson_status
            FROM criterion c
            LEFT JOIN criterion_condition cc ON cc.criterion_id = c.id
            LEFT JOIN condition_expression ce ON ce.condition_id = cc.id
            WHERE c.task_id = @task
            ORDER BY c.points DESC, c.position, cc.position, cc.id, ce.position, ce.id
            """;

        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("task", taskId);
        await using var reader = await command.ExecuteReaderAsync(ct);

        var criteria = new List<Criterion>();
        var conditions = new Dictionary<int, List<CriterionCondition>>();
        var expressions = new Dictionary<int, List<ConditionExpression>>();
        var seenCriteria = new HashSet<int>();
        var seenConditions = new HashSet<int>();

        while (await reader.ReadAsync(ct))
        {
            var criterionId = reader.GetInt32(0);
            if (seenCriteria.Add(criterionId))
            {
                criteria.Add(new Criterion(
                    criterionId, reader.GetInt32(1),
                    reader.IsDBNull(2) ? null : reader.GetString(2),
                    reader.IsDBNull(3) ? null : reader.GetString(3), []));
            }

            if (reader.IsDBNull(4))
            {
                continue;
            }

            var conditionId = reader.GetInt32(4);
            if (seenConditions.Add(conditionId))
            {
                AddTo(conditions, criterionId,
                      new CriterionCondition(conditionId, reader.GetString(5), []));
            }

            if (reader.IsDBNull(6))
            {
                continue;
            }

            AddTo(expressions, conditionId, new ConditionExpression(
                reader.GetInt32(6), reader.GetString(7),
                reader.IsDBNull(8) ? null : JsonNode.Parse(reader.GetString(8)),
                reader.GetString(9)));
        }

        return criteria.Select(criterion => criterion with
        {
            Conditions = (conditions.TryGetValue(criterion.Id, out var found) ? found : [])
                .Select(condition => condition with
                {
                    Expressions = expressions.TryGetValue(condition.Id, out var e) ? e : [],
                }).ToList(),
        }).ToList();
    }

    private async Task<IReadOnlyList<Requirement>> ReadRequirementsAsync(
        NpgsqlConnection connection, int taskId, CancellationToken ct)
    {
        const string sql = """
            SELECT r.id, rr.code, r.kind, r.stage, r.path, r.content
            FROM task_requirement tr
            JOIN requirement r ON r.id = tr.requirement_id
            JOIN requirement_regime rr ON rr.id = r.regime_id
            WHERE tr.task_id = @task
            ORDER BY r.kind, r.stage NULLS FIRST, r.path
            """;

        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("task", taskId);
        await using var reader = await command.ExecuteReaderAsync(ct);

        var out_ = new List<Requirement>();
        while (await reader.ReadAsync(ct))
        {
            out_.Add(new Requirement(
                reader.GetInt32(0), reader.GetString(1), reader.GetString(2),
                reader.IsDBNull(3) ? null : reader.GetString(3),
                reader.GetString(4), reader.GetString(5)));
        }

        return out_;
    }

    private async Task<IReadOnlyList<ExampleSolution>> ReadSolutionsAsync(
        NpgsqlConnection connection, int taskId, CancellationToken ct)
    {
        const string sql = """
            SELECT id, points, method, content FROM example_solution
            WHERE task_id = @task ORDER BY position, id
            """;

        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("task", taskId);
        await using var reader = await command.ExecuteReaderAsync(ct);

        var out_ = new List<ExampleSolution>();
        while (await reader.ReadAsync(ct))
        {
            out_.Add(new ExampleSolution(
                reader.GetInt32(0), reader.GetInt32(1),
                reader.IsDBNull(2) ? null : reader.GetString(2), reader.GetString(3)));
        }

        return out_;
    }

    private async Task<IReadOnlyList<Rule>> ReadRulesAsync(
        NpgsqlConnection connection, int taskId, CancellationToken ct)
    {
        // Reguły arkusza obejmujące to zadanie. Zakres „16–21" porównuje się
        // LICZBOWO: dopasowanie po krańcach gubiło regułę przy zadaniu 18.
        const string sql = """
            SELECT r.id, r.kind, r.content, r.tasks_from, r.tasks_to
            FROM rule r
            JOIN corpus_task t ON t.marking_scheme_id = r.marking_scheme_id
            WHERE t.id = @task
              AND (r.tasks_from IS NULL OR split_part(r.tasks_from, '.', 1)::int
                     <= split_part(t.number, '.', 1)::int)
              AND (r.tasks_to IS NULL OR split_part(r.tasks_to, '.', 1)::int
                     >= split_part(t.number, '.', 1)::int)
            ORDER BY r.position
            """;

        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("task", taskId);
        await using var reader = await command.ExecuteReaderAsync(ct);

        var out_ = new List<Rule>();
        while (await reader.ReadAsync(ct))
        {
            out_.Add(new Rule(
                reader.GetInt32(0), reader.GetString(1), reader.GetString(2),
                reader.IsDBNull(3) ? null : reader.GetString(3),
                reader.IsDBNull(4) ? null : reader.GetString(4)));
        }

        return out_;
    }

    public async Task<string?> GetAssetPathAsync(int assetId, CancellationToken ct = default)
    {
        // Wycinek wydaje się TYLKO dla zadania, które jest w korpusie — inaczej
        // przeglądarka pokazywałaby grafikę rekordu, którego nikt nie zatwierdził.
        const string sql = """
            SELECT a.path FROM asset a
            JOIN task_version v ON v.id = a.task_version_id
            JOIN corpus_task t ON t.id = v.task_id
            WHERE a.id = @asset
            LIMIT 1
            """;

        await using var connection = await OpenAsync(ct);
        await using var command = new NpgsqlCommand(sql, connection);
        command.Parameters.AddWithValue("asset", assetId);
        return await command.ExecuteScalarAsync(ct) as string;
    }

    public async Task<CorpusProgress> GetProgressAsync(CancellationToken ct = default)
    {
        const string perYear = """
            SELECT d.year,
                   count(*)::int AS total,
                   count(*) FILTER (WHERE t.review_status = 'pending')::int,
                   count(*) FILTER (WHERE t.review_status = 'approved')::int,
                   count(*) FILTER (WHERE t.review_status = 'corrected')::int,
                   count(*) FILTER (WHERE t.review_status = 'rejected')::int
            FROM task t
            JOIN document d ON d.id = t.marking_scheme_id
            GROUP BY d.year ORDER BY d.year
            """;

        const string totals = """
            SELECT (SELECT count(*) FROM task)::int,
                   (SELECT count(*) FROM task WHERE review_status = 'approved')::int,
                   (SELECT count(*) FROM task WHERE review_status = 'corrected')::int,
                   (SELECT count(*) FROM task WHERE review_status = 'rejected')::int,
                   (SELECT count(*) FROM task WHERE review_status = 'pending')::int,
                   (SELECT count(*) FROM asset)::int,
                   (SELECT count(*) FROM asset
                     WHERE description_status IN ('approved', 'corrected'))::int,
                   (SELECT count(*) FROM condition_expression)::int,
                   (SELECT count(*) FROM condition_expression
                     WHERE mathjson_status IN ('auto', 'approved'))::int
            """;

        await using var connection = await OpenAsync(ct);

        var years = new List<YearProgress>();
        await using (var command = new NpgsqlCommand(perYear, connection))
        await using (var reader = await command.ExecuteReaderAsync(ct))
        {
            while (await reader.ReadAsync(ct))
            {
                years.Add(new YearProgress(
                    reader.GetInt16(0), reader.GetInt32(1), reader.GetInt32(2),
                    reader.GetInt32(3), reader.GetInt32(4), reader.GetInt32(5)));
            }
        }

        await using var totalsCommand = new NpgsqlCommand(totals, connection);
        await using var totalsReader = await totalsCommand.ExecuteReaderAsync(ct);
        await totalsReader.ReadAsync(ct);

        var tasks = totalsReader.GetInt32(0);
        var approved = totalsReader.GetInt32(1);
        var corrected = totalsReader.GetInt32(2);
        var rejected = totalsReader.GetInt32(3);
        var pending = totalsReader.GetInt32(4);

        // Trafienia parsera liczone po rekordach, które WESZŁY do korpusu:
        // odrzucone nie są ani trafieniem, ani poprawką — są dziurą.
        var usable = approved + corrected;

        return new CorpusProgress(years, new ProgressTotals(
            tasks, usable + rejected, approved, corrected, rejected, pending,
            usable == 0 ? 0d : (double)approved / usable,
            totalsReader.GetInt32(5), totalsReader.GetInt32(6),
            totalsReader.GetInt32(7), totalsReader.GetInt32(8)));
    }

    private static void AddTo<TKey, TValue>(
        Dictionary<TKey, List<TValue>> map, TKey key, TValue value)
        where TKey : notnull
    {
        if (!map.TryGetValue(key, out var found))
        {
            found = [];
            map[key] = found;
        }

        found.Add(value);
    }
}
