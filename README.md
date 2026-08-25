# Usage Monitor for Claude and Codex

Monitor Claude and Codex usage at the same time from one Windows application.

The app runs as a single process and creates two independent tray icons - one for Claude and one for Codex. Each provider has its own cache, polling loop, popup, alerts, event commands, and failure state, so a problem with one provider does not hide or stall the other.

This repository combines selected behavior from [Usage Monitor for Claude](https://github.com/jens-duttke/usage-monitor-for-claude) and [Usage Monitor for Codex](https://github.com/ihor-sokoliuk/usage-monitor-for-codex). See [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md) for the exact source revisions and path map.

## What you get

- One portable `UsageMonitorForClaudeAndCodex.exe` with no installer or separate Python runtime
- Two provider-labelled tray icons with independent percentages, bars, tooltips, and detail popups
- Provider-specific alerts for usage thresholds and quota resets
- Adaptive polling that pauses while Windows is idle or locked and aligns updates around resets
- Optional provider-scoped event commands for reset, threshold, startup, and double-click actions
- One combined Windows autostart entry, single-instance identity, notification identity, settings file, and sanitized rotating log
- An optional loopback-only JSON [status endpoint](docs/status-endpoint.md) for local integrations to read current usage
- Thirteen UI languages and Windows-aware clock, theme, and mixed-DPI behavior

## Provider data flow

The two providers deliberately use different authentication and transport paths.

| Provider | Authentication source | Usage transport | Built-in network behavior |
|---|---|---|---|
| Claude | The selected Claude configuration directory's `.credentials.json` | OAuth HTTPS requests with the token in the `Authorization` header | Sends provider requests only to fixed `https://api.anthropic.com` endpoints |
| Codex | Account state reported by the local `codex app-server` child | JSONL RPC over the child's standard input/output | The monitor makes no Codex provider HTTP request and never inspects a Codex credential store; the external Codex child performs its own network activity |

The Codex provider can also run the installed CLI's official `codex update` command when enabled. That command can access the network and replace Codex installation files. Claude session recovery may run the native `claude update` command after an authentication failure so Claude Code can renew its own selected credentials.

See [PRIVACY.md](PRIVACY.md) for the complete local-storage and integration statement.

## Requirements

- Windows 10 or Windows 11, 64-bit
- Claude Code installed and signed in for the Claude icon
- A current native Windows Codex CLI installed and signed in with ChatGPT for the Codex icon
- Microsoft Edge WebView2 Runtime, normally present on supported Windows systems

Claude and Codex remain independent. If one CLI is missing or one account is signed out, the other provider can continue updating.

## Getting started

1. Sign in to Claude Code and Codex:

   ```powershell
   claude
   codex login
   ```

2. Place `UsageMonitorForClaudeAndCodex.exe` in its own writable folder and run it.
3. If Windows hides either new tray icon, enable **Usage Monitor for Claude and Codex** in the taskbar system-tray settings.
4. Open each icon's popup and confirm that its provider label, account, versions, and quota windows are correct.

The application writes `usage-monitor-for-claude-and-codex.log` beside the executable. The log is size-rotated and sanitized; it contains no credentials, tokens, raw provider payloads, account email addresses, raw CLI output, or event-command output.

## Tray behavior

Each icon operates on its own provider:

| Action | Result |
|---|---|
| Hover | Shows that provider's configured quota windows and reset times |
| Left-click | Opens that provider's detail popup |
| Double-click | Runs that provider's `on_double_click_command` when configured |
| **Refresh now** in a popup or tray menu | Immediately refreshes only that provider's usage and profile |
| Right-click | Opens that provider's refresh and event-command actions plus shared restart, autostart, project, and quit actions |
| Escape or click outside | Closes an unpinned popup |

An explicit **Refresh now** request is the narrow user-initiated exception to the selected provider's normal `poll_fast` successful-fetch spacing. It uses that provider's existing authentication and transport path; refreshing Claude does not call, wake, or reset Codex, and refreshing Codex does not call, wake, or reset Claude.

Restart, quit, and **Start with Windows** affect the combined application and therefore both icons. Provider usage, refreshes, alerts, and event commands remain isolated.

**Project on GitHub** contains links to this combined repository and to the original provider project represented by that tray icon.

## Provider homes

The default roots are `~/.claude` and `~/.codex`. Select different roots with independent flags:

```powershell
.\UsageMonitorForClaudeAndCodex.exe `
  --claude-config-dir="C:\ProviderHomes\claude-work" `
  --codex-home="C:\ProviderHomes\codex-work"
```

Both `--flag=value` and `--flag value` forms are accepted. The selected roots are passed only to their matching provider. The restart and autostart command preserve both flags.

`--codex-home` separates Codex configuration and monitor state, but separate Codex accounts also require file-backed credentials in every home:

```toml
cli_auth_credentials_store = "file"
```

Keyring-backed Codex credentials can be shared machine-wide; the app does not inspect or attempt to isolate that keyring.

## Settings

Create `usage-monitor-settings.json` beside the executable. Source runs use the repository root. If `USAGE_MONITOR_CONFIG_DIR` is set, its settings file takes priority; otherwise the combined fallback is `~/.usage-monitor/usage-monitor-settings.json`.

Shared product settings are top-level. Provider-specific settings are nested:

```json
{
  "language": "en",
  "time_format": "24h",
  "log_max_bytes": 2097152,
  "log_backup_count": 3,
  "providers": {
    "claude": {
      "poll_interval": 180,
      "icon_fields": ["five_hour", "seven_day"],
      "alert_thresholds_five_hour": [50, 80, 95]
    },
    "codex": {
      "poll_interval": 180,
      "auto_update_codex_cli": false,
      "icon_fields": ["five_hour", "seven_day"]
    }
  }
}
```

When no combined settings file exists, legacy Claude and Codex settings can be read independently as migration fallbacks. The combined app never writes or modifies those files. Once a combined file exists, it is authoritative; move provider-specific keys into the matching `providers` object.

See [Configuration](docs/configuration.md) for the schema, migration behavior, display fields, polling, alerts, CLI updates, and colors.

## Migrating from the standalone monitors

The combined application has a new Windows identity and can technically run beside both older programs, but running all three would duplicate polling and notifications. Migrate deliberately:

1. Open the standalone Claude tray icon and disable **Start with Windows**.
2. Open the standalone Codex tray icon and disable **Start with Windows**.
3. Quit both standalone applications.
4. Create the combined nested settings file, or start once with no combined file to use the legacy read-only fallbacks.
5. Start `UsageMonitorForClaudeAndCodex.exe` and enable its single **Start with Windows** entry if desired.
6. Verify that exactly two icons belong to the combined process and that the legacy processes do not restart after sign-in.

The new identity uses mutex `UsageMonitorForClaudeAndCodex_SingleInstance`, holder mapping `UsageMonitorForClaudeAndCodex_HolderPID`, and the exact `UsageMonitorForClaudeAndCodex` name for both its autostart value and notification AppUserModelID. It does not reuse either standalone product's identity.

## Event commands

Event commands are configured inside the matching provider object. Every invocation includes `USAGE_MONITOR_PROVIDER=claude` or `USAGE_MONITOR_PROVIDER=codex`.

Use that variable when one script handles both providers. Commands run with the same Windows privileges as the app and may access files, launch programs, or use the network exactly as configured. See [Event Commands](docs/event-commands.md).

## Building and verifying

Use native Windows PowerShell from an NTFS clone:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --requirement requirements.txt
python -m unittest discover -s tests
python -m usage_monitor --verbose
python build.py
.\dist\UsageMonitorForClaudeAndCodex.exe --verbose
```

The build configuration lives in `usage_monitor.spec`. A complete smoke test checks:

- two distinct provider icons appear from one process;
- each popup shows only its own provider's data;
- one provider can fail without stopping the other;
- restart and quit stop both tray-message loops and the Codex app-server child;
- only the combined mutex, holder mapping, autostart value, AUMID, settings, and log identities are used;
- the frozen executable launches from a path unrelated to the checkout;
- old standalone Claude and Codex monitors can remain installed without identity collisions, although their autostarts should stay disabled.

The optional Codex live-wire probe is manual and read-only. Never automate logout, login, credential changes, or credential-store inspection.

## Security and transparency

- No telemetry or analytics
- No dynamic endpoints, encoded destinations, obfuscated logic, or dynamic code execution
- Provider security boundaries are isolated and covered by provider-specific tests
- Shared pywebview/WebView2 components may use local loopback or runtime caches
- Enabling autostart and the notification identity writes combined-product values to the current user's Windows registry
- The combined rotating log is a local file; settings are user-created and read-only to the app
- User-configured event commands are unrestricted by design and fall outside the built-in provider network boundary

## Contributing and upstream updates

Read [AGENTS.md](AGENTS.md) before making changes. The two source repositories have independent review cursors; never merge either upstream wholesale. Record selective imports in [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md), run the full Windows suite, and smoke-test both providers after shared UI changes.

## Credits and disclaimer

This project derives from Jens Duttke's MIT-licensed Usage Monitor for Claude and Ihor Sokoliuk's MIT-licensed Codex port. Preserve both source histories and copyright notices when importing work.

This is an independent community project. It is not created, endorsed, or officially supported by Anthropic or OpenAI. Claude, Anthropic, Codex, ChatGPT, and OpenAI are used descriptively to indicate compatibility and are trademarks of their respective owners.

## License

MIT - see [LICENSE](LICENSE).
