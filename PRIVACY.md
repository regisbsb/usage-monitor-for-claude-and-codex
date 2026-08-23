# Privacy Policy

Usage Monitor for Claude and Codex is a local Windows application that displays usage for two providers in one process. It has no telemetry or analytics and does not send account or usage data to the project authors, advertisers, or analytics services.

## Data processed locally

For each enabled provider, the app processes the account/profile information and quota data needed for its tray icon, popup, alerts, and event commands. This can include account email, plan type, quota identifiers, utilization percentages, durations, reset times, provider errors, and account-change notifications.

Raw provider responses are kept in memory only as needed by the running process. The app does not persist them.

## Claude provider

The Claude provider reads `.credentials.json` from the selected Claude configuration directory. The directory is selected by `--claude-config-dir`, `CLAUDE_CONFIG_DIR`, or the default `~/.claude`.

It extracts the Claude OAuth token and sends it only in the HTTP `Authorization` header to fixed HTTPS endpoints on `api.anthropic.com` for usage and profile reads. It does not send the token to Codex, the project authors, event commands, the popup, or the application log.

After a Claude authentication failure, the provider may invoke the installed native `claude update` command. That external Claude Code process may access the network and update the selected Claude credentials. The app then re-reads the same selected credentials file and may retry the failed provider request.

## Codex provider

The Codex provider never constructs, reads, checks, watches, timestamps, or otherwise inspects a Codex credential-file or keyring location. Authentication state, email, and plan information come only from the account response of a local `codex app-server` child.

The built-in Codex provider makes no provider HTTP request. It starts `codex app-server` and exchanges newline-delimited JSON over the child's standard input/output. The Codex child is a separate OpenAI program and performs authentication, network activity, logging, caching, and state changes according to the user's Codex configuration.

When automatic Codex CLI updates are enabled, the app may invoke the fixed official `codex update` command. That external command may access the network and replace Codex installation files under the current user's permissions. The app stops its app-server child and serializes the update against provider reads before invoking it.

## Settings and logs

The authoritative combined settings file is `usage-monitor-settings.json`. It is searched first under `USAGE_MONITOR_CONFIG_DIR` when that environment variable is set, then next to the executable or in the repository root for source runs, and finally at `~/.usage-monitor/usage-monitor-settings.json`. The app reads this user-created file and does not create or modify it.

When no combined file exists, the app can read legacy standalone Claude and Codex settings as migration fallbacks. Those legacy files are also never modified.

The app writes `usage-monitor-for-claude-and-codex.log` beside the frozen executable, or in the repository root in source mode. The size-rotated log can contain sanitized runtime information, fixed provider operation names, timings, classifications, utilization summaries, CLI versions/update outcomes, and crash traces. It must not contain credentials, tokens, credential metadata, account email addresses, raw provider JSON, raw Claude/Codex stdout or stderr, or event-command output.

If the log cannot be opened at the documented adjacent location, startup fails visibly instead of silently writing somewhere else.

## Windows integration

The combined application owns one product identity rather than one identity per provider:

- named mutex `UsageMonitorForClaudeAndCodex_SingleInstance`;
- page-file-backed holder mapping `UsageMonitorForClaudeAndCodex_HolderPID`;
- current-user Run-key value `UsageMonitorForClaudeAndCodex` when **Start with Windows** is enabled;
- AppUserModelID `UsageMonitorForClaudeAndCodex` for notification identity.

Disabling **Start with Windows** removes the combined Run-key value. The app does not remove old standalone Claude or Codex autostart entries automatically; users should disable those entries in the old applications before migration.

The holder mapping is memory-backed and disappears with the process. The packaged Python runtime, Windows, WebView2, Claude Code, and Codex CLI may create their own temporary, cache, log, credential, or state files outside the app's storage behavior.

## WebView2 and local runtime behavior

The shared pywebview/Edge WebView2 runtime may use local loopback communication and runtime caches internally. Popup content is bundled with the application; this caveat does not grant either provider permission to send account data to an additional project-controlled service.

## Event commands

Event commands are user-supplied programs. They run with the same Windows user privileges as the app and can read or write files, launch programs, and access networks exactly as configured.

Each command receives provider and event context in environment variables, including `USAGE_MONITOR_PROVIDER=claude` or `codex`. Do not place secrets directly in the settings file or event variables. Network or filesystem activity performed by an event command belongs to that user-controlled command and is not built-in Claude or Codex provider communication.

## Contact

For privacy questions, use the issue tracker associated with this combined repository.
