# Configuration

No settings file is required for the default Claude and Codex homes. To override behavior, create `usage-monitor-settings.json` containing a JSON object.

## File locations and authority

The first combined settings file found is authoritative:

1. `$USAGE_MONITOR_CONFIG_DIR/usage-monitor-settings.json`, when that environment variable is set
2. Beside `UsageMonitorForClaudeAndCodex.exe`, or in the repository root when running from source
3. `~/.usage-monitor/usage-monitor-settings.json`

The app reads settings at startup and never creates or modifies the file. Use **Restart** from either tray menu after editing it.

If no combined file exists, the app can read the standalone monitors' provider-specific settings independently as a migration fallback:

- Claude: the legacy `usage-monitor-settings.json` locations associated with the selected Claude configuration directory
- Codex: the legacy `usage-monitor-for-codex-settings.json` locations associated with the selected Codex home

Legacy files remain read-only. They do not override an existing combined file. Move their provider keys under the matching nested provider object when creating the combined file.

## Nested schema

Shared product settings stay at the top level. Provider-specific polling, quota display, alerts, event commands, and CLI behavior live under `providers.claude` or `providers.codex`.

```json
{
  "language": "en",
  "time_format": "24h",
  "weekly_bar_parts": 5,
  "log_max_bytes": 2097152,
  "log_backup_count": 3,
  "bg": "#1e1e1e",
  "providers": {
    "claude": {
      "poll_interval": 180,
      "poll_fast": 120,
      "tooltip_fields": ["five_hour", "seven_day"],
      "popup_fields": ["*"],
      "icon_fields": ["five_hour", "seven_day"],
      "alert_thresholds_five_hour": [50, 80, 95]
    },
    "codex": {
      "poll_interval": 180,
      "poll_fast": 120,
      "tooltip_fields": ["five_hour", "seven_day"],
      "popup_fields": ["*"],
      "icon_fields": ["five_hour", "seven_day"],
      "auto_update_codex_cli": false
    }
  }
}
```

Do not place provider keys at the top level in a combined file. A flat `poll_interval`, `icon_fields`, or event command would be ambiguous because the two providers have independent runtime state.

## Provider homes and flags

Claude defaults to `~/.claude`; Codex defaults to `~/.codex`. Override either independently:

```powershell
.\UsageMonitorForClaudeAndCodex.exe `
  --claude-config-dir="C:\ProviderHomes\claude-work" `
  --codex-home="C:\ProviderHomes\codex-work"
```

The flags also accept spaced values. They affect only the matching provider and are preserved by restart and the combined autostart command.

The Claude root selects the `.credentials.json` read by the Claude provider. The Codex root is passed to the local app-server child as `CODEX_HOME`; the monitor does not inspect credentials within it.

### Multiple Codex accounts

Separate Codex homes do not guarantee separate accounts when the CLI uses a shared OS keyring. For each independently monitored Codex home, configure file-backed credentials before signing in:

```toml
cli_auth_credentials_store = "file"
```

Then run `codex login` with that `CODEX_HOME`. Keyring isolation, including `auto` when it selects the keyring, is not verified by this application.

## Shared settings

The shared layer controls presentation and product-level storage. Supported shared categories include:

| Key | Default | Purpose |
|---|---:|---|
| `language` | Windows display language | UI locale: `de`, `en`, `es`, `fr`, `hi`, `id`, `it`, `ja`, `ko`, `pt-BR`, `uk`, `zh-CN`, or `zh-TW` |
| `time_format` | Windows regional clock | `24h` or `12h` |
| `log_max_bytes` | `2097152` | Maximum active combined log size; minimum `1024` |
| `log_backup_count` | `3` | Number of rotated combined logs; minimum `1` |
| `weekly_bar_parts` | `5` | Equal pacing sections shown on seven-day usage bars; integer from `1` to `31` |

Popup colors are also shared top-level strings: `bg`, `fg`, `fg_dim`, `fg_heading`, `fg_link`, `bar_bg`, `bar_fg`, `bar_fg_warn`, `bar_divider`, and `bar_marker`.

Shared settings do not merge provider account state. They only give the two provider popups a consistent product presentation.

`weekly_bar_parts` changes only the visual pacing guides. The provider's quota remains a seven-day window, and the elapsed-time marker still follows the real reset period. The default of `5` supports a five-day workweek; set it to `7` for seven equal calendar-day budgets.

## Provider polling

Each provider accepts its own polling values:

| Key | Default | Purpose |
|---|---:|---|
| `poll_interval` | `180` | Normal seconds between scheduled updates |
| `poll_fast` | `120` | Minimum successful-fetch spacing and active-use cadence |
| `poll_fast_extra` | `2` | Extra fast polls after usage stops increasing |
| `poll_error` | `30` | Cadence after a transient provider error |
| `max_backoff` | `900` | Maximum retained provider backoff where applicable |
| `idle_pause` | `300` | Seconds before idle polling slows; `0` disables idle detection |
| `idle_interval` | `900` | Minimum seconds between scheduled polls while idle or locked; an uncovered open popup keeps the normal cadence |

`poll_fast` must not exceed `poll_interval`. Successful scheduled fetches respect that provider's `poll_fast` spacing. An explicit user click on **Refresh now** in a provider popup or tray menu is the narrow exception: it requests an immediate fetch only for that provider, using the same provider-specific authentication and transport path.

Each provider has its own cooldown, backoff, reset alignment, error streak, account-switch state, and manual-refresh request. A Claude refresh or backoff must not call, wake, reset, or delay Codex, and a Codex refresh or app-server restart must not call, wake, reset, or delay Claude.

## Quota field names

Provider responses are normalized into dynamic top-level quota fields. Common examples are `five_hour`, `seven_day`, and model-scoped variants such as `seven_day_sonnet` or `seven_day_gpt_5_pro`. These are examples, not a fixed schema.

Field labels, periods, and ordering derive from the normalized name. Duration-less Codex windows use a stable fallback name and remain displayable but have no elapsed-time marker or dividers.

Do not copy a field name from one provider into the other provider's configuration unless that provider actually reports it. Missing configured fields are skipped or substituted according to the display resolver without creating fake quota rows.

An announced code-named field with no reset window is hidden until it becomes active. A duration-named quota or a model-scoped limit supplied through Claude account limits remains visible at 0% before its first active window. Active fields whose names cannot be parsed still display without time markers or dividers.

## Display fields

The following settings are provider-specific:

| Key | Default | Purpose |
|---|---|---|
| `tooltip_fields` | `['five_hour', 'seven_day']` | Ordered tooltip quota fields |
| `popup_fields` | `['*']` | Ordered popup fields; `*` inserts remaining detected quotas |
| `icon_fields` | `['five_hour', 'seven_day']` | Exactly two preferred tray slots |
| `compact_hide` | `[]` | Sections or quota bars hidden in pinned compact mode |

An `icon_fields` entry may use the `:overage` display suffix where supported, for example `five_hour:overage`. Available configured fields keep their order; missing fields can be replaced by unused detected fields in duration order. A provider with one active quota draws one centered bar rather than an empty second line.

Tray theme overrides can be placed within each provider so the two icons remain distinguishable. `icon_light` and `icon_dark` map channels such as `fg`, `fg_half`, `fg_dim`, and `fg_warn` to `[R, G, B, A]` arrays.

## Alert thresholds

Threshold settings belong to a provider and use `alert_thresholds_<field>`:

```json
{
  "providers": {
    "claude": {
      "alert_thresholds_five_hour": [50, 80, 95],
      "alert_thresholds_seven_day": [95]
    },
    "codex": {
      "alert_thresholds_five_hour": [80, 95],
      "alert_thresholds_seven_day_gpt_5_pro": [80, 95]
    }
  }
}
```

Values must be between 1 and 100. An empty list disables alerts for that field. `alert_time_aware` and `alert_time_aware_below` are also provider-specific because elapsed quota state is provider-specific.

Claude can normalize its extra-usage information when the API reports it. Codex raw credits metadata is intentionally dropped and must not activate Claude's extra-usage UI or settings.

## Event commands

These keys belong inside each provider object:

- `on_reset_command`
- `on_threshold_command`
- `on_startup_command`
- `on_double_click_command`

Each accepts one non-empty command string or an array of non-empty strings. Every invocation includes `USAGE_MONITOR_PROVIDER` so a shared script can distinguish Claude from Codex. See [Event Commands](event-commands.md).

## Claude CLI behavior

Claude's `cli_command` entries are for version display only. Authentication recovery continues to use the selected native Windows Claude CLI and the same selected `.credentials.json`.

`notify_claude_update` controls whether a successful 401 recovery that also changed the Claude CLI version produces a notification. The app does not run `claude update` as a periodic general updater; it is part of Claude authentication recovery.

## Codex CLI updates

Codex supports:

| Key | Default | Purpose |
|---|---:|---|
| `auto_update_codex_cli` | `true` | Periodically invoke the official `codex update` command |
| `codex_update_interval` | `86400` | Minimum seconds between attempts; minimum `300` |
| `notify_codex_update` | `true` | Notify only when the installed version actually changes |

Before invoking the updater, the app stops the local app-server child and serializes the command against Codex provider operations. The next Codex read starts a fresh child. `codex update` may use the network and replace CLI installation files. Disable it when a package manager or administrator owns the installation.

## Combined log

The frozen app writes `usage-monitor-for-claude-and-codex.log` beside the executable; source mode uses the repository root. Rotated files add `.1`, `.2`, and so on.

The log is shared at the product level but provider-tagged and sanitized. It must never contain tokens, credential values or metadata, account email addresses, raw provider responses, raw CLI stdout/stderr, or event-command output. Startup fails visibly if this exact location is not writable.
