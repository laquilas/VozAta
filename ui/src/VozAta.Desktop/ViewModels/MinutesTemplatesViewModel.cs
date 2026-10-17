using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Client;

namespace VozAta.Desktop.ViewModels;

/// <summary>A minutes template in a picker; the name is replaced in place when the language changes.</summary>
public sealed partial class TemplateOption(string id, string name) : ObservableObject
{
    public string Id { get; } = id;

    [ObservableProperty]
    public partial string Name { get; set; } = name;

    public override string ToString() => Name;
}

/// <summary>
/// The engine's minutes templates (phase 20), shared by the Start screen and "Regenerate minutes".
/// Reloading keeps the same <see cref="TemplateOption"/> objects, so pickers keep their selection.
/// </summary>
public sealed class MinutesTemplatesViewModel(IEngineClient client)
{
    public ObservableCollection<TemplateOption> Items { get; } = [];

    /// <summary>Read <c>GET /templates</c>; engine errors propagate to the caller.</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        var templates = await client.GetTemplatesAsync(cancellationToken);
        foreach (var stale in Items.Where(item => templates.All(template => template.Id != item.Id)).ToList())
        {
            Items.Remove(stale);
        }

        for (var index = 0; index < templates.Count; index++)
        {
            var template = templates[index];
            if (Find(template.Id) is { } existing)
            {
                existing.Name = template.Name;
            }
            else
            {
                Items.Insert(Math.Min(index, Items.Count), new TemplateOption(template.Id, template.Name));
            }
        }
    }

    public TemplateOption? Find(string? id) => Items.FirstOrDefault(item => item.Id == id);
}
