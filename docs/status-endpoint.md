# Local status endpoint

The app can expose the current usage snapshot over a tiny local HTTP endpoint so
other programs on the same machine (for example an OpenPets plugin) can read
Claude and Codex utilization without contacting the provider APIs themselves.

The endpoint is **read-only** and binds to **loopback only** (`127.0.0.1`). It is
never reachable from other machines on the network, performs no network or disk
IO in the request path, and only ever reads the app's in-memory cache. It is
also **optional**: if the port is already in use the failure is logged and the
app keeps running normally without the endpoint.

## Request

```
GET http://127.0.0.1:45455/usage
```

`GET /` returns the same body. Any other path returns `404`. Only `GET` is
supported. No CORS headers are sent.

## Response

`HTTP 200`, `Content-Type: application/json`:

```json
{
  "schema": 1,
  "generated_at": "2026-08-25T12:34:56Z",
  "providers": {
    "claude": {
      "display_name": "Claude",
      "stale": false,
      "error": null,
      "windows": {
        "five_hour": {"utilization": 42, "resets_at": "2026-08-25T15:00:00Z"},
        "seven_day": {"utilization": 7,  "resets_at": "2026-08-30T00:00:00Z"}
      }
    },
    "codex": {"display_name": "Codex", "stale": false, "error": null, "windows": {}}
  }
}
```

### Fields

- `schema` — contract version integer (currently `1`).
- `generated_at` — ISO-8601 UTC timestamp of when the snapshot was built.
- `providers` — one entry per **enabled** provider monitor, keyed by provider id
  (`claude`, `codex`). A disabled provider is omitted. An enabled provider always
  appears even before its first successful fetch (with empty `windows`).
- `display_name` — human-readable provider name.
- `stale` — `true` when the provider's last successful fetch is older than three
  poll intervals, `false` when it is recent, and `null` when the provider has
  never succeeded (no baseline to compare against).
- `error` — the provider's last error string, or `null`.
- `windows` — dynamic map of quota windows. Keys depend on the account and API
  (for example `five_hour`, `seven_day`, `seven_day_sonnet`). Each window has an
  integer `utilization` percent (`0` when missing) and a raw `resets_at` string
  passed through from the provider data (may be an empty string). The
  differently shaped `extra_usage` entry is intentionally excluded.

## Settings

Two top-level (application-scoped) keys in `usage-monitor-settings.json` control
the endpoint:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `status_server_enabled` | bool | `true` | Serve the endpoint when the app runs |
| `status_server_port` | int (>= 1024) | `45455` | Loopback TCP port to bind |

```json
{
  "status_server_enabled": true,
  "status_server_port": 45455
}
```

Restart the app from either tray menu after editing settings.
