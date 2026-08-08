# Codex setup on Windows

This guide runs the local checkout as a Codex STDIO MCP server and installs its Python bridge into a Cinema 4D 2025 preference directory.

> [!IMPORTANT]
> This fork targets Cinema 4D 2025.3.2, but the target is **not live-verified** until `npm run test:live:2025` exits successfully without skips. Do not infer compatibility from a successful build, ordinary `npm test`, plugin installation, or the presence of a tool in `docs/TOOLS.md`.

The Codex forms below follow the [official OpenAI MCP configuration](https://developers.openai.com/codex/mcp): a local STDIO command configured in Settings, through `codex mcp add`, or in `config.toml`.

## Prerequisites

- Windows with Cinema 4D 2025.3.2 installed.
- Node.js 24 or newer; locate the executable with `(Get-Command node.exe).Source`.
- An absolute local checkout path, for example `D:\ABSOLUTE\PATH\TO\mcp_c4d`.
- A saved backup of any scene that matters. The bridge can mutate documents even when arbitrary Python is disabled.

Build the STDIO server from the checkout:

```powershell
Set-Location "D:\ABSOLUTE\PATH\TO\mcp_c4d"
npm ci
npm run build
```

The Codex command must point to the resulting absolute `dist\index.js` path, not to `src\index.ts`.

## Configure the shared token

Generate a token outside the repository and set it in the current PowerShell process and the current user's environment. This default form is compatible with Windows PowerShell 5.1; it does not print the generated value:

```powershell
$c4dMcpRng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
  $c4dMcpBytes = New-Object byte[] 32
  $c4dMcpRng.GetBytes($c4dMcpBytes)
  $c4dMcpToken = -join ($c4dMcpBytes | ForEach-Object { $_.ToString('x2') })
} finally {
  $c4dMcpRng.Dispose()
}
$env:C4D_MCP_TOKEN = $c4dMcpToken
[Environment]::SetEnvironmentVariable("C4D_MCP_TOKEN", $c4dMcpToken, "User")
```

Cinema 4D reads the variable only when its process starts. Start Cinema 4D after setting it. Codex must pass the same `C4D_MCP_TOKEN` to the Node process. Never put the real value in this repository, a checked-in `.env` file, screenshots, or bug reports.

## Install the bridge

Do not install while Cinema 4D is running. First print the plan without changing files:

```powershell
Set-Location "D:\ABSOLUTE\PATH\TO\mcp_c4d"
npm run install:c4d -- --dry-run
```

The installer discovers a single direct child matching `%APPDATA%\Maxon\Maxon Cinema 4D 2025_*`. If more than one exists, select the intended preference explicitly. Review the exact source and destination, then run one of these explicit forms:

```powershell
npm run install:c4d -- --install
```

```powershell
npm run install:c4d -- --install --preference "C:\Users\<WINDOWS_USER>\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_<INSTALL_ID>"
```

The destination is `<PREFERENCE>\plugins\cinema4d_mcp_bridge`. If that directory already exists, the installer first moves it to the same `plugins` directory as `cinema4d_mcp_bridge.backup-<UTC_TIMESTAMP>`, then copies only `plugin\cinema4d_mcp_bridge` from this checkout.

After installation, start Cinema 4D 2025.3.2 and confirm its console reports:

```text
[cinema4d_mcp_bridge] listening on 127.0.0.1:18710
```

## Configure Codex STDIO

Use one of the supported forms below. Replace every `ABSOLUTE`/angle-bracket placeholder locally. The command and both path arguments must resolve to absolute Windows paths.

### Settings UI

1. Open **Settings → MCP servers → Add server**.
2. Name the server `cinema4d` and select **STDIO**.
3. Set command to `C:\Program Files\nodejs\node.exe`, or the absolute value returned by `(Get-Command node.exe).Source`.
4. Add argument `D:\ABSOLUTE\PATH\TO\mcp_c4d\dist\index.js`.
5. Add environment variable `C4D_MCP_TOKEN` with the same locally generated value used by Cinema 4D. Do not place that value in Git.
6. Save, restart the Codex host when prompted, and use `/mcp` to inspect the connection.

### CLI

Run this only after `$env:C4D_MCP_TOKEN` is set in the current PowerShell session:

```powershell
codex mcp add cinema4d `
  --env "C4D_MCP_TOKEN=$env:C4D_MCP_TOKEN" `
  -- "C:\Program Files\nodejs\node.exe" `
  "D:\ABSOLUTE\PATH\TO\mcp_c4d\dist\index.js"
codex mcp list
```

The shell expands the environment variable into Codex's local configuration. Keep that local configuration out of Git. Use `codex mcp --help` to inspect the installed CLI's supported MCP commands.

### `config.toml` with environment forwarding

Codex supports user-level `~/.codex/config.toml` and trusted-project `.codex/config.toml`. The `env_vars` entry forwards the existing local environment variable without writing its value into the file:

```toml
[mcp_servers.cinema4d]
command = 'C:\Program Files\nodejs\node.exe'
args = ['D:\ABSOLUTE\PATH\TO\mcp_c4d\dist\index.js']
cwd = 'D:\ABSOLUTE\PATH\TO\mcp_c4d'
env_vars = ["C4D_MCP_TOKEN"]
```

If `node.exe` is installed elsewhere, use its actual drive-letter absolute path.

## Safe defaults

Keep the first verification run in the default restricted posture:

- `C4D_MCP_HOST` defaults to loopback `127.0.0.1`; non-loopback binding is refused unless `C4D_MCP_ALLOW_REMOTE=1` is explicitly set on the bridge side.
- `C4D_MCP_ENABLE_EXEC_PYTHON` is unset on both sides, so `exec_python` is hidden by the MCP server and rejected by the bridge.
- `C4D_MCP_ENABLE_PYTHON_OPS` is unset on the Cinema 4D side, so creating or editing Python-bearing plugin types is rejected.
- Keep Codex approval prompts enabled for mutating tools. The bridge is not a scene sandbox.
- The strict foundation test creates a uniquely named, non-active temporary document, scopes edits to it, uses `save_document` with `copy: true`, and closes it during cleanup. It still requires a saved backup of user work before live testing.

Use `get_capabilities` to inspect the reported runtime and security posture after connecting. A response alone does not establish the full foundation path.

## Live verification

Only the following command is the strict Cinema 4D 2025 foundation gate:

```powershell
Set-Location "D:\ABSOLUTE\PATH\TO\mcp_c4d"
npm run test:live:2025
```

It sets `C4D_MCP_REQUIRE_LIVE=1`, so an unreachable bridge or a non-2025 runtime fails instead of silently skipping. A successful, no-skip run exercises ping, capabilities, temporary-document creation, create/edit/read, undo, preview rendering, save-copy, state preservation, and cleanup.

Ordinary `npm test` is developer-friendly and may skip bridge-dependent E2E suites when the bridge is unavailable. It is not evidence of 2025 compatibility. Record the exact Cinema 4D build, command, exit code, skipped-test count, and foundation assertions when promoting a row in [Compatibility](./COMPATIBILITY.md) to live-verified.

## Backup and rollback

The installer backup is a sibling of the installed plugin, for example:

```text
C:\Users\<WINDOWS_USER>\AppData\Roaming\Maxon\Maxon Cinema 4D 2025_<INSTALL_ID>\plugins\cinema4d_mcp_bridge.backup-2026-08-08T01-02-03.456Z
```

To roll back, close Cinema 4D, verify the exact preference path, move the current `cinema4d_mcp_bridge` directory aside, and rename the selected `.backup-*` directory back to `cinema4d_mcp_bridge`. Keeping the current copy aside makes the rollback reversible. Start Cinema 4D only after the old directory name has been restored.

For a first installation with no `.backup-*` directory, roll back by moving `cinema4d_mcp_bridge` out of the preference's `plugins` directory. Do not delete a backup until the restored bridge has been tested.
