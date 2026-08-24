# Project Guidelines

This file is the authoritative repository guidance for Usage Monitor for Claude and Codex. The application is a single Windows process that supervises two provider monitors and displays two independent tray icons. Apply Python best practices, change only what the task requires, and keep provider boundaries easy to audit.

## Platform and workflow

- This is a Windows-only application. Windows APIs through `ctypes.windll` and `winreg` may be used unconditionally; do not add `sys.platform` branches.
- Develop, test, and build with native Windows Python from an NTFS clone. Do not run Win32 tests or builds from WSL or a `\\wsl.localhost` path.
- Activate `.\.venv\Scripts\Activate.ps1` before running Python commands.
- Read `AGENTS.local.md` at the start of local work when it exists. It is ignored machine-specific guidance and must never be copied into tracked files or public output.
- Agents do not commit, push, tag, publish releases, or perform destructive Git operations. Preserve unrelated worktree changes.

## Combined architecture

- The public package is `usage_monitor` and the frozen executable is `UsageMonitorForClaudeAndCodex.exe`.
- One supervisor owns two provider monitors, `claude` and `codex`. Each provider has an independent cache, poll loop, tray icon, popup state, alerts, and event commands. A slow or failing provider must not block the other.
- pywebview runs its GUI loop on the main thread. The two pystray icons run detached on their own threads. Quit and restart must stop both icon message pumps; stopping one icon does not stop the other.
- Shared UI behavior belongs outside provider packages. Provider authentication, transport, normalization, recovery, CLI integration, and provider-specific settings belong under `usage_monitor/providers/`.
- Shared code consumes normalized quota dictionaries; it must not branch on raw provider payloads.

## Provider interface and fields

- Provider identifiers are fixed literals: `claude` and `codex`.
- A provider fetch returns normalized usage plus profile state as one provider cycle. Profile semantics are three-valued: a profile dictionary replaces cached state, `{}` is authoritative signed-out state, and `None` preserves the prior profile.
- Quota entries are top-level dictionaries with `utilization` and `resets_at`; optional display metadata may be added without changing those keys. Null windows are skipped and a missing reset is `''`.
- Never hardcode a closed quota-field list in display, alert, reset, event-variable, or sorting code. Parse duration-derived fields generically and leave unparseable fields displayable without time markers or dividers.
- Credits and extra-usage data are active only where the provider explicitly normalizes them. Do not infer Codex credits support from raw app-server metadata.

## Claude security boundary

- Claude code reads only the selected Claude configuration directory's `.credentials.json`, chosen by `--claude-config-dir`, `CLAUDE_CONFIG_DIR`, or the default `~/.claude`.
- Claude OAuth requests go only to fixed top-level literals under `https://api.anthropic.com`. Never construct provider URLs dynamically.
- The OAuth token is used only in the `Authorization` header. Never log, persist, render, hash for telemetry, or include it in exceptions.
- On a 401, Claude recovery may invoke only the fixed native `claude update` command, re-read the same selected credentials file, and retry according to the provider's episode guard. Do not route authentication through display-only CLI commands.
- Credential reads and Claude HTTP calls remain isolated in the Claude provider. Other modules must not inspect Claude credential contents.

## Codex security boundary

- Codex code must not inspect a credential store in any way: no contents, path construction, existence check, timestamp, watcher, keyring lookup, or metadata. Authentication state comes only from the local app-server account response.
- The built-in Codex provider makes no provider HTTP request. It launches the fixed local `codex app-server` command and communicates through JSONL stdio. The Codex child owns its authentication, network, logs, and state.
- App-server method names and known handshake/notification names must be fixed auditable constants or literals. Do not construct method names dynamically.
- One logical provider operation holds the operation lock across all RPCs, pins a single child generation, and retries the whole operation at most once after child death. Never return mixed-generation partial results.
- Keep the app-server child in a kill-on-close Windows Job object. Startup failure, Job-object failure, timeout, restart, and shutdown paths must kill, wait for, and close child resources.
- Unknown RPC errors default to transient. Authentication classification requires exact code/data evidence recorded in the synthetic fixture notes; never guess from message substrings.
- Automatic Codex CLI updates may invoke only the fixed official `codex update` command. Serialize the updater against provider operations, stop the app-server first, and never log raw subprocess output.

## Shared process, storage, and Windows identity

- The application owns one product-level mutex `UsageMonitorForClaudeAndCodex_SingleInstance`, one holder mapping `UsageMonitorForClaudeAndCodex_HolderPID`, one autostart value `UsageMonitorForClaudeAndCodex`, and one AppUserModelID `UsageMonitorForClaudeAndCodex`.
- Never restore the standalone Claude or Codex mutex, mapping, autostart, or AUMID names. The combined process is the singleton, not either provider icon.
- The combined settings filename is `usage-monitor-settings.json`. Authoritative search order is the executable/project directory, then `~/.usage-monitor/`. Legacy provider settings are migration fallbacks only and are never written.
- Provider-specific settings live below `providers.claude` and `providers.codex`. Shared product settings remain top-level. Do not silently accept the same flat provider key for both providers.
- `--claude-config-dir` selects the Claude configuration root and `--codex-home` selects the Codex home. Resolve both before importing modules that read settings or provider environments.
- The application log is `usage-monitor-for-claude-and-codex.log` beside the frozen executable or in the project root in source mode. Use bounded size rotation. Startup must fail visibly if the adjacent log cannot be opened.
- Logs may contain sanitized runtime diagnostics, fixed method names, timings, classifications, update versions, and utilization summaries. Never log tokens, credentials, raw provider payloads, email addresses, raw Claude/Codex output, or event-command output.

## Event commands

- Every event command receives `USAGE_MONITOR_PROVIDER=claude` or `codex` in addition to the existing event variables.
- Automatic reset, threshold, and startup commands are fire-and-forget, discard output, and never show a failure dialog.
- User-driven test actions and double-click commands capture output and may show an early/nonzero failure dialog without blocking tray, popup, or poll threads.
- Event commands are an explicit user-controlled execution surface. They run with the user's privileges and may access files, programs, and networks. They are not part of either built-in provider network boundary.

## Popup, tray, and DPI

- The popup uses pywebview with a WinForms host and Edge WebView2. pywebview 6.x `resize()` and `move()` expect logical pixels.
- `_tray_position()` receives physical dimensions for Win32 calculations and returns logical coordinates. Detect a left taskbar with `work.left > mon.left`.
- Do not replace tray-anchored `resize()`/`move()` with raw `SetWindowPos`. Pinned drag is the sole exception and deliberately uses physical cursor coordinates; reassert size with `resize()` after crossing a DPI boundary.
- Hide the taskbar window with `WS_EX_TOOLWINDOW` and removal of `WS_EX_APPWINDOW`. Do not set WinForms `ShowInTaskbar = False` because it can recreate the handle and crash WebView2.
- pystray double-click support is installed per icon only when that provider configures a double-click command. Guard click state with the icon's own lock and forward unrelated messages to the saved pystray handler.

## Polling and concurrency

- Each provider owns its polling cooldown, recovery guard, account fingerprint, notification state, and child/HTTP recovery state. Never share these mutable fields across providers.
- A successful fetch cannot occur more often than that provider's `poll_fast` interval except for its narrowly defined confirmed-account-switch path or an explicit user-initiated refresh from that provider's popup or tray menu. A manual refresh must remain provider-scoped and use only that provider's existing authentication and transport boundary.
- Reset alignment must not schedule inside the final `poll_fast - reset_buffer` seconds before a reset.
- Account identity changes must be confirmed from the same provider and must clear only that provider's alert/reset baselines.
- Mock time through the module under test. Add concurrency, boundary, empty, null, malformed, and provider-isolation tests for behavior changes.

## Dependencies, style, and build

- Runtime dependencies remain minimal and well known: requests for Claude HTTPS, Pillow, pystray, and pywebview. Codex does not use requests.
- No `eval()`, `exec()`, `compile()`, dynamic imports, obfuscation, encoded endpoints, or hidden/minified logic.
- Use module docstrings, `from __future__ import annotations`, signature type hints, numpydoc for public/nontrivial APIs, relative package imports, `__all__`, and focused modules.
- Prefer single quotes, PEP 8 with readable 140-160 character lines, hyphens rather than typographic dashes, two blank lines between top-level definitions, and explicit loops for complex conditions.
- All build configuration lives in `usage_monitor.spec`; output is `dist\UsageMonitorForClaudeAndCodex.exe`. Add assets to `datas` and hidden imports only when required.
- After every task, run `python -m unittest discover -s tests`. For dependency or packaging changes, also perform a clean build and frozen smoke on native Windows.

## Documentation and upstream sync

- Keep README, `PRIVACY.md`, configuration, API reference, event commands, changelog, and security claims synchronized.
- `UPSTREAM_SYNC.md` records the two independent source heads, separate review cursors, path translations, and every imported change. Never merge or rebase either source repository wholesale into this combined repository.
- Claude and Codex security statements are not interchangeable. Every claim must name the provider to which it applies.
- Update `[Unreleased]` for user-visible features, fixes, or behavior changes. Skip internal-only refactors.
