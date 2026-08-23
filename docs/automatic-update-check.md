# Updates and Recovery

The combined executable does not silently replace itself. Provider CLI behavior is separate and must not be described as an application self-update.

## Claude authentication recovery

The Claude provider normally performs only fixed HTTPS usage/profile requests. After a 401, it may invoke the installed native Windows CLI using the fixed command:

```text
claude update
```

Claude Code owns any network access, installation change, or credential renewal performed by that command. The monitor re-reads the selected Claude `.credentials.json` and retries according to the Claude recovery guard.

This command is not a periodic general updater. It runs only as part of Claude authentication recovery. Custom display-only `cli_command` entries are never substituted into this path.

## Codex CLI updates

The Codex provider can periodically invoke the installed native CLI using the fixed command:

```text
codex update
```

This is enabled by `providers.codex.auto_update_codex_cli` and governed by `codex_update_interval`. Before invoking it, the application stops the local app-server child and serializes the update against Codex provider operations. The next Codex read launches a fresh child.

`codex update` can access the network and replace Codex installation files under the current user's permissions. Disable it when Codex is managed by an administrator or package manager:

```json
{
  "providers": {
    "codex": {
      "auto_update_codex_cli": false
    }
  }
}
```

Raw updater stdout and stderr are not logged. The app reports only sanitized outcome metadata and notifies only when the installed version actually changes and `notify_codex_update` is enabled.

## Combined executable releases

Until this combined repository establishes a release channel, users should not copy a standalone monitor's release-check script or URL and assume it applies to the combined product. Verify the repository, version metadata, checksum, and release notes for `UsageMonitorForClaudeAndCodex.exe` itself.

An optional user-configured event command may check a chosen release service, but that command is outside the built-in provider network boundary and runs with the user's privileges.
