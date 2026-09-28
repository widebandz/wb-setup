# Local Knowledge Graph pilot

The operator's **Knowledge Graph** tile runs Glitch Cat, a separate Node
service on port 4180. The Setup pilot bundles a reviewed copy of that
engine and installs it behind the real customer Fleetdeck board. The earlier
fixed `/graph` first-text diagram was a placeholder and is not the pilot's
Knowledge Graph tile. The client graph indexes only that Mac's own files.

## Build and transfer a reviewed engine bundle

On the operator Mac, with access to the private Glitch Cat source:

```sh
python3 packaging/glitch-cat-pilot.py bundle \
  ~/glitch-cat dist/glitch-cat-pilot-bundle
python3 packaging/glitch-cat-pilot.py verify dist/glitch-cat-pilot-bundle
```

`dist/` is ignored by Git. The bundle contains Git-tracked generic engine
modules, six graph/health icons, and the npm package/lock files. It excludes
the host pack, register, database, notes, logs, tests, and Git directory. Its
manifest hashes every copied file and known host identifiers are removed.
The Glitch Cat checkout has no public license file. Its rights holder expressly
authorized distributing this reviewed source **inside the Wideband Setup
installer** for the public 0.7.0 pilot on September 28, 2026. This permission
does not publish the standalone Glitch Cat repository or grant a general open
source license. Continue excluding the host pack, local data, secrets, and
untracked files from the bundle.

`packaging/build-app.sh --graph-source` includes the verified bundle in the
pilot DMG. `install.sh --phone-only` stages it under
`~/srv/glitch-cat-pilot`, builds the VM-local index, registers the graph tile,
and installs the engine and owner-gated proxy LaunchAgents. Tailscale Serve
`:8792` points to the loopback proxy on `:4181`, while the engine remains on
loopback `:4180`. The private graph entry `/p/<owner capability>/graph` sets
the same owner session cookie as Fleetdeck; direct graph/API access is denied
without it.
For an isolated manual check on a pilot Mac, the helper also supports:

```sh
python3 ~/srv/wb-setup/packaging/glitch-cat-pilot.py stage \
  /path/to/glitch-cat-pilot-bundle ~/srv/glitch-cat-pilot
python3 ~/srv/wb-setup/packaging/glitch-cat-pilot.py preflight \
  ~/srv/glitch-cat-pilot
python3 ~/srv/wb-setup/packaging/glitch-cat-pilot.py build \
  ~/srv/glitch-cat-pilot
python3 ~/srv/wb-setup/packaging/glitch-cat-pilot.py serve \
  ~/srv/glitch-cat-pilot
```

`stage` refuses an existing target. The generated pack declares exactly two
walked local roots: `~/srv/wb-setup` (created by the native app launcher) and
`~/wideband/first-project` (created by each first-job recipe). It declares
zones and scopes the measured launchd plane to Wideband jobs. The graph
database remains under the client-local pilot tree at `.data/kg.db` with mode 0600.
`build` preserves a prior index if the next build fails. `serve` stays in the
foreground and binds `127.0.0.1:4180`; stop it with Ctrl-C. The helper alone
does not install LaunchAgents or Tailscale routes; the phone-stack integration
does that after the owner reply and first job are verified.

The phone-stack integration checks `/api/stats`, `/api/graph?lens=plane`, the
connected Surface lens, and the proxy's owner gate, then rebuilds the index
after the real services and Serve mappings exist. The customer board points to
the verified HTTPS graph origin. On a phone, the graph canvas opens full width
and the lenses appear in a menu. Do not reuse the host's graph database or
pack.

The current engine's rich code relationships cover JavaScript, TypeScript,
Next.js routes, and SQL. The pilot Setup source is mostly Python and shell,
while the generated first website is a small static page. This pack yields a
real, cited file inventory and an observed operator plane, with fewer code
relationships than the operator's multi-repository graph. Its runtime facts
reflect the **last build time**; Glitch Cat is not a live tmux viewer. Rebuild
after meaningful project changes, and show the index timestamp in the UI.

To roll back the integration, remove only the graph tile and its private Serve
mapping, unload the dedicated graph LaunchAgent, and keep
`~/srv/glitch-cat-pilot` for the owner's review. The helper never removes it.
