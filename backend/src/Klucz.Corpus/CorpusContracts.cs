using System.Text.Json.Nodes;

namespace Klucz.Corpus;

/// <summary>
/// Kontrakt odczytu korpusu (W2.1). Implementacja czyta po widoku <c>corpus_task</c>,
/// nigdy po <c>task</c> — definicja „co jest korpusem" stoi w schemacie.
/// </summary>
public interface ICorpusReader
{
    Task<IReadOnlyList<FormSummary>> ListFormsAsync(CancellationToken ct = default);

    Task<IReadOnlyList<TaskSummary>> ListTasksAsync(int formId, CancellationToken ct = default);

    /// <summary>Pełne drzewo zadania albo <c>null</c>, gdy nie ma go w korpusie.</summary>
    Task<TaskDetail?> GetTaskAsync(int taskId, CancellationToken ct = default);

    /// <summary>Ścieżka WZGLĘDNA wycinka w składzie blobów albo <c>null</c>.</summary>
    Task<string?> GetAssetPathAsync(int assetId, CancellationToken ct = default);

    Task<CorpusProgress> GetProgressAsync(CancellationToken ct = default);
}

public sealed record FormSummary(
    int Id, string Code, string Variant, string? Version, DateOnly Session,
    int Tasks, int Points);

public sealed record TaskSummary(
    int Id, string Number, int MaxPoints, string Kind, bool HasAsset, int Versions);

public sealed record TaskDetail(
    int Id, string Number, int MaxPoints, string Kind, string ReviewStatus, int? Page,
    IReadOnlyList<TaskVersion> Versions,
    IReadOnlyList<Criterion> Criteria,
    IReadOnlyList<Requirement> Requirements,
    IReadOnlyList<ExampleSolution> Solutions,
    IReadOnlyList<Rule> Rules);

public sealed record TaskVersion(
    int Id, string Code, string Variant, string? Version, string? Content, int? Page,
    IReadOnlyList<ModelAnswer> Answers,
    IReadOnlyList<Asset> Assets);

public sealed record ModelAnswer(int Id, string? Part, string Answer);

/// <summary>Wycinek graficzny. Bajty idą osobnym endpointem przez <c>IBlobStore</c>.</summary>
public sealed record Asset(int Id, string Kind, string? Description, string DescriptionStatus);

public sealed record Criterion(
    int Id, int Points, string? Label, string? Description,
    IReadOnlyList<CriterionCondition> Conditions);

public sealed record CriterionCondition(
    int Id, string Description, IReadOnlyList<ConditionExpression> Expressions);

/// <summary>
/// Zapis równoważny z MathJSON-em. <c>MathJson</c> bywa <c>null</c> — wtedy
/// <c>MathJsonStatus</c> mówi dlaczego (<c>none</c>, <c>failed</c>), i to jest
/// informacja dla konsumenta, nie brak danych.
/// </summary>
public sealed record ConditionExpression(
    int Id, string Expression, JsonNode? MathJson, string MathJsonStatus);

public sealed record Requirement(
    int Id, string Regime, string Kind, string? Stage, string Path, string Content);

public sealed record ExampleSolution(int Id, int Points, string? Method, string Content);

public sealed record Rule(int Id, string Kind, string Content, string? TasksFrom, string? TasksTo);

/// <summary>
/// Postęp ingestu dla pulpitu W2.3. Liczony po CAŁEJ tabeli <c>task</c>, nie po
/// widoku korpusu: pytanie brzmi „ile jeszcze zostało", więc rekordy spoza
/// korpusu są tu treścią, a nie szumem.
/// </summary>
public sealed record CorpusProgress(IReadOnlyList<YearProgress> Years, ProgressTotals Totals);

public sealed record YearProgress(
    int Year, int Total, int Pending, int Approved, int Corrected, int Rejected);

public sealed record ProgressTotals(
    int Tasks, int Decided, int Approved, int Corrected, int Rejected, int Pending,
    double HitShare, int Assets, int AssetsDescribed,
    int Expressions, int ExpressionsWithMathJson);
