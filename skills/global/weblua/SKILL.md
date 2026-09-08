---
name: weblua
description: Drive and inspect browser applications with WebLua's persistent Chrome/CDP server, CLI, screenshots, console/network capture, and Lua scenarios. Use when the user requests WebLua or browser verification needs an available local automation path, including WASM/WebGPU applications.
---

# WebLua

WebLua is the user's private `SomeoneIsWorking/weblua` repository. Its Go server
owns Chrome through Rod/CDP; `weblua-ctl` drives that persistent server. Browser
automation does not require an installed MCP connector.

## Discover the actual installation

1. Check `command -v weblua` and `command -v weblua-ctl`, then the expected
   checkout at `~/repo/weblua`. Keep any resolved absolute path in session state,
   not tracked project configuration. An explicit checkout override may be used.
2. If absent, check authenticated access with
   `gh repo view SomeoneIsWorking/weblua`, then clone with
   `gh repo clone SomeoneIsWorking/weblua <chosen-checkout>`. Do not change its
   visibility or substitute an unrelated project with the same name. Report
   attempted locations and access failures instead of silently returning empty.
3. Read that checkout's `README.md`, CLI usage, and the relevant implementation
   (`ctl/main.go`, `server.go`, `lua_runner.go`, `main.go`). Installed binaries can
   lag source. `weblua -help` shows server flags; invoking `weblua-ctl` without a
   command shows its usage. Do not assume a `--help` subcommand exists.
4. Prefer working installed binaries. If a build is needed, build both into the
   checkout's `build/` directory: `go build -o build/bin/weblua .` and
   `go build -o build/bin/weblua-ctl ./ctl/`. The CLI resolves the server beside
   itself before checking PATH. Honor the repository's declared Go requirements
   and any package-install instructions. Rod can locate or download a browser;
   inspect the available runtime before declaring Chromium installation required.

## Own one isolated session

Set `WEBLUA_DIR` to the active project's fixed `scratch/weblua/` path for **every**
server and CLI invocation. This selects PID, logs, downloads, and default output
locations; it does not select a personal Chrome profile. Use an agent-owned
browser, headless unless visible presentation is requested. Never attach the
user's personal browser profile or reuse another task's server.

Choose an unused loopback port, retain it with the session, and check status and
ownership before starting or stopping. Distinct ports alone are insufficient:
concurrent sessions also need distinct owned `WEBLUA_DIR` directories. Reuse each
activity's fixed directory rather than accumulating numbered runs.

Example CLI sequence, after resolving the binaries and selecting an unused
`WEBLUA_PORT` (7979 is the server default, not a reserved task port):

```sh
export WEBLUA_DIR="$PWD/scratch/weblua"
weblua-ctl --port "$WEBLUA_PORT" start --headless --url http://localhost:3000
weblua-ctl --port "$WEBLUA_PORT" status
weblua-ctl --port "$WEBLUA_PORT" text
weblua-ctl --port "$WEBLUA_PORT" eval 'document.title'
weblua-ctl --port "$WEBLUA_PORT" click 'button[type=submit]'
weblua-ctl --port "$WEBLUA_PORT" console --errors
weblua-ctl --port "$WEBLUA_PORT" network --failed
weblua-ctl --port "$WEBLUA_PORT" screenshot "$WEBLUA_DIR/current.png"
weblua-ctl --port "$WEBLUA_PORT" stop
```

Use the resolved CLI path when it is not on PATH. If only the server is needed,
`weblua -serve -headless -port <port> -url <url>` exposes the HTTP API. Use Python
HTTP clients for project automation. Read `server.go` for current request/response
contracts: `GET /status`, `POST /navigate` with `{"url":"..."}`, `POST /eval`
with `{"expression":"..."}`, `GET /console`, and `GET /network` are the central
inspection paths. HTTP 200 alone is not success; check response error fields.

## Gather evidence at the required boundary

- Inspect the actual DOM before choosing selectors. Prefer interactive
  observation and readiness conditions to fixed input timing.
- Inspect saved screenshots with the image viewer. Console and failed-network
  reports complement pixels; neither proves a scenario reached gameplay.
- For Lua scenarios, use `weblua-ctl lua <file> --wait` and inspect errors/status.
  A wait timeout does not stop the script. Inspect the existing session before
  restarting. Keep scripts and outputs under project scratch unless they are
  maintained verification tools.
- WASM/WebGPU checks must inspect secure-context, cross-origin isolation,
  required browser features, adapter/device creation, and actual application
  counters/output. Check `main.go` and the running Chrome flags: some WebLua
  revisions set `disable-gpu` unconditionally. Do not claim GPU qualification
  from a passing DOM check or bypass a required renderer. A needed browser
  launch capability belongs in WebLua, not a copied project browser launcher.
- Finalize recordings explicitly and stop only the session you own. Preserve
  bounded failure evidence, then clean scratch at the milestone. Never kill a
  shared browser/server name or copy stale README examples using system temp
  directories or personal filesystem paths.
