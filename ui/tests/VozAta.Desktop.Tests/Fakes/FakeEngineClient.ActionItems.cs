using VozAta.Client;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Action items (phase 23): stored per session, edits applied, exports scripted.</summary>
internal sealed partial class FakeEngineClient
{
    public Dictionary<string, List<ActionItem>> ActionItems { get; } = [];

    public List<string> TaskTargets { get; } = ["azure_devops", "github"];

    public List<string> Extractions { get; } = [];

    public List<(string Id, IReadOnlyList<ActionItemEdit> Items)> ActionItemUpdates { get; } = [];

    public List<(string Id, string Target, IReadOnlyList<string> ItemIds)> ActionItemExports { get; } = [];

    /// <summary>Item id → error message: these items fail to export, the others get a link.</summary>
    public Dictionary<string, string> ExportFailures { get; } = [];

    public Exception? ActionItemsError { get; set; }

    public Exception? ActionItemsExportError { get; set; }

    public Task<ActionItemList> GetActionItemsAsync(string id, CancellationToken cancellationToken = default)
    {
        Calls.Add($"action-items {id}");
        return ActionItemsError is null ? Task.FromResult(List(id)) : Task.FromException<ActionItemList>(ActionItemsError);
    }

    public Task ExtractActionItemsAsync(string id, CancellationToken cancellationToken = default)
    {
        Extractions.Add(id);
        return ActionItemsError is null ? Task.CompletedTask : Task.FromException(ActionItemsError);
    }

    public Task<ActionItemList> UpdateActionItemsAsync(
        string id, IReadOnlyList<ActionItemEdit> items, CancellationToken cancellationToken = default)
    {
        ActionItemUpdates.Add((id, items));
        if (ActionItemsError is not null)
        {
            return Task.FromException<ActionItemList>(ActionItemsError);
        }

        var stored = Items(id);
        foreach (var edit in items)
        {
            var index = stored.FindIndex(item => item.Id == edit.Id);
            if (index >= 0 && stored[index].ExportedUrl is null)
            {
                stored[index] = stored[index] with { Description = edit.Description, Owner = edit.Owner, Due = edit.Due };
            }
        }

        return Task.FromResult(List(id));
    }

    public Task<ActionItemsExportResult> ExportActionItemsAsync(
        string id, string target, IReadOnlyList<string> itemIds, CancellationToken cancellationToken = default)
    {
        ActionItemExports.Add((id, target, itemIds));
        if (ActionItemsExportError is not null)
        {
            return Task.FromException<ActionItemsExportResult>(ActionItemsExportError);
        }

        var stored = Items(id);
        var created = new List<CreatedTask>();
        var failed = new List<FailedTask>();
        foreach (var itemId in itemIds)
        {
            var index = stored.FindIndex(item => item.Id == itemId);
            if (ExportFailures.TryGetValue(itemId, out var error))
            {
                failed.Add(new FailedTask(itemId, error));
            }
            else if (index >= 0)
            {
                var url = $"https://{target}.test/{itemId}";
                stored[index] = stored[index] with { ExportedUrl = url };
                created.Add(new CreatedTask(itemId, url));
            }
        }

        return Task.FromResult(new ActionItemsExportResult(created, failed));
    }

    private List<ActionItem> Items(string id) =>
        ActionItems.TryGetValue(id, out var items) ? items : ActionItems[id] = [];

    private ActionItemList List(string id) => new([.. Items(id)], [.. TaskTargets]);
}
