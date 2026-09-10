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

The reverse also bites: a script that hardcodes `/Users/studio` works on one
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

**Class:** grant-path. Message scanning silently returns nothing.

```bash
sqlite3 ~/Library/Messages/chat.db "select count(*) from message;"
```

A number means granted. An error means not.

**Fix:** Settings → Privacy & Security → Full Disk Access → add Terminal.
Then **quit Terminal completely and reopen it** — the grant does not apply
to the running process. If the messaging tool is what fails, grant to its
*real binary path* (`/opt/homebrew/bin/imsg`), not to a wrapper.

**Proof:** the `sqlite3` command above returns a count in a *new* terminal.

## P0-SSH — Remote Login is off

**Class:** reachability.

```bash
launchctl print-disabled system | grep sshd
```

**Fix:** Settings → General → Sharing → Remote Login → on.

**Proof:** the command prints `"com.openssh.sshd" => enabled`. Do not check
`lsof -iTCP:22` — see class 4; it shows an unprivileged user nothing either
way.

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

## P5-CLAUDE — claude not on PATH

**Class:** environment.

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

Then open a **new** terminal. The most common cause is checking in the same
shell the installer ran in.

**Proof:** `claude --version` in a new tab.

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
