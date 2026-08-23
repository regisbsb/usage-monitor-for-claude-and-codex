# Codex app-server wire notes

Probe date: 2026-07-16
Codex CLI: `codex-cli 0.140.0` on native Windows
Probe: `tests/integration/probe_live_app_server.py`

## Pinned request wire

- Transport framing is one JSON object per line over stdio.
- Messages omit the `"jsonrpc": "2.0"` member.
- Handshake used `initialize`, awaited its response, then sent `initialized` with `params: {}` before account requests.
- The probe did not test omitting `initialized`; the monitor must use the documented handshake.
- Account read method: `account/read`.
- Account rate-limits method: `account/rateLimits/read`.
- Proactive refresh parameter: `refreshToken` (camelCase boolean). The live probe verified `false` is accepted.
- Documented account notification method: `account/updated`. No `account/updated` notification occurred during this read-only probe.

## Observed response shapes

The signed-in account response contained:

```json
{
  "account": {
    "type": "chatgpt",
    "email": "<redacted>",
    "planType": "<redacted>"
  },
  "requiresOpenaiAuth": true
}
```

The rate-limits response contained both `rateLimits` and a non-empty `rateLimitsByLimitId`. Each keyed value was a full snapshot with `limitId`, `limitName`, `primary`, `secondary`, `credits`, `individualLimit`, `planType`, and `rateLimitReachedType`. Window fields used `usedPercent`, `windowDurationMins`, and `resetsAt`. Account-specific durations, utilization, reset times, identifiers, plan information, and window topology were not retained.

`credits` was nested inside the snapshot and used this shape:

```json
{
  "hasCredits": "<redacted boolean>",
  "unlimited": "<redacted boolean>",
  "balance": "<redacted nullable string>"
}
```

The probe also observed the unrelated notification `remoteControl/status/changed`. No server-initiated request occurred.

## Account discriminators and required fields

- Live ChatGPT discriminator: `chatgpt`.
- Protocol-schema API-key discriminator: `apiKey`.
- Protocol-schema Bedrock discriminator: `amazonBedrock`.
- `requiresOpenaiAuth` is required on every account-read response fixture, including signed-out and non-ChatGPT cases.

## Error evidence

No auth-shaped JSON-RPC error was observed. Do not infer an auth error from message text and do not treat `-32001` as authentication evidence; Codex also uses that code for server overload. `AUTH_ERROR_CODES` must therefore ship empty until a future live probe provides exact code/data evidence.

`10_auth_error.json` is a synthetic test stand-in only. Tests may patch its code into the auth predicate to exercise recovery behavior, but it is not pinned wire evidence. `10b_transient_error.json` and `11_method_not_found.json` are also deterministic error-path fixtures rather than responses captured in this signed-in probe.

## Fixture provenance

The usage fixtures preserve verified field casing and nesting while using deterministic synthetic account details, percentages, durations, timestamps, balances, identifiers, and topologies. They are not copies of the live account response. `04_multi_bucket.json` reflects the structural proof that `rateLimitsByLimitId` values are nested snapshots rather than flat windows.

## External-login experiment

Not performed. The probe did not automate or trigger logout/login, did not change credential configuration, and did not access any credential store. Runtime child TTL and failed-state recycling remain responsible for bounded observation of external authentication changes until this optional manual experiment is performed by the user.


