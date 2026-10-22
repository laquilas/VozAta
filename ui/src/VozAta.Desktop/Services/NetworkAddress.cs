using System.Net;
using System.Net.Sockets;

namespace VozAta.Desktop.Services;

/// <summary>
/// Where a configured server lives, this PC or another one (phase 43). The same rules as the
/// engine's <c>net.py</c>, so the Config page and the engine agree on what is remote.
/// </summary>
public static class NetworkAddress
{
    /// <summary>
    /// Loopback names and addresses only. An empty or unparsable URL and an unspecified address
    /// (<c>0.0.0.0</c>, <c>::</c>) count as local; this PC's own LAN address is remote on purpose.
    /// </summary>
    public static bool IsLocalUrl(string? url)
    {
        if (HostOf(url) is not { Length: > 0 } host)
        {
            return true;
        }

        if (host == "localhost" || host.EndsWith(".localhost", StringComparison.Ordinal))
        {
            return true;
        }

        if (!IPAddress.TryParse(host, out var address))
        {
            return false; // a name such as gpu-box
        }

        if (address.AddressFamily == AddressFamily.InterNetworkV6 && address.IsIPv4MappedToIPv6)
        {
            address = address.MapToIPv4();
        }

        return IPAddress.IsLoopback(address) || address.Equals(IPAddress.Any) || address.Equals(IPAddress.IPv6Any);
    }

    /// <summary>The host name without scheme, port or path; the raw text when none parses.</summary>
    public static string Host(string url) => HostOf(url) is { Length: > 0 } host ? host : url.Trim();

    private static string? HostOf(string? url)
    {
        var text = url?.Trim();
        if (string.IsNullOrEmpty(text))
        {
            return null;
        }

        var absolute = text.Contains("://", StringComparison.Ordinal) ? text : $"http://{text}";
        return Uri.TryCreate(absolute, UriKind.Absolute, out var uri)
            ? uri.Host.Trim('[', ']').ToLowerInvariant()
            : null;
    }
}
