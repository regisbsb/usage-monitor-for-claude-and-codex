# Event Commands

Each provider can launch user-configured Windows shell commands when its quota resets, a threshold is crossed, its first successful update completes, or its tray icon is double-clicked.

Event commands are provider-scoped. A Claude event never runs a Codex command and a Codex event never runs a Claude command.

## Configuration

Place commands inside the matching provider object in `usage-monitor-settings.json`:

```json
{
  "providers": {
    "claude": {
      "on_reset_command": "powershell -NoProfile -File .\\on-reset.ps1"
    },
    "codex": {
      "on_threshold_command": [
        "powershell -NoProfile -File .\\on-threshold.ps1",
        "mplay32 /play /close C:\\Windows\\Media\\notify.wav"
      ],
      "on_double_click_command": "codex"
    }
  }
}
```

Supported keys:

| Key | Trigger |
|---|---|
| `on_reset_command` | That provider reports a usage drop/reset |
| `on_threshold_command` | That provider crosses a configured threshold |
| `on_startup_command` | That provider completes its first successful update after app start/restart |
| `on_double_click_command` | The matching provider tray icon is double-clicked |

Each setting accepts one non-empty command string or an array of non-empty strings. An empty string or array disables the command. Relative paths resolve from the executable directory, or the repository root in source mode.

## Execution behavior

Commands run with the same Windows user privileges as the application. They can launch programs, read or write files, and access networks. Review every command and script; do not place secrets directly in the JSON settings file.

Automatic reset, threshold, and startup commands are fire-and-forget. Their output is discarded and a background failure never displays a dialog.

The **Test event commands** menu and tray double-click are user-driven. Their output is captured on a daemon thread so the icon, popup, and polling loops remain responsive. A nonzero test result displays an error dialog. A double-click command surfaces only an early launch/configuration failure; a later application exit is printed but does not interrupt the user.

Testing performs real side effects. A test command can send a real network message or modify files.

## Provider identity

Every invocation receives one of:

```text
USAGE_MONITOR_PROVIDER=claude
USAGE_MONITOR_PROVIDER=codex
```

This variable is always present and is the authoritative way for one script to distinguish providers.

Example PowerShell routing:

```powershell
switch ($env:USAGE_MONITOR_PROVIDER) {
    'claude' { $prefix = '[Claude]' }
    'codex'  { $prefix = '[Codex]' }
    default  { exit 2 }
}

$message = "$prefix $env:USAGE_MONITOR_VARIANT reached $env:USAGE_MONITOR_UTILIZATION%"
Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show($message, $env:USAGE_MONITOR_TITLE) | Out-Null
```

## Common environment variables

| Variable | Meaning |
|---|---|
| `USAGE_MONITOR_VERSION` | Combined application version |
| `USAGE_MONITOR_PROVIDER` | `claude` or `codex` |
| `USAGE_MONITOR_EVENT` | `reset`, `threshold`, `startup`, or `double_click` |

## Reset event

| Variable | Meaning |
|---|---|
| `USAGE_MONITOR_VARIANT` | Normalized quota field that dropped |
| `USAGE_MONITOR_UTILIZATION` | Current rounded utilization |
| `USAGE_MONITOR_PREV_UTILIZATION` | Previous rounded utilization |
| `USAGE_MONITOR_RESETS_AT` | Current reset timestamp, or empty |
| `USAGE_MONITOR_TITLE` | Localized notification title |
| `USAGE_MONITOR_MESSAGE` | Localized notification body |
| `USAGE_MONITOR_UTILIZATION_FIVE_HOUR` | Compatibility value for the provider's `five_hour`, or `0` |
| `USAGE_MONITOR_UTILIZATION_SEVEN_DAY` | Compatibility value for the provider's `seven_day`, or `0` |

Reset commands can fire for any normalized quota field, not only the compatibility pair.

## Threshold event

| Variable | Meaning |
|---|---|
| `USAGE_MONITOR_VARIANT` | Normalized quota field that crossed a threshold |
| `USAGE_MONITOR_UTILIZATION` | Current rounded utilization |
| `USAGE_MONITOR_THRESHOLD` | Highest newly crossed threshold |
| `USAGE_MONITOR_RESETS_AT` | Reset timestamp, or empty |
| `USAGE_MONITOR_TITLE` | Localized notification title |
| `USAGE_MONITOR_MESSAGE` | Localized notification body |

Claude can additionally emit `USAGE_MONITOR_EXTRA_USED` and `USAGE_MONITOR_EXTRA_LIMIT` when its normalized extra-usage state is active. Codex does not emit these from raw app-server credits metadata.

## Startup and double-click snapshots

The command receives a pair for every detected quota field:

```text
USAGE_MONITOR_UTILIZATION_<FIELD>
USAGE_MONITOR_RESETS_AT_<FIELD>
```

The field name is uppercased. For example, `seven_day_gpt_5_pro` becomes `USAGE_MONITOR_UTILIZATION_SEVEN_DAY_GPT_5_PRO`. A missing reset is an empty string. Duration-less Codex windows still emit variables.

An announced code-named quota with no active reset window is omitted from event variables, matching the popup and tray. A duration-named quota or a marked Claude account limit remains available before its first window.

Double-click before a provider's first successful update supplies only common variables. Startup commands wait for that provider's first successful update; the other provider's success does not trigger them.

## Idle and notification behavior

Each provider keeps polling at a reduced cadence while Windows is idle or locked. Reset alignment still confirms a reset promptly, including when no reset command is configured. An uncovered open popup keeps the normal cadence. The other provider remains independent.

Desktop notifications are deferred while the user is away. Event commands themselves are not deferred.

## Network boundary

An event command's network or filesystem activity belongs to that user-configured command. It does not change the built-in provider claims:

- Claude built-in provider HTTPS is restricted to fixed `api.anthropic.com` endpoints.
- Codex built-in provider uses local app-server stdio and makes no provider HTTP request.

For example, a command using `curl`, PowerShell `Invoke-WebRequest`, or another CLI is an additional destination explicitly selected by the user.
