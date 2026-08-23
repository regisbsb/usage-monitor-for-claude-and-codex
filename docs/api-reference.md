# Provider Reference

The combined application has two independent provider boundaries. Shared tray, popup, alert, and event code consumes normalized data and does not handle credentials or raw provider messages.

## Normalized provider contract

A provider cycle returns:

- `usage`: a dictionary of normalized quota fields, or a provider-specific error state;
- `profile`: a fresh profile dictionary, `{}` for authoritative signed-out state, or `null`/`None` when account state was unavailable and the previous profile must be preserved;
- recovery metadata used only by that provider's cache episode guard.

A quota field is a top-level dictionary with:

| Key | Meaning |
|---|---|
| `utilization` | Percentage consumed, not percentage remaining |
| `resets_at` | Aware ISO-8601 reset timestamp, or an empty string when unavailable |
| `limit_name` | Optional provider-supplied friendly display name |

Field names are dynamic. Display code must parse duration-derived names rather than enumerate provider schemas. Null/inactive windows are skipped. A duration-less field remains displayable but has no calculated period, elapsed-time marker, or dividers.

## Claude provider

### Credential selection

Claude reads `.credentials.json` from the configuration directory selected by:

1. `--claude-config-dir`;
2. `CLAUDE_CONFIG_DIR`;
3. the default `~/.claude`.

The OAuth access token is read only by the Claude provider and is sent only in the HTTP `Authorization` header. It must not cross into shared code, Codex code, logs, popups, or event-command variables.

### Fixed endpoints

Claude provider requests are fixed HTTPS GETs under `https://api.anthropic.com`:

| Endpoint | Purpose |
|---|---|
| `/api/oauth/usage` | Usage windows, scoped limits, and supported extra-usage information |
| `/api/oauth/profile` | Account and organization/profile information |

Provider URLs remain top-level literals. Redirects or runtime-constructed provider hosts are not part of the contract.

### Authentication recovery

On a 401, the Claude cache compares the token used for the failed request with the currently selected credentials. If a new token is already present, it can retry with that token. Otherwise recovery may invoke the fixed native `claude update` command, re-read the same `.credentials.json`, and retry once according to the continuous-failure episode guard.

Custom `cli_command` entries are display-only and never choose the authentication source or recovery CLI.

### Claude-specific normalization

Top-level usage windows and model-scoped entries are normalized into the common quota shape. Scoped limits receive stable synthetic field names based on their duration group and model scope. Existing top-level fields are never overwritten.

Claude extra-usage amounts are normalized only when the API explicitly reports the active billing state. That structure is separate from quota entries.

## Codex provider

### Local transport

The monitor launches a local `codex app-server` child and speaks newline-delimited JSON over standard input/output. Messages follow JSON-RPC 2.0 semantics but omit the `jsonrpc` member on the wire.

The monitor does not read a Codex credential store and does not make Codex provider HTTP requests. The external child owns its authentication and network behavior.

### Fixed methods

| Method | Purpose |
|---|---|
| `initialize` / `initialized` | Required app-server handshake |
| `account/read` | Read authentication mode, account email, and plan |
| `account/rateLimits/read` | Read rate-limit windows |
| `account/updated` | Notification used only as an early account re-check hint |

Normal account reads send `refreshToken: false`. A recovery-enabled account read may send `refreshToken: true` at most once per continuous failure episode when exact authentication evidence permits recovery.

Unexpected server notifications are ignored. An unexpected server request with an `id` receives a fixed method-not-found response so neither side waits indefinitely.

### Generation atomicity

Account and rate-limit reads form one logical provider operation:

1. The operation lock is acquired.
2. The child TTL is evaluated before the operation starts.
3. Every RPC is pinned to one child generation.
4. If that child dies, all partial results are discarded and the whole operation is retried once with a new generation.
5. A second transport failure ends the provider cycle as a transient error.

This prevents an account response from one child/account from being paired with usage returned by another generation. TTL expiry never interrupts an operation in progress.

The child belongs to a kill-on-close Windows Job object so process replacement, crash, restart, and normal quit do not leave an authenticated app-server orphan.

### Rate-limit source selection

Codex can return a compatibility snapshot in `rateLimits` and keyed buckets in `rateLimitsByLimitId`.

- A non-empty keyed map is used alone, in sorted limit-ID order.
- Otherwise the snapshot's `primary` then `secondary` windows are used.
- The two sources are never merged.
- `usedPercent` maps directly to `utilization`.
- `resetsAt` Unix seconds become aware UTC ISO-8601 text; missing or invalid reset values become `''`.
- Credits metadata is dropped.

Duration-based names preserve common fields such as `five_hour` and `seven_day`, support unusual minute/hour/day durations, add sanitized keyed-limit suffixes, and use deterministic collision counters. A missing-duration keyed window uses its limit slug; a missing-duration snapshot window uses its slot fallback.

### Account and error states

ChatGPT authentication supplies the plan usage displayed by Codex. Signed-out, API-key, Amazon Bedrock, method-not-found, malformed, and transient states are classified separately.

Unknown RPC error codes are transient. Authentication classification requires exact code/data evidence in the Codex wire notes; message substring guessing is prohibited. Method-not-found on a required account method means the installed Codex CLI is too old for this monitor.

### Codex CLI update

When enabled, the Codex provider invokes only the installed CLI's fixed `codex update` command. It stops the app-server and serializes the updater against logical provider operations first. Raw updater output is not logged. A notification is shown only when the installed version actually changes.

## Shared isolation rules

- Claude errors, cooldowns, refresh state, and account fingerprints affect only Claude.
- Codex child generations, TTL, errors, and account revisions affect only Codex.
- Shared UI code receives provider-labelled normalized snapshots.
- Every event command receives `USAGE_MONITOR_PROVIDER`.
- One provider may continue updating while the other is signed out, missing, updating, or failing.
