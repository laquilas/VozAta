using System.ComponentModel;
using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using Microsoft.Win32;

namespace VozAta.Worker.Services;

/// <summary>Start VozAta Worker when the user signs in to Windows.</summary>
public interface IStartupRegistry
{
    bool IsEnabled { get; }

    void Apply(bool enabled);
}

/// <summary>Let other PCs reach the worker: inbound rules on the Private network profile.</summary>
public interface IFirewall
{
    /// <summary>False when the user declined the administrator prompt or the rules failed.</summary>
    Task<bool> AllowAsync(int httpPort, int discoveryPort);
}

/// <summary>HKCU <c>Run</c> value, started minimized to the tray.</summary>
[ExcludeFromCodeCoverage(Justification = "Writes the Windows registry; covered by the manual check.")]
public sealed class RegistryStartup(string executable) : IStartupRegistry
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "VozAta Worker";

    public bool IsEnabled =>
        OperatingSystem.IsWindows() && Registry.CurrentUser.OpenSubKey(RunKey)?.GetValue(ValueName) is not null;

    public void Apply(bool enabled)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        using var key = Registry.CurrentUser.CreateSubKey(RunKey);
        if (enabled)
        {
            key.SetValue(ValueName, $"\"{executable}\" --minimized");
        }
        else
        {
            key.DeleteValue(ValueName, throwOnMissingValue: false);
        }
    }
}

/// <summary><c>netsh advfirewall</c> as administrator (one UAC prompt for both rules).</summary>
[ExcludeFromCodeCoverage(Justification = "Asks for elevation; covered by the manual check.")]
public sealed class NetshFirewall : IFirewall
{
    public async Task<bool> AllowAsync(int httpPort, int discoveryPort)
    {
        const string rule = "netsh advfirewall firewall";
        var commands = string.Join(
            " & ",
            $"{rule} delete rule name=\"VozAta Worker\"",
            $"{rule} delete rule name=\"VozAta Worker discovery\"",
            $"{rule} add rule name=\"VozAta Worker\" dir=in action=allow protocol=TCP localport={httpPort} profile=private",
            $"{rule} add rule name=\"VozAta Worker discovery\" dir=in action=allow protocol=UDP localport={discoveryPort} profile=private");
        var start = new ProcessStartInfo("cmd.exe", $"/c ({commands}) >nul")
        {
            UseShellExecute = true,
            Verb = "runas",
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        try
        {
            using var process = Process.Start(start);
            if (process is null)
            {
                return false;
            }

            await process.WaitForExitAsync();
            return process.ExitCode == 0;
        }
        catch (Win32Exception)
        {
            return false; // the administrator prompt was declined
        }
    }
}
