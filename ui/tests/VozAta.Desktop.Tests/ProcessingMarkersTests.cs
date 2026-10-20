using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class ProcessingMarkersTests
{
    [Fact]
    public void A_done_meeting_is_unseen_until_cleared()
    {
        var markers = new ProcessingMarkers();
        Assert.False(markers.IsUnseen("a"));

        markers.MarkDone("a");
        markers.MarkDone("a"); // idempotent
        markers.MarkDone("b");
        Assert.Equal((true, true), (markers.IsUnseen("a"), markers.IsUnseen("b")));

        markers.Clear("a");
        markers.Clear("missing");
        Assert.Equal((false, true), (markers.IsUnseen("a"), markers.IsUnseen("b")));
    }
}
