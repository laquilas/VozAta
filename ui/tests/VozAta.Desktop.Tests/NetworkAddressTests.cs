using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests;

/// <summary>Local or remote (phase 43): the same rows as the engine's <c>tests/test_net.py</c>.</summary>
public sealed class NetworkAddressTests
{
    [Theory]
    [InlineData("http://localhost:11434")]
    [InlineData("http://LOCALHOST:11434")]
    [InlineData("http://foo.localhost")]
    [InlineData("http://127.0.0.1:11434")]
    [InlineData("http://127.1.2.3")]
    [InlineData("http://[::1]:11434")]
    [InlineData("localhost:11434")]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    [InlineData("http://0.0.0.0:11434")]
    [InlineData("http://[::]:11434")]
    public void Loopback_empty_and_unspecified_addresses_are_local(string? url) =>
        Assert.True(NetworkAddress.IsLocalUrl(url));

    [Theory]
    [InlineData("http://192.168.0.20:11434")]
    [InlineData("192.168.0.20:11434")]
    [InlineData("https://gpu-box.lan/ollama")]
    [InlineData("http://10.0.0.5")]
    [InlineData("http://[fe80::1]:11434")]
    [InlineData("http://gpu-box:11434")]
    public void Any_other_address_is_remote(string url) =>
        Assert.False(NetworkAddress.IsLocalUrl(url));

    [Theory]
    [InlineData("http://192.168.0.20:11434/x", "192.168.0.20")]
    [InlineData("gpu-box:11434", "gpu-box")]
    [InlineData("https://gpu-box.lan/ollama", "gpu-box.lan")]
    [InlineData("http://[fe80::1]:11434", "fe80::1")]
    [InlineData("", "")]
    public void The_host_has_no_scheme_port_or_path(string url, string host) =>
        Assert.Equal(host, NetworkAddress.Host(url));
}
