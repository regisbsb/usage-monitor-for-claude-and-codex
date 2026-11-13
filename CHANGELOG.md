# Changelog

All notable changes to Usage Monitor for Claude and Codex are documented here.

This is a fresh combined product derived from [Usage Monitor for Claude](https://github.com/jens-duttke/usage-monitor-for-claude) and [Usage Monitor for Codex](https://github.com/ihor-sokoliuk/usage-monitor-for-codex). Their pre-combination release histories remain in their respective repositories. Exact source revisions are recorded in [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md).

## [Unreleased]

### Added

- Each provider's [`popup_fields`](docs/configuration.md#popup-field-exclusions) now accepts exact exclusions such as `["*", "-iguana_necktie"]` to hide specific popup bars while keeping the other active quotas visible.
- Optional [work-hour pacing](docs/configuration.md#work-hour-pacing) pauses long-quota markers outside the configured hours and uses the same pace for tray overage and time-aware alerts.
- An optional [forecast chart](docs/configuration.md#usage-forecast-chart) shows recent quota usage and estimates when the top tray quota might run out.

### Fixed

- Long tray tooltips, including custom Claude configuration names and emoji, are shortened to fit Windows without interrupting updates.
- Malformed `time_format` and `icon_style` arrays or objects are ignored with a settings warning instead of crashing startup, including in provider sections.
- Each provider's reset commands receive utilization and reset timestamps for all active quotas, with the existing compatibility values preserved.
- Codex CLI version and update output is decoded as UTF-8; failed version commands and missing captured output are rejected safely.

## [1.0.3] - 2026-10-22

### Fixed

- Popup keyboard and mouse hooks use pointer-sized Windows results and handles, preventing lost keystrokes while either provider popup is open.
- Both providers post Windows notifications under the combined product identity with a neutral logo, five-minute expiry, and tray-balloon fallback.

### Documentation

- Added PowerShell-compatible verbose-log collection instructions alongside the rotating application log.

## [1.0.2] - 2026-09-27

### Changed

- Each provider continues polling at a slower cadence while Windows is idle or locked, with reset alignment and normal polling while an uncovered popup is open.
- Claude HTTPS now verifies certificates through the Windows certificate store, and Claude authentication messages name the CLI login command.
- Announced but inactive code-named quota fields are hidden until they gain a reset window; inactive model-scoped account limits remain visible.

### Fixed

- Reset and threshold event commands receive an empty reset timestamp when the provider reports null.
- Verbose output respects redirected stdout and stderr and redacts home paths reached through a junction or symlink.

## [1.0.1] - 2026-09-27

### Changed

- Seven-day usage bars are now divided into five equal workweek pacing sections by default; the shared `weekly_bar_parts` setting can customize the section count.

## [1.0.0] - 2026-09-01

### Added

- One Windows application now monitors Claude and Codex simultaneously through two independent tray icons, provider caches, polling loops, popups, alerts, and event-command surfaces.
- The combined product has its own executable, mutex, holder mapping, autostart value, notification identity, settings search path, and rotating log so it does not collide with either standalone monitor.
- Provider settings use nested `providers.claude` and `providers.codex` objects, with independent `--claude-config-dir` and `--codex-home` command-line flags.
- Every event command receives `USAGE_MONITOR_PROVIDER=claude` or `codex`.
- Migration guidance covers disabling both legacy standalone autostarts before enabling the single combined autostart entry.
- Provider popups and tray menus offer **Refresh now**, which explicitly bypasses normal cooldown spacing for only the selected provider while preserving its authentication and transport boundary.
- The tray project menu links to both this combined repository and the selected provider's original upstream project.

### Changed

- The public Python package is `usage_monitor` and the frozen output is `UsageMonitorForClaudeAndCodex.exe`.
- Claude preserves its selected `.credentials.json` and fixed `api.anthropic.com` OAuth flow within an isolated Claude provider boundary.
- Codex preserves its credential-free local app-server boundary, generation-atomic JSONL transport, Windows Job-object child cleanup, and optional serialized official `codex update` behavior.
- Shared UI, polling, notification, event, DPI, and Windows integration behavior is supervised at the combined product level while provider failures remain isolated.
- The authoritative combined settings file is searched beside the executable/project first and then under `~/.usage-monitor`; legacy provider files are read-only migration fallbacks.

### Fixed

- Changing **Start with Windows** from either tray icon now refreshes the checkmark in both provider menus.
- Codex quota-reset and CLI-update notifications now identify Codex instead of using Claude-specific text.

### Security

- Privacy and audit documentation now distinguishes Claude credential/HTTPS handling from Codex local app-server handling and records the shared WebView2, event-command, registry, settings, and log boundaries.
