# Troubleshooting

## How to use this

```bash
bash doctor.sh          # what the machine actually is
bash verify.sh          # what is wrong, each failure tagged [P0-FDA] etc.
```

Every `✗` from `verify.sh` carries an ID. Find that ID in **Part 2** below.
Each entry names the symptom, the class it belongs to, a command that
confirms the diagnosis, the fix, and — the half usually missing — how to
prove it is actually fixed.

If nothing errored but something is wrong anyway, go to **Part 3**. If the
machine worked for weeks and then stopped, go to **Part 4**.

**Read Part 1 once.** Six classes cover nearly every failure in this build,
including the ones nobody has written down yet. A symptom table can only
help with failures someone already hit; knowing the class lets you diagnose
a new one.

---

# Part 0 — Wideband Setup app and private guide

Use this section when the installer itself will not open or the embedded guide
disconnects. Once the guide is healthy, use the check ID from its readiness
screen and continue in Part 2.

## The unsigned pilot is blocked by Gatekeeper

**Symptom:** macOS says Wideband Setup was not opened or cannot verify the
developer.

The pilot DMG is ad-hoc signed but not notarized. This is expected only when the
filename contains `unsigned`.

1. Select **Done**, not Move to Trash.
2. Open **Open Privacy & Security** from the DMG.
3. In System Settings, scroll to Security and select **Open Anyway** beside
   Wideband Setup.
4. Confirm **Open Anyway** and enter the Mac administrator password into the
   macOS prompt.

**Proof:** Wideband Setup reaches its branded welcome window. A production DMG
must be Developer ID signed, notarized, and stapled; it should not require this
exception.

## The app stays on “Preparing your private setup guide”

Wait up to a minute on a new Mac. The bundled engine can open before Homebrew,
Python, or Command Line Tools exists, but the app still has to copy its private
payload and start the loopback service.

If it remains there, quit the app and open the installed copy:

```bash
open "$HOME/Applications/Wideband Setup.app"
```

An operator may inspect the local log on the Mac:

```bash
tail -n 80 ~/.wideband/setup/engine.log
```

Do not paste the raw log into a support channel. Use **Setup tools → Export
support bundle** when the UI is available; that export is deliberately
redacted.

**Proof:** the header says **Connected on this Mac** and the next saved action
appears.

## The page says “Reconnect needed”

Progress is already saved. Do not refresh an old localhost tab or type a port
manually. Reopen:

```bash
open "$HOME/Applications/Wideband Setup.app"
```

The native shell reads the current private connection, supplies the current
token, and resumes the saved step. An old browser tab cannot safely invent a
replacement token.

**Proof:** the reconnect banner disappears and Live Readiness updates again.

## The guide is not using port 8803

This is normal when another local process already owns 8803. Wideband Setup
selects a free loopback port and records the real one. Inspect only the
non-secret fields:

```bash
plutil -extract port raw -o - ~/.wideband/setup/connection.json
plutil -extract build_id raw -o - ~/.wideband/setup/connection.json
```

Never print or share the `token` field. Do not kill an unknown process merely
to reclaim 8803.

**Proof:** the app reports the selected port and remains connected. Reopening
after 8803 becomes free may return to the preferred port.

## The app asks whether it may check for updates

This is a one-time consent prompt from the native Wideband Setup app. No update
request is made before the client chooses. If enabled, startup checks contact
only:

```text
https://os.wideband.ai/version
```

The request contains the installed app version as a normal user-agent but no
setup answers, client profile, local token, or machine identifier. Change the
preference from **Wideband Setup → Check for Updates When Starting**. A manual
**Check for Updates…** remains available whether or not startup checks are
enabled.

**Proof:** the menu item shows a checkmark only when startup checks are enabled.

## “Couldn’t check for updates” appears

The installer and saved setup continue normally; an update check never blocks
the local guide. Confirm the Mac can resolve and reach the public endpoint:

```bash
curl -fsS https://os.wideband.ai/version
```

The response must be schema-1 JSON for `wideband-setup`. The app refuses an
oversized response, a response redirected away from the Wideband hostname, an
unknown product/trust state, a malformed checksum, or release links outside
`github.com/widebandz/wb-setup/releases`. Do not work around that refusal with
an alternate download link. Use **View Version History…** or contact Wideband.

**Proof:** a manual check reports either the newest published version or that
the installed release is current.

## An update is available

Select **View & Download** to open the public GitHub Release. Review the release
notes, exact DMG name, SHA-256, and whether the build is unsigned or notarized.
Wideband Setup does not silently download, mount, install, or execute the new
app. Opening the newer DMG replaces the managed installer payload while keeping
the client's saved setup state and curated identity.

Unsigned pilots still require the Privacy & Security → Open Anyway handoff.
Once production builds are Developer ID signed and notarized, the update notice
must say so and the release must use `Wideband-Setup.dmg` rather than an
`unsigned` filename.

**Proof:** after opening the new release, **About Wideband Setup** and a manual
update check report the same version shown on the public release page.

## Terminal appeared behind the app

The client package carries its own verified tools and does not need Homebrew.
Terminal may host the first bootstrap or recovery while the native guide is
open. Leave that window open until the guide says the local core is ready.
Enter a Mac password only into an explicit macOS prompt.

On an established machine, reopening Wideband Setup should run quietly. If the
readiness screen already says the foundation is installed but every launch
opens Terminal, export a support bundle for the operator.

## Homebrew is not writable or says Git is unavailable after an OS upgrade

**Symptom:** the log reports that `/opt/homebrew` is not writable and may
suggest a recursive `chown`; later Homebrew downloads API data but fails with
“Git is unavailable.”

**Class:** identity plus bare-machine assumptions. A major macOS upgrade can
leave the Homebrew prefix on disk while removing or deselecting Apple Command
Line Tools. The old prefix may also belong to a different setup user. These are
two independent failures; the existence of `brew` proves neither is healthy.
The packaged 0.8.0 client installer should use its private tools and leave a
foreign prefix untouched. If it instead blocks, export a support bundle.

Run the read-only guard from the downloaded repository:

```bash
bash ~/srv/wb-setup/bootstrap.sh --diagnose-homebrew
```

It reports the invoking user and UID, home owner, GUI console user,
architecture, PATH, selected developer directory, runnable Git version, Apple
Command Line Tools receipt, exact prefix owner and mode, and the number of
objects owned by another UID when the current user owns the prefix. It does
not use `sudo` or change the machine.

Do not copy a generic `sudo chown -R <name> /opt/homebrew` from an error. The
bootstrap prints a repair only when all of these are true:

- the machine is arm64 and the target is exactly `/opt/homebrew`;
- the target is a real directory, not a symlink, and contains Homebrew markers;
- the invoking user owns their unsymlinked home and is an administrator; and
- the GUI console user is the same intended user; and
- the standard Homebrew directories have no extended ACL or file-flag state
  that a scoped ownership/mode repair cannot safely explain.

For a recognized prefix already owned throughout by the current user, the
legacy source bootstrap may print a directory-mode repair that the owner must
review. It never prints or runs a command to transfer another user's prefix.
The packaged client installer needs no Homebrew repair.

If the report shows ACL entries, file flags, or effective non-writability that
is not explained by ownership or owner-write bits, no repair command is
printed. That state requires operator review; a generic `chown` or `chmod`
would be guesswork and may not fix the actual restriction.

If the report says `developer Git installed_not_selected`, the files already
exist and the client may personally run the exact selection shown by the
installer:

```bash
sudo /usr/bin/xcode-select --switch /Library/Developer/CommandLineTools
```

If it says `developer Git missing`, approve Apple's Command Line Tools dialog.
That package is not the full Xcode application. The message saying an install
was requested is not proof the download started; select **Install** and leave
Terminal open while Wideband waits for the Git executable to appear.

If it says `developer Git incompatible`, the files remain but the selected Git
cannot run. This is a known post-upgrade class: Apple advises checking Software
Update for a Command Line Tools release compatible with the new macOS. Open
**System Settings → General → Software Update**, install that update, and reopen
Wideband Setup. Wideband does not delete the existing Apple toolchain or run a
destructive reinstall command automatically.

**Proof:** a second diagnostic reports `developer Git ready` with a Git version,
`prefix state healthy`, the intended user and console user agree, and reopening
Wideband Setup advances the Core tools row without another ownership error.

## A permission was approved but remains red

Confirm the selected row names **Wideband Agent**, not Terminal, Python, or
Wideband Setup. Close any old copy of Wideband Agent if macOS asks, then return
to the guide. The focused check refreshes automatically while the permission
step is open.

If the grant remains red after two refresh cycles, use **Setup tools → Check
this Mac** and follow the matching `P0-*` section in Part 2.

## Repair completed but setup is not “done”

That is a valid state. **Repair Wideband** reconciles deterministic software;
it cannot approve macOS privacy prompts, sign into accounts, answer the
operator interview, or prove a message arrived on the client's phone.

Read the ownership label on the next action:

- **Machine verified** means the app observed the object or permission.
- **You confirmed** means the client owns the account or real-world outcome.
- **We customize together** means the result requires a Wideband handoff.

---

# Part 1 — the six classes

## 1. Grant-path

macOS attributes a TCC permission to a binary's **resolved real path**, not
to its name and not to the symlink you invoked. Three consequences that
account for most "I granted it and it still doesn't work":

- **A symlink holds a different grant than its target.** Granting Full Disk
  Access to `/opt/homebrew/bin/foo` when that is a symlink grants it to
  whatever the link resolves to at that moment.
- **`brew upgrade` moves the real path.** A formula upgrade changes
  `…/Cellar/python/3.13/…` to `…/3.14/…`, and every grant attached to the
  old path is now attached to a binary that no longer exists. This has
  already happened once on the reference machine and silently voided a
  project's grants.
- **A grant never applies to an already-running process.** Granting Full
  Disk Access to Terminal does nothing for the Terminal you granted it
  from. Quit it completely and reopen.

`doctor.sh` prints resolved real paths for exactly this reason. When a grant
looks given but behaves as if it is not, compare what you granted against
what the tools section reports.

## 2. Environment divergence

It works when you type it and fails when launchd runs it. launchd gives a
job almost nothing: no `~/bin`, no `/opt/homebrew/bin`, often no `HOME`.

Every plist in `templates/launchagents/` therefore sets `PATH` and `HOME`
explicitly. A loop that runs by hand and fails on schedule is this class
until proven otherwise — check the plist's `EnvironmentVariables` before
anything else.

The reverse also bites: a script that hardcodes `/Users/yourname` works on one
machine and nowhere else. `selftest.sh` asserts no loop contains an identity
literal.

## 3. Identity

The build assumes exactly one of each identity. Two accounts is the failure.

- A second GitHub account blocks deploys, and it is painful to unwind after
  commits exist under both.
- `git config user.name` and `gh auth` are **separate** and can disagree —
  `doctor.sh` prints both because they routinely do.
- A hardcoded phone number or hostname makes a script unportable. Identity
  belongs in `~/.sop-vars` and nowhere else.

## 4. Reachability

Four distinct things all present as "I can't reach it":

- **Bound to loopback.** A dev server on `127.0.0.1` is invisible to the
  tailnet proxy. Bind `-H 0.0.0.0`.
- **HTTP on a tailnet port.** Safari's HTTPS-First fails the handshake
  before anything answers. `tailscale serve --https`.
- **HTTPS certificates not enabled** for the tailnet in the admin console.
  `serve` then has no certificate to issue and every surface fails at TLS.
- **The check itself is wrong.** `sshd` is socket-activated and its socket
  belongs to root, so an unprivileged `lsof -iTCP:22` shows nothing even
  when Remote Login is on. Read `launchctl print-disabled system` instead.

## 5. Ledger-vs-object

The record says it happened. The thing is not there. Always verify the
object, never the record:

- `supabase db push` re-runs the whole migration ledger. The ledger will say
  a migration ran; check that the **table or column exists**.
- A LaunchAgent can be *loaded* and *failing*. `launchctl list` shows it;
  the second column is the last exit code, and non-zero means a broken loop
  that looks installed.
- A stale `.vercel/project.json` points at a real project with no env vars
  and no domain. The link exists; it is the wrong link.
- **"Installed" is not "has fired once."** A scheduled job is not working
  until it has actually run and produced output.

## 6. Bare-machine assumptions

Things true on a built machine and false on a fresh one:

- `/usr/bin/git` and `/usr/bin/python3` are **Command Line Tools stubs**.
  Invoking either on a bare Mac pops the CLT installer dialog and blocks.
  This is why `bootstrap.sh` fetches a tarball rather than cloning.
- `/bin/bash` is **3.2**. No associative arrays, no `mapfile`.
- A script downloaded in a browser is **quarantined** by Gatekeeper. Piping
  `curl` to `bash` is not, which is why the installer is a URL and not a
  download.
- The Mac App Store Tailscale **ships no CLI**. Only the standalone app does.

---

# Part 2 — failures by check ID

## P0-FDA — Full Disk Access

**Class:** grant-path. Protected local-data workflows silently return nothing.

```bash
bash ~/srv/wb-setup/verify.sh --quick
```

The verifier launches the app through LaunchServices so TCC evaluates the
Wideband Agent identity rather than the invoking terminal. The Full Disk check
reads one byte and does not print, retain, or transmit its contents.

**Fix:** Settings → Privacy & Security → Full Disk Access → add and enable
`~/Applications/Wideband Agent.app`. Use the installer's **Show Wideband
Agent** button to reveal the exact bundle.

**Proof:** the verifier reports `Wideband Agent has Full Disk Access`.

## P0-AX — Accessibility is not granted

**Class:** grant-path. Visible-control automation cannot operate the Mac.

```bash
bash ~/srv/wb-setup/verify.sh --quick
```

**Fix:** use **Request Accessibility** in Wideband Setup, choose Open System
Settings, then enable **Wideband Agent** under Privacy & Security →
Accessibility.

**Proof:** the verifier reports that Wideband Agent has Accessibility. A check against Terminal or Python
does not prove that the agent itself was approved.

## P0-SCREEN — Screen Recording is not granted

**Class:** grant-path. Desktop-level visual verification can return blank or
incomplete images.

```bash
bash ~/srv/wb-setup/verify.sh --quick
```

**Fix:** use **Request Screen Access** in Wideband Setup, then allow
**Wideband Agent** under Privacy & Security → Screen & System Audio Recording.

**Proof:** the verifier reports that Wideband Agent has Screen Recording.

## P0-AUTOMATION — Messages automation is not granted

**Class:** grant-path. Approved Messages actions cannot run.

```bash
bash ~/srv/wb-setup/verify.sh --quick
```

**Fix:** use **Show macOS prompt** in Wideband Setup and allow Wideband Agent
to control Messages. The request reads only the Messages application name and
does not send or read a conversation.

**Proof:** the verifier reports that Wideband Agent may automate Messages
without presenting another prompt.

## P0-SSH — Remote Login is off

**Class:** reachability.

```bash
launchctl print-disabled system | grep sshd
```

**Fix:** Settings → General → Sharing → Remote Login → on.

**Proof:** the command prints `"com.openssh.sshd" => enabled`. Do not check
`lsof -iTCP:22` — see class 4; it shows an unprivileged user nothing either
way.

## P0-SCREENSHARING — Screen Sharing is off

**Class:** reachability. The operator cannot provide visual support.

```bash
launchctl print-disabled system | grep com.apple.screensharing
```

**Fix:** Settings → General → Sharing → Screen Sharing → on. Restrict access
to the intended administrator account. Leave legacy VNC password access off
unless it is explicitly required.

**Proof:** the command prints `"com.apple.screensharing" => enabled`.

## P0-SLEEP — the machine sleeps

**Class:** ledger-vs-object. Scheduled loops miss their window and there is
no error anywhere, because a job that never ran cannot fail.

```bash
sudo pmset -a sleep 0 disksleep 0
```

**Proof:** `pmset -g | grep '^ *sleep'` reports `0`. Re-check after any
macOS update — see Part 4.

## P3-CLI — a core tool is missing

**Class:** bare-machine.

```bash
brew bundle --file=Brewfile
```

**Proof:** `bash verify.sh` no longer reports it. If `brew` itself is
missing, the Homebrew step of `bootstrap.sh` failed — read
`/tmp/wb-bootstrap-brew.log`.

## P3-GHAUTH — gh is not authenticated

**Class:** identity.

```bash
gh auth login          # HTTPS · browser
```

**Proof:** `gh api user -q .login` prints the expected username.

## P3-GHUSER — gh is the wrong account

**Class:** identity. **Stop and fix this now.** It blocks deploys, and
unwinding it after commits exist under both accounts is far worse than
fixing it here.

```bash
gh auth logout && gh auth login
git config --global user.name  "$GH_USER"
git config --global user.email "$GIT_EMAIL"
```

`gh` and `git config` are separate identities and can disagree. Set both.

**Proof:** `gh api user -q .login` and `git config --global user.name` agree
with `$GH_USER` in `~/.sop-vars`.

## P4-TSCLI — no Tailscale CLI

**Class:** bare-machine. Almost always the App Store build, which ships no
CLI.

Install the standalone app from tailscale.com/download, then link it:

```bash
printf '#!/bin/sh\nexec "/Applications/Tailscale.app/Contents/MacOS/Tailscale" "$@"\n' \
  | sudo tee /opt/homebrew/bin/tailscale >/dev/null
sudo chmod +x /opt/homebrew/bin/tailscale
```

A **wrapper**, not `ln -s`. The app binary derives its bundle identifier
from `argv[0]`, so a symlink to it crashes; `exec` on the real path does not.

**Proof:** `tailscale status` answers.

## Tailscale is stopped after a Mac restart

**Class:** persistence. A successful sign-in or `tailscale up` proves only that
the current session is connected. The standalone macOS app has a native login
helper, but it must be enabled in the Tailscale app's **Start on Login** setting.

Open Tailscale's Settings, turn on **Start on Login**, and connect. Restart the
Mac, sign into the same macOS user, and wait for Tailscale to show **Connected**
without manually launching it or running `tailscale up`. Then reopen the
private Fleetdeck HTTPS link from the phone. A command-line check can confirm
that `BackendState` is `Running` and `Self.Online` is `true`:

```bash
TAILSCALE_BE_CLI=1 /Applications/Tailscale.app/Contents/MacOS/Tailscale status --json
```

If the app starts but remains disconnected, review its VPN On Demand rules; a
rule set to **Never** can stop the connection. Use Tailscale's own login helper
and VPN settings rather than installing a second Wideband LaunchAgent. On
macOS, Tailscale runs for a signed-in user; availability before macOS login is
not a supported persistence expectation. See Tailscale's documentation for
[Start on Login](https://tailscale.com/docs/features/tailscale-system-policies),
[VPN On Demand](https://tailscale.com/docs/features/client/ios-vpn-on-demand),
and [macOS login behavior](https://tailscale.com/docs/how-to/run-unattended).

## P4-TSSERVE — no serve mappings

**Class:** reachability. Phone surfaces are unreachable.

First enable HTTPS certificates for the tailnet: admin console → Settings →
Features → HTTPS Certificates. Without it `serve` has no certificate to
issue and fails at TLS.

```bash
tailscale serve --bg --https=<port> http://127.0.0.1:<port>
```

**Proof:** the URL opens **on the phone** with a real padlock. Curl from the
machine is not proof — that path can succeed while the phone's fails.

**Ordering matters here.** fleetdeck creates its `serve` mapping during its
own install, and only if the Tailscale CLI already exists. Install Tailscale
*after* `install.sh` and the board is installed with no mapping — nothing is
broken, but nothing is served either. Fix without re-running anything:

```bash
fleetdeck start && fleetdeck url
```

Enable HTTPS Certificates in the admin console **before** that, or `serve`
has no certificate to issue and fails at TLS.

## P5-CLAUDE — claude not on PATH

**Class:** environment.

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

Then open a **new** terminal. The most common cause is checking in the same
shell the installer ran in.

**Proof:** `claude --version` in a new tab.

**If it was never installed at all** — the installer 404s or times out — the
network is blocking `claude.ai`. A filtered corporate, school, or DNS-level
network does this, and it returns a 404 rather than a timeout, so it reads as
a bad URL. Confirm from a phone hotspot.

Homebrew's CDN is often reachable when `claude.ai` is not, so there is a
second route to the same tool:

```bash
brew install --cask claude-code
```

Then open a **new** terminal window — the cask links into
`/opt/homebrew/bin`, and a window that was already open will not see it.
`bootstrap.sh` now attempts this automatically once Homebrew exists.

Observed on a real client machine, 2026-09-10.

## P5-SL — the status line script is missing

**Class:** ledger-vs-object.

```bash
bash install.sh
```

**Proof:** `ls -l ~/.claude/statusline-command.sh`. It does **not** need the
`+x` bit — `settings.json` invokes it as `bash <path>`.

## P5-SLCOLOR — colors print literally

**Class:** none — a code bug, and a subtle one.

The status line shows `\033[0;32m` as text. The colors must be `$'...'`
strings holding real ESC bytes. Written `"\033[0;32m"` they print literally,
because `printf` only expands escapes in its **format** string and these
arrive as `%s` arguments.

**Fix:** re-run `install.sh` to restore the vendored copy.

**Proof:** `grep "\$'" ~/.claude/statusline-command.sh` matches.

## P5-SLJQ — jq missing, status line blank

**Class:** bare-machine. The script parses its JSON input with `jq`; without
it, every field is empty and the line renders blank rather than erroring.

```bash
brew install jq
```

**Proof:** a new `claude` session shows a context percentage.

## P5-SETTINGS — settings.json missing or not wired

**Class:** ledger-vs-object.

```bash
bash install.sh
```

`install.sh` **merges** into an existing `settings.json` rather than
replacing it, so your MCP servers and permissions survive. If the file is
not valid JSON it refuses and says so — fix the JSON first.

**Proof:** `jq -e '.statusLine.command' ~/.claude/settings.json`.

## P5-MD — a required MD file is missing

**Class:** ledger-vs-object.

`~/.claude/CLAUDE.md` is placed by `bootstrap.sh` and `install.sh`.
`~/.claude/USER.md` is **not automated** — it is judgment, and writing it is
a step in the checklist. Until it exists this check fails, correctly.

**Proof:** both files exist and `verify.sh` reports their line counts.

## P5-MDCAP — an MD file is over 200 lines

**Class:** none — a discipline check.

Past 200 lines these files stop being read, by people and by the model,
which makes an over-long file worse than a missing one: it reads as covered.

**Fix:** cut it. Move detail into a skill or a linked doc.

**Proof:** `wc -l` on each is ≤ 200.

## P5-MCP — no MCP servers connected

**Class:** identity, usually — an expired OAuth grant.

```bash
claude mcp list
```

**Fix:** re-authenticate the server that shows a failure. Note that
interactively-authenticated servers are absent in headless runs by design.

**Proof:** `claude mcp list` shows `✔ Connected`.

## P6-IMSGOS — this macOS version cannot run the iMessage transport

**Class:** bare-machine assumption. The upstream `imsg` transport requires
macOS 14 or newer. Wideband Setup can still build its general workstation on
macOS 13, but it cannot claim that texting the head agent works there.

**Fix:** use a Mac running macOS 14 or newer for the iMessage head runtime.

**Proof:** `sw_vers -productVersion` begins with 14 or higher, and
`~/bin/wb-imessage check` reports `"macos_supported": true`.

## P6-IMSG — the Messages transport is missing

**Class:** ledger-vs-object. A Messages Automation grant is not a listener.

**Fix:** for a packaged 0.8.0 client install, reopen the downloaded Wideband
Setup app and inspect its private-tool preflight. It includes a checksum-pinned
`imsg` transport and must never borrow a different profile's Homebrew binary.
The legacy source/operator install can still use the upstream
[`imsg` install guide](https://github.com/openclaw/imsg/blob/main/docs/install.md).

**Proof:** `~/srv/wb-setup/lib/toolchain-path imsg` returns a verified path;
that path's `--version` succeeds. No test message is sent by this check.

## P6-IMSGCFG — the private head runtime is not configured

**Class:** identity. The transport needs the owner's phone number, chosen OS
and agent names, and a private workspace before it can bind a chat.

**Fix:** complete the naming step in Wideband Setup and run its **Set up head
agent** action. That action passes the private answers on stdin to
`wb-imessage init`; addresses do not belong in shell history or support logs.
An existing runtime identity is preserved by repair.

**Proof:** `~/bin/wb-imessage check` reports `"configured": true`.

## P6-IMSGCHAT — the owner chat is not bound or no longer matches

**Class:** identity. The route accepts only a one-to-one iMessage chat with the
configured owner number. It pins the chat ID, GUID, participant, and signed-in
Messages account. A stale row ID or a group chat is refused.

**Fix:** the client personally signs a **separate Apple Account** into
Messages on the agent Mac, then sends a fresh text from their phone. In the
guided installer, confirm that separate-account step and run **Bind my text
chat** within ten minutes. A changed binding needs operator review; do not
silently retarget outbound messages.

**Proof:** `~/bin/wb-imessage check` reports `"target_verified": true`.
The final human proof is a real reply visible on the client's phone.

## P6-IMSGHEAD — the persistent head agent is absent

**Class:** ledger-vs-object. The `wb-head` session must have a recognized live
agent in its active pane; a bare shell is not a destination for text.

**Fix:** check that Claude is installed and signed in, then inspect
`tmux list-panes -s -t '=wb-head' -F '#{pane_current_command}'`. The keeper
creates a missing session on its next interval. It leaves an unexpected live
shell alone for operator review.

**Proof:** `~/bin/wb-imessage check` reports `"head_session": true`.

## P6-IMSGSERVICES — an iMessage runtime service is not loaded

**Class:** ledger-vs-object. The watcher, router, head keeper, and guarded
outbox are four separate LaunchAgents. Before an exact chat is bound, their
plists stay in the private `~/.wideband/imessage/launchagents/` staging folder,
outside `~/Library/LaunchAgents/`. A plist in the live folder can start at the
next GUI login even if `launchctl bootstrap` was never run.

**Fix:** run Wideband Setup's iMessage install action again
(`bash ~/srv/wb-setup/install.sh --imessage-only --no-verify`). While unbound,
it moves only this organization's four iMessage plists out of LaunchAgents and
boots out their loaded jobs. After the client binds the exact owner chat, the
same command installs and loads them. Leave unrelated LaunchAgents untouched. Inspect
`launchctl list` for `imessage-watch`, `imessage-route`, `imessage-keep`, and
`imessage-outbox` under this Mac's `com.$ORG` prefix. If a service is loaded
but failing, inspect its private log under `~/.wideband/imessage/logs/`.

**Proof:** `~/bin/wb-imessage check` reports `"services_loaded": true`,
then a real text receives a reply on the phone and still does after restart.

## P7-CONF / P7-TPM — tmux config or plugins missing

**Class:** ledger-vs-object.

```bash
bash install.sh
```

Then, inside tmux, press **prefix + I** once (Ctrl-a, then Shift-i) to fetch
the plugin set. `install.sh` clones tpm but cannot press the key for you.

**Proof:** `ls ~/.config/tmux/plugins/` shows more than `tpm`.

## P7-TM — tm or tm-standard missing

**Class:** ledger-vs-object. Three tmux keybindings (T, G, S) depend on
these; without them each popup prints a "not installed" message rather than
failing silently.

```bash
bash install.sh
```

They are **copied** to `~/bin`, not symlinked into the Homebrew prefix —
brew can clobber that path, and see class 1.

**Proof:** `tm ls` lists your sessions.

## P7-STD — no session standard

**Class:** ledger-vs-object.

```bash
bash install.sh                       # seeds it if absent, never overwrites
```

If you already curated one elsewhere, `install.sh` leaves it alone by
design.

**Proof:** `cat ~/.config/tmux-command-center/config/sessions.conf`.

## P7-SESS — standard sessions are not running

**Class:** ledger-vs-object. The standard lists sessions; the server is not
running them. Counting sessions would pass this; checking names does not.

```bash
tm-standard          # drift: ok · ~ elsewhere · -- missing
tm-standard apply    # create what is missing; never kills a live session
```

If they are missing **after a reboot**, the `tmux-boot` agent is not loaded
— that is P8-LOAD, not this.

**Proof:** `tm-standard` shows `ok` for every row.

## P8-LOAD — no agents loaded

**Class:** ledger-vs-object.

```bash
bash install.sh
launchctl list | grep "com.$ORG"
```

If loading fails, background items may be blocked: Settings → General →
Login Items & Extensions.

**Proof:** the agents appear, and after a reboot they are still there.

## P8-EXIT — an agent is loaded but failing

**Class:** environment, usually. **This is the most important failure in the
build**, because everything looks installed and nothing is delivering.

```bash
launchctl list | grep "com.$ORG" | awk '$2!=0'
cat /tmp/com.$ORG.<name>.log
```

Almost always the plist's `PATH` or `HOME` — the job cannot find a tool that
is on *your* PATH. Compare against a working plist in
`templates/launchagents/`.

**Proof:** the exit column reads `0` **and** the log shows a recent
successful run. A job that has never fired is not fixed, it is untested.

## SHELL-PATH — installed, but "command not found"

**Class:** environment divergence, and the most expensive kind: it looks
exactly like a failed install.

`install.sh` adds `~/bin` and `~/.local/bin` to `.zshrc`. A terminal window
opened **before** that line existed will never see them. The binary is on
disk, working, and unreachable from that one window.

```bash
ls -l ~/bin/fleetdeck ~/bin/tm ~/.local/bin/claude 2>/dev/null
```

**Fix:** open a new terminal window. That is the whole fix.

To use it without opening one:

```bash
~/bin/fleetdeck url          # full path always works
source ~/.zshrc              # or reload the current shell
```

**Proof:** `command -v fleetdeck` prints a path. On the first live build
this cost two rounds of debugging an install that had already succeeded —
which is why `verify.sh` now separates "not installed" from "not on PATH".

## P9-FLEET — fleetdeck not installed

**Class:** ledger-vs-object.

`install.sh` clones and installs it, seeding `config.json` from `$BRAND` and
`com.$ORG`. If it is missing, that step failed or was skipped.

```bash
bash install.sh                         # or NO_FLEETDECK=1 to skip on purpose
cat /tmp/wb-fleetdeck-install.log
```

It needs `tmux` and `ttyd` on PATH — both are in the Brewfile — and it
**refuses** to install from `~/Documents`, `~/Desktop` or `~/Downloads`,
because launchd cannot read those without a Full Disk Access grant.

Without Tailscale the board still installs; the portal simply stays
loopback-only until the tailnet is up. That is not a failure.

**Proof:** `fleetdeck doctor` reports every surface, and `fleetdeck url`
prints an address that opens on the phone.

## P9-PINNED — config.json pins a machine name

**Class:** identity. The board works here and breaks on the next machine.

`machine` must stay **empty** so fleetdeck resolves it from Tailscale at
boot. A pinned value is how a build stops being portable — the same mistake
as hardcoding a hostname in a loop.

```bash
jq '.machine = ""' ~/srv/fleetdeck/config.json > /tmp/fd.json \
  && mv /tmp/fd.json ~/srv/fleetdeck/config.json
cd ~/srv/fleetdeck && ./install.sh
```

**Proof:** `jq -r .machine ~/srv/fleetdeck/config.json` prints nothing, and
`fleetdeck url` still returns the right host.

---

# Part 3 — silent failures

Nothing errors. Something is still wrong. These need their own detection
because no exit code will ever tell you.

| What you see | What it is | How to confirm |
|---|---|---|
| Playwright screenshots are **black** | Screen Recording not granted | grant it, retake one, look at it |
| Status line **blank** | `jq` missing | `command -v jq` |
| Status line shows `\033[…]` | colors not `$'...'` | `grep "\$'" ~/.claude/statusline-command.sh` |
| Migration "ran", column absent | `db push` re-ran the ledger | query the **object**, not the ledger |
| Prod has no env vars | stale `.vercel/project.json` | check the project name in the dashboard |
| Loop installed, nothing arrives | loaded but exiting non-zero | `launchctl list \| awk '$2!=0'` |
| Board works here, not on the next machine | `machine` pinned in `config.json` | leave it empty; resolve from Tailscale |
| Phone can't open a surface that curls fine | HTTP, or loopback bind | test **from the phone**, always |

The pattern: **an absence never raises.** A job that never ran, a grant that
was never given, a field that was never filled — none of them produce an
error, and all of them look like success from a distance. Anything that
matters gets an assertion, not an assumption.

---

# Part 4 — day two

It worked for weeks and then stopped. These are the causes, roughly in order
of how often they bite.

## `brew upgrade` voided a TCC grant

**Class 1.** A formula upgrade changes the resolved real path, and the grant
was attached to the old one. Nothing announces this. Symptoms appear as a
permission that was working and now is not.

```bash
bash doctor.sh | sed -n '/tools (resolved/,/permissions/p'
```

Re-grant against the new real path.

## A macOS major upgrade reset permissions

**Class 1.** Major upgrades re-prompt for, and sometimes clear, TCC grants,
and can reset `pmset`. After any major upgrade, re-run the whole of Phase 0
rather than assuming.

```bash
bash verify.sh | grep -E 'P0-'
```

## A loop stopped firing

**Class 5.** Three distinct causes with the same symptom:

- non-zero exit — `launchctl list | awk '$2!=0'`
- launchd throttling after repeated fast failures — check `ThrottleInterval`
  and the log for a crash loop
- the machine slept through the scheduled time — `pmset -g`

A calendar job that missed its window does **not** run late. It waits for
the next one.

## Tailscale node key expired

**Class 4.** Node keys expire (commonly ~180 days) and the machine drops off
the tailnet. Every phone surface goes dark at once, which is the tell — a
single broken surface is not this.

```bash
tailscale status          # shows the expiry / logged-out state
```

Re-authenticate, and consider disabling key expiry for a server that must
stay reachable.

## Logs filled the disk

Only `healthcheck` self-caps today, at 2000 lines. Everything else in
`/tmp/com.$ORG.*.log` grows without bound.

```bash
bash doctor.sh | sed -n '/── machine/,/── identity/p'   # disk free
du -sh /tmp/com.*.log
```

This is a **real gap in the build**, not user error — log rotation for every
loop is on the list.

## Credentials expired

Anthropic subscription, Supabase keys, Vercel token, MCP OAuth grants. Each
fails in its own way and none of them announce it in advance.

```bash
claude mcp list
gh auth status
```

## The resurrect directory was wiped

**Class 5.** Window and pane layout is gone, sessions do not come back as
they were. This is exactly what `sessions.conf` is the safety net for:
resurrect carries the transient detail, the standard carries the names and
roots.

```bash
tm-standard apply
```

## Something changed and nobody wrote it down

Run `doctor.sh` and read the **drift** section. It compares every verbatim
artifact against the repo copy. `DIFFERS from repo` means someone edited the
installed copy — which works until the next `install.sh` silently reverts
it. Move the change into the repo and re-install.

---

## When none of this helps

```bash
bash doctor.sh > /tmp/doctor.txt
```

Paste that file to the agent, or to whoever is helping. It carries the
resolved real paths, the launchd exit codes, and the drift report — the
three things that are almost never in a description of the problem and
almost always in the cause.
