# Upstream Sync Ledger

This repository combines two independently maintained source lines. Import changes selectively and keep a separate review cursor for each source.

## Source revisions used for the combined baseline

| Source | Repository | Baseline head | Last reviewed SHA |
|---|---|---|---|
| Claude | https://github.com/jens-duttke/usage-monitor-for-claude | `3e2cfc3b2eb15e1f8b9b08e2b0d470750f84bad1` | `3e2cfc3b2eb15e1f8b9b08e2b0d470750f84bad1` |
| Codex | https://github.com/ihor-sokoliuk/usage-monitor-for-codex | `cbd5996b38fa8bbf62a98034bc60e926bc3bed96` | `cbd5996b38fa8bbf62a98034bc60e926bc3bed96` |

Common ancestor: `f9224c2667ce7210464590d1e5e3f5d8637c8c69`.

The Claude source supplies the newer shared UI/runtime baseline. The Codex source supplies the Codex provider adapter, app-server transport, updater/logging behavior, Codex identity tests, fixtures, and provider-specific documentation. The combined product introduces a new package and Windows identity rather than treating either source as a fork target.

## Source path map

| Claude source | Codex source | Combined destination | Rule |
|---|---|---|---|
| `usage_monitor_for_claude/` shared modules | `usage_monitor_for_claude/` shared modules | `usage_monitor/` | Start from the newer Claude shared UI and manually port provider-neutral Codex fixes |
| `usage_monitor_for_claude/api.py` | n/a | `usage_monitor/providers/claude/` | Claude credentials and HTTPS stay entirely within the Claude provider boundary |
| `usage_monitor_for_claude/claude_cli.py` | n/a | `usage_monitor/providers/claude/` | Preserve native CLI recovery and display-only custom CLI behavior |
| n/a | `usage_monitor_for_claude/api.py` | `usage_monitor/providers/codex/api.py` | Preserve Codex normalization/classification and tri-state profile contract |
| n/a | `usage_monitor_for_claude/app_server.py` | `usage_monitor/providers/codex/app_server.py` | Preserve JSONL transport, generation atomicity, Job-object lifecycle, and redaction |
| n/a | `usage_monitor_for_claude/codex_cli.py` | `usage_monitor/providers/codex/codex_cli.py` | Preserve native discovery, version reporting, and fixed official updater |
| provider-specific `cache.py` behavior | provider-specific `cache.py` behavior | provider cache/supervisor components under `usage_monitor/providers/` | Keep cooldown, recovery, identity, and error state independent per provider |
| `usage_monitor_for_claude/__main__.py` | `usage_monitor_for_claude/__main__.py` | `usage_monitor/__main__.py` | Combined supervisor, two detached tray icons, and both provider-home flags |
| `usage_monitor_for_claude.spec` | `usage_monitor_for_codex.spec` | `usage_monitor.spec` | Preserve all required assets and produce the new combined executable identity |
| `usage_monitor_for_claude.ico` and notification logo | `usage_monitor_for_codex.ico` | combined assets under `usage_monitor/` and repository root | Keep provider icons distinguishable while using one product notification identity |
| `tests/` | `tests/` plus `tests/fixtures/codex/` | `tests/` | Retain provider suites and add cross-provider isolation/lifecycle tests |
| `locale/` | `locale/` | `locale/` | Retain shared keys and use provider-aware copy without multiplying keys per quota field |
| README/docs/privacy | README/docs/privacy | combined documentation | State Claude and Codex data flows separately; never generalize one provider's claim to the other |

## Prohibited sync operations

- Never merge or rebase either source repository wholesale into this combined repository.
- Never use GitHub's one-click **Sync fork** for either source.
- Never resolve a conflict by restoring the standalone package, executable, mutex, autostart, AUMID, settings, or log identity.
- Never import Claude credential handling into shared or Codex code.
- Never import Codex's no-provider-HTTP claim as a statement about Claude.
- Never replace the Codex app-server transport with direct credential or HTTP access.
- Never restore Claude-only `claude update` behavior as a Codex updater or replace fixed `codex update` with download scraping.
- Agents do not perform commit-producing cherry-picks. The user owns history operations after reviewing a proposed import.

## Review procedure

Review each source independently:

1. Fetch the source without modifying the combined worktree.
2. Enumerate every commit after that source's own last-reviewed SHA. Do not use a shared cursor.
3. Inspect the full patch for each commit and classify it as shared UI/runtime, Claude provider, Codex provider, packaging/identity, docs, or irrelevant.
4. Record every imported and skipped commit with its source and reason.
5. Manually translate changes through the path map. Use commit-producing cherry-picks only when the user explicitly chooses to do so and the commit is proven cleanly portable.
6. Run focused tests for the changed provider, the shared suite, and cross-provider isolation tests.
7. Perform a native Windows source smoke and clean frozen build. Verify two icons, independent provider failures, one combined process identity, and complete Codex child cleanup.
8. Advance only the reviewed source's cursor.

## Review history

| Review date | Source | Range | Result |
|---|---|---|---|
| 2026-08-23 | Claude | common ancestor through `3e2cfc3b2eb15e1f8b9b08e2b0d470750f84bad1` | Selected as the newer shared/UI baseline and Claude provider source |
| 2026-08-23 | Codex | common ancestor through `cbd5996b38fa8bbf62a98034bc60e926bc3bed96` | Codex provider, transport, fixtures, updater/logging, and provider-neutral fixes mapped into the combined design |

## Import history

The initial combined repository is a fresh integration rather than a merge commit. Future selective imports should append one row per source commit:

| Date | Source | Source SHA | Method | Notes |
|---|---|---|---|---|
| 2026-08-23 | Claude | `3e2cfc3b2eb15e1f8b9b08e2b0d470750f84bad1` | Baseline copy plus restructuring | Newer shared runtime and Claude provider mapped into `usage_monitor` |
| 2026-08-23 | Codex | `cbd5996b38fa8bbf62a98034bc60e926bc3bed96` | Manual provider port | Codex app-server boundary and selected reliability behavior integrated without restoring standalone identity |
