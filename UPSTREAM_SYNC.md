# Upstream Sync Ledger

This repository combines two independently maintained source lines. Import changes selectively and keep a separate review cursor for each source.

## Source revisions used for the combined baseline

| Source | Repository | Baseline head | Last reviewed SHA | Review status |
|---|---|---|---|---|
| Claude | https://github.com/jens-duttke/usage-monitor-for-claude | `3e2cfc3b2eb15e1f8b9b08e2b0d470750f84bad1` | `987fc0005291f98df2859d083431370bde313e16` | Synced through v1.23.0 by selective review |
| Codex | https://github.com/ihor-sokoliuk/usage-monitor-for-codex | `cbd5996b38fa8bbf62a98034bc60e926bc3bed96` | `cbd5996b38fa8bbf62a98034bc60e926bc3bed96` | Synced; no newer upstream commits on 2026-09-27 |

Common ancestor: `f9224c2667ce7210464590d1e5e3f5d8637c8c69`.

"Synced" means every upstream commit through the listed cursor was reviewed and classified. It does not mean the combined source tree is identical to either standalone application.

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
| 2026-09-27 | Claude | `3e2cfc3..987fc00` (27 commits) | Selectively ported seven behavior commits and two supporting documentation commits; classified all remaining commits below |
| 2026-09-27 | Codex | `cbd5996..cbd5996` (0 commits) | Current upstream head equals the existing Codex review cursor |

### Claude commits reviewed and skipped on 2026-09-27

| Source SHA | Reason |
|---|---|
| `501c3ea` | Claude issue template points feature requests to its Discussions |
| `eecd55c`, `0ca00a6` | Linux support and launcher do not apply to this Windows-only product |
| `7030a81` | Repairs tests specific to the standalone Linux/Windows platform split |
| `b5fc52a`, `987fc00` | Standalone Claude release version bumps |
| `d89df18`, `4f49926` | Claude maintainer release command and WinGet fork procedure |
| `4344671`, `3b4a001`, `2851b30`, `c374112` | Temporary Claude token diagnostic workflow and its removal |
| `8d7899e` | Reviewed and skipped: prepaid credits construct an organization-specific provider URL dynamically, conflicting with the fixed-literal Claude URL boundary; no prepaid request or UI was imported |
| `9e6ab88`, `3c5308d`, `259393e` | Claude download warning, related-project links, and plan-list prose are standalone documentation |
| `fe1b3b8` | Merge commit; no separate behavior beyond commits classified here |
| `62242da` | Reviewed and skipped: signing targets the standalone Claude release EXE and needs a combined-product signing identity and certificate |

## Import history

The initial combined repository is a fresh integration rather than a merge commit. Future selective imports should append one row per source commit:

| Date | Source | Source SHA | Method | Notes |
|---|---|---|---|---|
| 2026-08-23 | Claude | `3e2cfc3b2eb15e1f8b9b08e2b0d470750f84bad1` | Baseline copy plus restructuring | Newer shared runtime and Claude provider mapped into `usage_monitor` |
| 2026-08-23 | Codex | `cbd5996b38fa8bbf62a98034bc60e926bc3bed96` | Manual provider port | Codex app-server boundary and selected reliability behavior integrated without restoring standalone identity |
| 2026-09-27 | Claude | `8a8df15` | Manual shared port | Null reset timestamps become empty event-command variables for both providers |
| 2026-09-27 | Claude | `b00aede` | Manual Claude port | Windows certificate-store validation and distinct Claude certificate error; pinned truststore dependency |
| 2026-09-27 | Claude | `bcc7bde` | Manual shared port | Independent reduced idle polling, reset alignment, uncovered-popup cadence, and screensaver detection |
| 2026-09-27 | Claude | `7f15085` | Manual shared port | Preserve redirected frozen verbose stdout and stderr |
| 2026-09-27 | Claude | `39bba11` | Adapted Claude port | Claude Code CLI authentication and login copy in all shipped locales |
| 2026-09-27 | Claude | `61fc445` | Adapted shared/Claude port | Hide announced inactive code names consistently; mark scoped account limits so they remain visible |
| 2026-09-27 | Claude | `3bd6d62` | Adapted documentation | Explain quota visibility and event-variable eligibility in combined docs |
| 2026-09-27 | Claude | `063758d` | Adapted shared port | Use effective Claude config directory in diagnostics and redact both home path spellings |
| 2026-09-27 | Claude | `b4a258f` | Adapted documentation | Note symlink/junction redaction fix in the combined changelog |
