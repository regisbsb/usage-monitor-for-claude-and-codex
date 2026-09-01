# Changelog

All notable changes to Usage Monitor for Claude and Codex are documented here.

This is a fresh combined product derived from [Usage Monitor for Claude](https://github.com/jens-duttke/usage-monitor-for-claude) and [Usage Monitor for Codex](https://github.com/ihor-sokoliuk/usage-monitor-for-codex). Their pre-combination release histories remain in their respective repositories. Exact source revisions are recorded in [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md).

## [Unreleased]

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
