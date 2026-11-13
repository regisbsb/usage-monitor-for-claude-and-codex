# Upstream Sync Ledger

This repository combines two independently maintained source lines. Import changes selectively and keep a separate review cursor for each source.

## Source revisions used for the combined baseline

| Source | Repository | Baseline head | Last reviewed SHA | Review status |
|---|---|---|---|---|
| Claude | https://github.com/jens-duttke/usage-monitor-for-claude | `3e2cfc3b2eb15e1f8b9b08e2b0d470750f84bad1` | `e73239c4929ace99f6f80d4bfab31484b229bc34` | Reviewed through standalone v1.27.0; five selected changes manually adapted |
| Codex | https://github.com/ihor-sokoliuk/usage-monitor-for-codex | `cbd5996b38fa8bbf62a98034bc60e926bc3bed96` | `6deb0294bacbf2c02bd319cdcdb2dfdeaafa077d` | Selectively reviewed through 2026-10-23 upstream changes; three fixes imported and deferred work recorded below |

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
| 2026-10-22 | Claude | `987fc00..5f27127` (9 commits, fetched 2026-10-17) | Ported three recommended changes plus supporting hook-fix documentation; classified all nine commits below |
| 2026-10-22 | Codex | `cbd5996..cbd5996` (0 commits at the 2026-10-17 check) | Existing Codex cursor retained |
| 2026-10-24 | Claude | `14fdd6f14ef49a4686b6c820a8fb46e2f40c10ff` only ([PR #113](https://github.com/jens-duttke/usage-monitor-for-claude/pull/113)) | Targeted popup-exclusion contribution reviewed and manually ported; intervening commits not reviewed and both review cursors unchanged |
| 2026-10-24 | Claude | `5f27127..5cbccc5` (4 commits) | Reviewed the complete range; popup exclusions match the existing targeted port, prepaid-only optimization and standalone release/credit documentation skipped |
| 2026-10-24 | Codex | `cbd5996..6deb029` (95 commits: 90 inherited Claude commits and 5 Codex commits) | Reviewed the complete range against both existing provider implementations; manually ported enum validation, complete reset snapshots, and Codex CLI capture hardening; remaining changes classified below |
| 2026-11-13 | Claude | `5cbccc5..e73239c` (11 commits) | Five changes manually adapted; weekly quota fallback already present, standalone process/release changes skipped, and MCP deferred |

### Claude commits reviewed on 2026-11-13

| Source SHA | Classification and result |
|---|---|
| `302eb47` | Shared work-hour pacing ported as an opt-in schedule with independent provider overrides and the existing default guides |
| `45181f5` | Standalone contributor and PR merge instructions skipped |
| `75e8f1c` | Missing session quota already promotes the next active tray quota and uses it for adaptive polling; popup exclusions remain independent of the tray |
| `dd6b81f` | Windows tooltip limit ported; existing reset text, labels, and independent field selection retained |
| `5454751` | Standalone v1.25.0 metadata skipped |
| `56bdbb4` | Optional forecast chart ported with account-scoped history, the shared pacing scale, and calendar ticks |
| `7c13da0` | MCP deferred; a combined version needs explicit provider selection, a combined Windows channel identity, and supervisor-owned startup and shutdown |
| `0c91da2` | Standalone v1.26.0 metadata skipped |
| `22b0644` | Claude plan label and popup details ported; raw profile field logging skipped |
| `9961eff` | Manual refresh safeguards and wait feedback adapted to the existing independent tray and popup controls |
| `e73239c` | Standalone v1.27.0 metadata skipped |

### Claude commits reviewed on 2026-10-24

| Source SHA | Classification and result |
|---|---|
| `6c176f1df555df8516adffb21e75f2960e5e7e3c` | Claude provider/cache optimization skipped: the combined product does not fetch prepaid credits, and the prerequisite dynamically constructed endpoint remains excluded |
| `31e2b329de23463b562232ed9050f42d3cf2a0fe` | Standalone v1.24.0 release/version metadata skipped; preserve the combined version and identity |
| `045079fcef0bfe25b8c92ad79843c833b0420707` | Shared popup exclusions already imported from the original `14fdd6f` PR head; the upstream squash adds no missing behavior |
| `5cbccc5e6f20a03efbc6779cc3c6d8e621acdef2` | Standalone changelog attribution/prose skipped; no runtime behavior |

### Codex commits reviewed on 2026-10-24

The upstream Codex branch rebased onto Claude and then preserved its old published ancestry. The 95-commit range contains 90 commits also reachable from Claude `5cbccc5`, plus the five Codex commits below. Those 90 shared commits are covered by the Claude baseline, earlier per-commit review/import records, and the four-commit review above; they do not represent 90 additional Codex features to import.

| Source SHA | Classification and result |
|---|---|
| `3c8934b910af73b1b74ed7bb0545b92f22f99ebf` | Codex provider/shared adaptation partially imported: UTF-8 CLI capture, failed-version rejection, and generic reset-command quota snapshots. Existing account parsing, normalization, tri-state profiles, authentication classification, and provider recovery are already present. Optional settings/cadence changes are deferred below; Linux backends, standalone packaging/identity, the quick-action event rename, and inactive-quota filtering changes are skipped to preserve combined contracts |
| `ca80f5ee0dcf5a131fa6beea3430efac948ff536` | Standalone release workflow portability skipped; it targets the Codex product rather than the combined executable |
| `f5d982a49457899716a95e07db63c79d69dc2b77` | Shared validation/reset compatibility partially imported: string guards for enum settings and legacy reset-snapshot defaults. App-server lifecycle changes and their API/cache handling are deferred below; Linux, standalone version, and supporting standalone documentation changes skipped |
| `be4f1fa6baa7642ee2a07ce624003a103f386720` | Ancestry-preservation merge; its tree equals `f5d982a`, so no separate behavior to import |
| `6deb0294bacbf2c02bd319cdcdb2dfdeaafa077d` | PR merge; its tree equals `f5d982a`, so no separate behavior to import |

### Deferred Codex changes after the 2026-10-24 review

These items remain pending even though the review cursor advances. They were not included in the three approved fixes.

| Source SHA | Deferred change and reason |
|---|---|
| `f5d982a` | Graceful shutdown, native descendant-exit verification, retained Job ownership, and updater/restart failure handling need a coordinated combined-provider/supervisor adaptation. The standalone native shutdown test `test_descendant_is_gone_before_replacement` failed in both its full suite and focused rerun; root cause remains unproven |
| `3c8934b` | Codex-only 600-second idle cadence changes polling policy; retain the current independent provider cadence until separately selected |
| `3c8934b` | `poll_fast <= poll_interval` validation must apply after the combined application/provider settings overlay, rather than validate fragments against standalone defaults |
| `3c8934b` | Display-only custom Codex CLI versions require nested Codex configuration; do not import the standalone flat setting or enable it implicitly |

### Claude commits reviewed and skipped on 2026-10-22

| Source SHA | Reason |
|---|---|
| `07d581d` | KDE Plasma tray left-click handling is Linux-specific |
| `4a2cd6e` | Linux bottom-panel anchoring does not apply to the Windows popup |
| `6336b31` | Changelog entry for the skipped Linux bottom-panel fix |
| `fd40bec` | GTK/WebKit popup caching and focus fixes; upstream explicitly keeps Windows window reuse disabled |
| `5f27127` | X11/WebKitGTK fractional scaling is Linux-specific |

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
| 2026-10-22 | Claude | `86e4723` | Manual shared port | Pointer-sized low-level hook callbacks, results, and handles; regression tests for both provider popups |
| 2026-10-22 | Claude | `e1be0c6` | Adapted documentation | Hook-fix changelog and Python-version caveat reviewed with `86e4723`; no separate runtime behavior |
| 2026-10-22 | Claude | `84270bb` | Adapted shared port | Combined-identity WinRT toasts via existing pythonnet, five-minute expiry, safe diagnostics, and provider-scoped balloon fallback |
| 2026-10-22 | Claude | `39886b1` | Adapted documentation | PowerShell verbose-log capture using the combined executable, alongside the existing rotating log |
| 2026-10-24 | Claude | `14fdd6f14ef49a4686b6c820a8fb46e2f40c10ff` ([PR #113](https://github.com/jens-duttke/usage-monitor-for-claude/pull/113)) | Manual shared port | Exact popup-field exclusions translated to shared formatting, nested provider settings, tests, and docs; default remains `['*']` for both providers |
| 2026-10-24 | Codex | `3c8934b910af73b1b74ed7bb0545b92f22f99ebf` | Manual Codex/shared port | Explicit UTF-8 CLI capture with replacement, failed-version and missing-stream rejection, and complete reset-command quota snapshots via the existing active-quota helper; fixed native update commands and provider isolation retained |
| 2026-10-24 | Codex | `f5d982a49457899716a95e07db63c79d69dc2b77` | Manual shared port | Reject malformed enum types before set membership across all settings sections; preserve legacy utilization/reset defaults alongside generic reset snapshots |
| 2026-11-13 | Claude | `302eb47ff62eb19e34675a771af56f3aede8fdc0` | Manual shared port | Opt-in work-hour pacing with provider overrides; shared elapsed-time scale for popup, tray, and alerts; current weekly guides retained when no schedule applies |
| 2026-11-13 | Claude | `dd6b81fc9af00e427c172892bf0da762e0cb4344` | Partial shared port | Fit complete startup and updated tray titles within the Windows UTF-16 limit; retain existing tooltip content and independent field selection |
| 2026-11-13 | Claude | `56bdbb43b83d377631fad0c621d45e438fbe6aac` | Manual shared port | Opt-in chart for the resolved top tray quota with per-provider and per-account memory history, popup exclusions, work-hour projection, and independent calendar ticks |
| 2026-11-13 | Claude | `22b0644757978be665aa35092c442844d0f9d8a8` | Partial Claude port | Normalize the plan label and optional tooltip in the Claude provider; preserve Codex labels and omit upstream profile logging |
| 2026-11-13 | Claude | `9961eff7c2458089f6b21623f2ce79cdf592a5f0` | Manual shared port | Distinct manual refresh gates per provider: coalesce with active operations, preserve backoff and reset alignment, and apply monotonic attempt limits; show popup wait reason |

## Verification for the 2026-11-13 import

- Native Windows full suite: 1,350 tests, 1,349 passing. The existing Store-backed Codex containment regression remains active and fails because the real interpreter and its descendant are outside the transport Job. It is unrelated to the five Claude ports.
- Focused coverage includes provider-specific work schedules, UTF-16 tooltip limits, forecast rollover and account isolation, Claude plan display, and manual refresh timing, backoff, reset deferral, and concurrent polling. Pyright reported zero errors and warnings.

## Verification for the 2026-10-24 import

- Native Windows full suite: all 1,303 tests passed, including the focused settings (187), Codex CLI (35), and upstream-port regression (15) suites.
- New regressions cover malformed enum containers/nulls and settings-section isolation; dynamic reset snapshots, compatibility defaults, inactive/malformed windows, provider isolation, and disabled commands; fixed native CLI arguments, UTF-8 capture, failed versions, missing streams, and sanitized diagnostics.
- Pyright reported zero errors and warnings; an independent read-only review found no actionable issues.
- A clean PyInstaller build from `usage_monitor.spec` produced `build/upstream-ports-smoke-20261024/dist/UsageMonitorForClaudeAndCodex.exe` for isolated verification.
- Native source and frozen smoke both verified two tray icons, independent signed-out snapshots, and provider-specific popup content. Real menu Restart recreated both trays and removed all tracked prior descendants; Quit removed all tracked remaining descendants, including Codex app-server and WebView2. The existing `dist` application kept running unchanged.
- Native smoke used isolated empty provider homes, Codex file-backed authentication configuration, and disabled automatic Codex updates. Authenticated usage and quota-reset events were not exercised in the GUI smoke; the changed behavior is covered by unit regressions.
- The three fixes were manually adapted in the combined worktree without committing or pushing. Deferred lifecycle, cadence, and optional settings changes were not imported.

## Verification for the 2026-10-22 import

- Native Windows Python 3.13: all 1,280 unit tests passed; Pyright reported zero errors and warnings.
- Clean PyInstaller build for v1.0.3 from `usage_monitor.spec` produced `dist/UsageMonitorForClaudeAndCodex.exe`.
- Native source and frozen EXE smoke used isolated empty Claude/Codex homes and disabled automatic Codex updates. Both tray icons and provider-specific signed-out popups worked; injected keyboard events traversed each popup's live low-level hook.
- The frozen EXE launched from an unrelated temporary directory. Restart removed the old Codex app-server and restored both icons; Quit removed both tray windows and all tracked descendants, including the real Codex app-server and WebView2 processes.
- Real WinRT delivery and Windows notification history confirmed both providers' startup messages under the combined AUMID with expiry set. Unit tests cover rejected registration, delivery failure, escaped XML, expiry, and provider-specific deferred routing.
- No authenticated provider usage or quota-reset notification was exercised in the frozen smoke; those paths are covered by the unit suite.
