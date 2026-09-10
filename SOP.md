# SOP — Full stack deployment

**Universal.** Bare M-chip Mac → a complete operator build, for any
operator, any org. Same result every time. This is the cheat sheet and
the checklist in one document.

Nothing below is hardcoded to one person or one company. Every
identity-shaped value is a variable, set once in §Variables and
referenced everywhere after. A worked example — the reference build this
SOP was extracted from — lives in Appendix A, clearly separated so it is
never mistaken for the procedure.

**Last updated:** 2026-09-10
**Requirements:** Apple silicon Mac (M-series), macOS 13.0+, an AI
subscription (Claude Pro/Max, or Console API key).
**Time:** ~3 hours hands-on. Permissions and DNS waits are most of it.

---

## Start here

One line, on a bare machine, before anything else:

```bash
curl -fsSL https://raw.githubusercontent.com/widebandz/wb-setup/main/bootstrap.sh | bash
```

It installs Claude Code first (zero dependencies, seconds), throws
Homebrew into the background, writes `~/.sop-vars`, places the agent's
runbook, and prints the queue of sign-ins and permission dialogs to work
**while the download runs**.

That ordering is deliberate and it is not the order this document reads
in. Three resources are in play — the machine, the human, and the agent —
and they do not contend. The machine downloads unattended; the human is
the scarce resource; the agent does the bulk but only once authed. So the
agent's installer goes first, the long download goes to the background,
and the human is never left watching a progress bar.

The common mistake is installing Homebrew first and waiting on it. Claude
Code is not behind Homebrew and never was.

Then:

```bash
claude                      # authenticate → the agent is live
bash ~/srv/wb-setup/verify.sh    # what is actually true on this machine
bash ~/srv/wb-setup/install.sh   # phases 5-9, once brew and auth are in
```

The phases below are the full procedure — what the agent works through,
and what you fall back to when a step needs a human or goes wrong.

---

## The build, in one picture

```
 ┌─ WEB STACK ─────┐  ┌─ INFRA + SERVER ─┐  ┌─ CLAUDE LAYER ──┐  ┌─ LOOPS + FUNCTION ┐  ┌─ BONUS REPOS ───┐
 │ Next.js         │  │ Homebrew         │  │ Claude Code     │  │ iMessage send     │  │ gods-eye-view   │
 │ TypeScript      │  │ Tailscale + HTTPS│  │ status line     │  │ iMessage scan     │  │ watch-youtube   │
 │ Tailwind CSS    │  │ tmux             │  │ SKILLS          │  │ daily usage text  │  │ ig-transcript   │
 │ Supabase        │  │ LaunchAgents     │  │  frontend-design│  │ email recap       │  │ WIM             │
 │ Vercel          │  │ fleetdeck        │  │  impeccable     │  │ tmux boot + save  │  │                 │
 │ Three.js        │  │ knowledge graph  │  │  code-review    │  │ healthcheck       │  │ installed via   │
 │                 │  │ global MD        │  │ TOOLS           │  │ service watchdog  │  │ fleetdeck adopt │
 │                 │  │ server scripts   │  │  Playwright     │  │ graph rebuild     │  │                 │
 │                 │  │                  │  │  Remotion       │  │ wakeup            │  │                 │
 │                 │  │                  │  │ MCP: Gmail,     │  │                   │  │                 │
 │                 │  │                  │  │  Drive, Cal,    │  │                   │  │                 │
 │                 │  │                  │  │  Supabase,      │  │                   │  │                 │
 │                 │  │                  │  │  Vercel, PW     │  │                   │  │                 │
 │                 │  │                  │  │ MD SURFACE      │  │                   │  │                 │
 │                 │  │                  │  │  CLAUDE · USER  │  │                   │  │                 │
 │                 │  │                  │  │  MEMORY · AGENTS│  │                   │  │                 │
 └─────────────────┘  └──────────────────┘  └─────────────────┘  └───────────────────┘  └─────────────────┘
        the app            the machine           the operator          the machine            optional
                                                     loop              running itself          surfaces
```

**Install order is not the column order.** Permissions first, then the
machine, then the operator loop, then the app, then the loops, then the
bonus surfaces. Phases below.

---

## Variables — set these once

Consistency across builds comes from one substitution table, not from
remembering. `bootstrap.sh` prompts for these and writes the file; this is
what it writes, and what to edit by hand afterward.

```bash
cat > ~/.sop-vars <<'EOF'
# Identity for this build. Everything downstream reads these.
export ORG="acme"                                  # reverse-domain slug → com.acme.*
export BRAND="fleetdeck"                           # name shown on the board
export MARK="◈"                                    # one cell, tmux status line
export GH_USER="acme-eng"                          # the ONLY GitHub identity used
export GIT_EMAIL="ops@acme.com"
export OPERATOR_PHONE="+15551234567"               # where the machine texts
export WORK_REPO="git@github.com:acme-eng/app.git"
export GRAPH_PACK="acme"                           # knowledge-graph corpus name
EOF
echo 'source ~/.sop-vars' >> ~/.zshrc && source ~/.sop-vars
```

| Variable | Meaning | Set at |
|---|---|---|
| `ORG` | reverse-domain slug; names every LaunchAgent `com.$ORG.*` | now |
| `BRAND` | board name, uppercased in the fleetdeck UI | now |
| `MARK` | the operator's mark, one cell wide, in the tmux status line | now |
| `GH_USER` | the one GitHub identity — a second identity breaks deploys | now |
| `GIT_EMAIL` | commit author | now |
| `OPERATOR_PHONE` | delivery target for texts and briefs | now |
| `WORK_REPO` | the app this machine builds | now |
| `GRAPH_PACK` | which corpus the knowledge graph indexes | now |
| `MACHINE` / `TAILNET` | MagicDNS name | **resolved from Tailscale at runtime — do not hardcode** |

**No script in this build hardcodes any of these.** A loop reads
`~/.sop-vars` and nothing else; that is the single property that makes the
next machine come out the same as this one. When extracting a script from
a working machine, the hardcoded phone number or hostname inside it is the
thing to remove first.

`MACHINE` and `TAILNET` are deliberately absent. Tools resolve them at
boot; pinning them is how a build stops being portable.

---

## Phase 0 — DO NOT SKIP

Every one of these is a macOS permission dialog. Miss one and a loop
fails silently three phases later, which is the most expensive kind of
failure in this build. Grant them all up front, before anything needs
them.

| # | Grant | Where | Without it |
|---|---|---|---|
| 0.1 | **Remote Login (SSH)** | Settings → General → Sharing → Remote Login **ON** | no remote reach into the machine |
| 0.2 | **Full Disk Access** — Terminal, iTerm, VS Code, `/opt/homebrew/bin/imsg` | Settings → Privacy & Security → Full Disk Access | message scanning cannot read `~/Library/Messages/chat.db` |
| 0.3 | **Automation** — Terminal → Messages, Terminal → System Events | Privacy & Security → Automation (prompts on first use; approve) | agent cannot send texts |
| 0.4 | **Accessibility** — Terminal / iTerm | Privacy & Security → Accessibility | window control and AppleScript automation fail |
| 0.5 | **Screen Recording** — Terminal, VS Code | Privacy & Security → Screen Recording | Playwright captures come back black |
| 0.6 | **Background items allowed** | Settings → General → Login Items & Extensions | LaunchAgents do not survive reboot |
| 0.7 | **Command line tools** | `xcode-select --install` | native npm modules fail to build |
| 0.8 | **Never sleep** | `sudo pmset -a sleep 0 disksleep 0` (plugged in) | scheduled loops miss their window |
| 0.9 | **Sign in to Messages** | Messages.app → Settings → iMessage | no delivery channel to the operator |

Grants attach to a **binary path**, not to a name. The messaging tool
needs its grants on the real binary (`/opt/homebrew/bin/imsg`); a grant
on a wrapper script is a different grant and will not work.

**Verify Phase 0:**

```bash
sqlite3 ~/Library/Messages/chat.db "select count(*) from message;"   # a number = FDA granted
ssh localhost 'echo ok'                                              # ok = remote login on
pmset -g | grep -E '^\s*sleep'                                       # 0
```

---

## Phase 1 — Accounts, email first

Email is first because every other account verifies through it. Confirm
mail arrives **before** creating anything else.

1. **Apple ID** — iCloud + Messages. The delivery channel.
2. **Email** — the operator mailbox. Send yourself one. Confirm arrival.
3. **GitHub** — as `$GH_USER`, and only that identity. A second account
   on the same machine blocks deploys and is painful to unwind.
4. **Anthropic** — Pro/Max subscription (default) or Console API key.
5. **Tailscale** — same identity on every node of the tailnet.
6. **Vercel** — linked to the GitHub account from step 3.
7. **Supabase** — project owner.
8. **Google Cloud** — OAuth client for the Gmail MCP (Phase 5.6).
9. **As the app requires:** transactional mail, bot-gate, error tracking,
   CRM, voice. See Phase 6 for which keys the app actually reads.

**Gate:** mail confirmed working both directions. Do not proceed without it.

---

## Phase 2 — Editor

Install VS Code, then install the shell command — this is the step
people skip:

```
Cmd+Shift+P → "Shell Command: Install 'code' command in PATH"
```

**Verify:** `code --version` prints.

---

## Phase 3 — Homebrew + core CLIs

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

On Apple silicon the installer prints two `eval` lines that put
`/opt/homebrew/bin` on the PATH. Run them. They are easy to scroll past
and nothing below works without them.

```bash
brew install node tmux gh jq ffmpeg python git sqlite ttyd
brew install supabase/tap/supabase
npm install -g vercel@latest
```

```bash
gh auth login                              # HTTPS · browser · as $GH_USER
git config --global user.name  "$GH_USER"
git config --global user.email "$GIT_EMAIL"
```

**Verify:** `brew --version`, `node -v` (24 LTS+), and `gh auth status`
names `$GH_USER`. Any other account — log out and redo.

---

## Phase 4 — Tailscale + HTTPS

The tailnet is how the operator's phone reaches this machine. Plain HTTP
on a tailnet port fails Safari's HTTPS-First: the surface is unreachable
from the phone, not merely ugly.

Install the **standalone macOS app** from tailscale.com/download — not
the Mac App Store build. The standalone app ships the CLI. Link it:

```bash
cat > /opt/homebrew/bin/tailscale <<'SH'
#!/bin/sh
exec "/Applications/Tailscale.app/Contents/MacOS/Tailscale" "$@"
SH
chmod +x /opt/homebrew/bin/tailscale
```

**Enable HTTPS certificates** in the tailnet admin console:
Settings → Features → HTTPS Certificates. Without this, `tailscale serve
--https` has no certificate to issue and every phone surface fails at TLS.

```bash
tailscale serve --bg --https=<port> http://127.0.0.1:<port>
tailscale serve status                     # prints this machine's real URLs
```

**Three rules that hold every time:**
- Bind dev servers `-H 0.0.0.0`. A loopback bind is invisible to the proxy.
- Never send a `localhost` or `.local` link. It will not open.
- One link per delivery.

**Verify:** the URL opens on the phone with a real padlock, no interstitial.

---

## Phase 5 — The Claude layer

### 5.1 Install

```bash
curl -fsSL https://claude.ai/install.sh | bash    # native; no Node/brew/npm needed
claude --version
claude                                            # browser login
```

Binary at `~/.local/bin/claude`, auto-updates, credentials in Keychain.
`command not found: claude` means `~/.local/bin` is off the PATH.

### 5.2 Status line — context visibility

Three segments — **directory | model | context used/left** — with the
context segment color-graded so cost is visible at a glance rather than
computed in your head.

```
~/app | Opus 5 | ctx: 34% used / 66% left
 cyan    magenta    green <50 · yellow ≥50 · red ≥80
```

`~/.claude/statusline-command.sh`:

```bash
#!/usr/bin/env bash
# Claude Code status line: directory | model | context window usage
input=$(cat)
cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // ""')
model=$(echo "$input" | jq -r '.model.display_name // ""')
used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
remaining=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')
short_cwd="${cwd/#$HOME/~}"
ctx_segment=""
if [ -n "$used" ]; then
  used_int=$(printf '%.0f' "$used"); remaining_int=$(printf '%.0f' "$remaining")
  if   [ "$used_int" -ge 80 ]; then color=$'\033[0;31m'
  elif [ "$used_int" -ge 50 ]; then color=$'\033[0;33m'
  else                                color=$'\033[0;32m'; fi
  reset=$'\033[0m'
  ctx_segment=" | ${color}ctx: ${used_int}% used / ${remaining_int}% left${reset}"
fi
printf "\033[0;36m%s\033[0m | \033[0;35m%s\033[0m%s" "$short_cwd" "$model" "$ctx_segment"
```

Two details that break it if changed: `jq` must be installed (Phase 3),
and the colors must be `$'...'` strings holding real ESC bytes — written
`"\033[0;32m"` they print literally, because `printf` only expands escapes
in its *format* string and these arrive as `%s` arguments.

```bash
chmod +x ~/.claude/statusline-command.sh
```

`~/.claude/settings.json`:

```json
{
  "statusLine": { "type": "command", "command": "bash /Users/<user>/.claude/statusline-command.sh" }
}
```

**Verify:** open `claude`; the line renders, and the context percentage
moves as the session fills.

### 5.3 Skills

| Skill | Source | Purpose |
|---|---|---|
| **frontend-design** | plugin `frontend-design@claude-plugins-official` | visual direction, typography, non-templated UI |
| **impeccable** | `~/.claude/skills/impeccable/` | UI audit — hierarchy, cognitive load, a11y, motion |
| **code-review** | built-in `/code-review` | reviews the working diff |
| supabase · vercel · claude-code-setup | official plugins | stack-specific guidance |

Enable plugins in `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "frontend-design@claude-plugins-official": true,
    "supabase@claude-plugins-official": true,
    "vercel@claude-plugins-official": true,
    "claude-code-setup@claude-plugins-official": true
  }
}
```

User skills are directories at `~/.claude/skills/<name>/SKILL.md` and
apply everywhere. Project skills live at `<repo>/.claude/skills/` and
arrive with the clone.

**Verify:** in a session, `/` lists the skills by name.

### 5.4 Tools

| Tool | Install | Used for |
|---|---|---|
| **Playwright** | `npx playwright install` + MCP server | driving the real app, capture, E2E |
| **Remotion** | `remotion` in the video project (4.0.x) | instructional and product video render |

### 5.5 The MD surface

Five files the operator reads and edits. **Cap each at 200 lines** — past
that they stop being read, by people and by the model.

| File | Path | Holds |
|---|---|---|
| **CLAUDE.md** (global) | `~/.claude/CLAUDE.md` | rules that apply on every project |
| **USER.md** | `~/.claude/USER.md` | who the operator is; voice; standing preferences |
| **CLAUDE.md** (project) | `<repo>/CLAUDE.md` | this repo's operating manual |
| **AGENTS.md** | `<repo>/AGENTS.md` | the agent fleet, boundaries, cross-check matrix |
| **MEMORY.md** | `~/.claude/projects/<slug>/memory/MEMORY.md` | index of persisted facts, one line each |

The global pair (`CLAUDE.md`, `USER.md`) is what makes a build *custom*
while the rest stays *consistent* — same machine everywhere, different
operator in two files.

**Verify:** all five exist and each is ≤200 lines.

```bash
wc -l ~/.claude/CLAUDE.md ~/.claude/USER.md <repo>/CLAUDE.md <repo>/AGENTS.md \
      ~/.claude/projects/*/memory/MEMORY.md
```

### 5.6 MCP servers

```bash
claude mcp list
```

Target state — six connected:

| Server | Transport | Gets you |
|---|---|---|
| Gmail | `https://gmailmcp.googleapis.com/mcp/v1` | read/draft/send mail; feeds the email recap |
| Google Drive | `https://drivemcp.googleapis.com/mcp/v1` | documents |
| Google Calendar | `https://calendarmcp.googleapis.com/mcp/v1` | scheduling |
| Supabase | `https://mcp.supabase.com/mcp` | schema, migrations, advisors |
| Vercel | `https://mcp.vercel.com` | deployments, logs, env |
| Playwright | `npx @playwright/mcp@latest` | the browser |

Gmail also needs OAuth on disk for the **non-MCP** loops: the email recap
reads `~/.gmail-mcp/gcp-oauth.keys.json` and
`~/.gmail-mcp/credentials.json` directly, stdlib only, so it runs whether
or not a Claude session is open.

**Verify:** `claude mcp list` shows ✔ Connected on all six.

---

## Phase 6 — The web stack

**Existing project:**

```bash
git clone "$WORK_REPO" ~/app && cd ~/app
npm install && cp .env.example .env.local
```

**New project:**

```bash
npx create-next-app@latest app --typescript --tailwind --app --eslint
cd app
npm install @supabase/supabase-js @supabase/ssr
npm install three @react-three/fiber @react-three/drei
npm install -D @playwright/test && npx playwright install
```

Versions this build is proven on: Next 14.1 · React 18.2 · TypeScript 5.3
· Tailwind 3.4 · three 0.161 · @react-three/fiber 8.18 · drei 9.122 ·
@playwright/test 1.52 · Remotion 4.0.

**Stack keys** — every app on this stack reads these:

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | browser client |
| `SUPABASE_SERVICE_ROLE_KEY` | server actions, admin, storage |
| `NEXT_PUBLIC_SITE_URL` | auth redirects |

**Common add-ons** — include the ones the app actually uses, omit the rest:
transactional mail (`RESEND_API_KEY`), bot gate
(`NEXT_PUBLIC_TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`, plus
`TURNSTILE_SKIP=true` for local dev), error tracking (`SENTRY_DSN`),
operator notifications (`OPERATOR_EMAIL`).

**Database.** Apply migrations individually, in order, from
`supabase/migrations/`. Never `supabase db push` against a project with
an existing ledger — it re-runs everything. Verify the *object* exists,
not that the ledger says it ran.

**Deploy.** Vercel builds from the GitHub push. Confirm the project link
is real before trusting it — a stale `.vercel/project.json` points at an
empty project with no env vars and no domain.

```bash
npm run dev -- -H 0.0.0.0     # desktop + tailnet
npm run dev:https             # required for mic/camera surfaces
```

---

## Phase 7 — tmux workspace

The machine has to survive a reboot without anyone rebuilding context by
hand.

```
~/.config/tmux/tmux.conf        session config
~/.config/tmux/tmux-boot.sh     builds the standing sessions
~/.config/tmux/tmux-save.sh     snapshots state every 15 min
~/.config/tmux/healthcheck.sh   watches the sessions every 5 min
~/.config/tmux/plugins/         tpm · resurrect · continuum · sensible · yank
```

**Standing sessions: one per concern, never one per task.** Name them for
the thing that persists — the app, production, the UI, messages, the
tunnel, each long-running workstream. A session per task means the set
churns daily and `tmux-boot.sh` goes stale within a week.

**Verify:** reboot. The sessions come back on their own. If you have to
run `tmux-boot.sh` by hand, the LaunchAgent is not loaded.

---

## Phase 8 — Loops and scripts

LaunchAgents in `~/Library/LaunchAgents/`, labeled `com.$ORG.*`. Scripts
in `~/bin` — **its own git repo, with a private remote.** This is the set
that earns its place on every build.

| Loop | Schedule | Does |
|---|---|---|
| `imsg.router` | keepalive | routes inbound texts to the right agent |
| `imsg.watch` | keepalive | scans Messages for commands |
| `cost-watch` | daily 08:00 | **daily usage text** — sums `~/.claude/projects/**/*.jsonl`, yesterday's tokens vs a 7-day norm, flags spikes. Dollar figure is a labeled list-price *equivalent*; on a subscription it is covered, not billed |
| `gmail-overview` | 07:00 · 09:00 · 11:00 | **email recap** — unread + starred, NEEDS REPLY (real people only; strips List-Unsubscribe / List-Id / no-reply senders), recent unread |
| `tmux` | on-demand at boot | builds the standing sessions |
| `tmux-save` | every 900s | snapshots session state |
| `healthcheck` | every 300s | session watch → a log |
| `service-watchdog` | 08 · 12 · 16 · 20 | restarts anything that died |
| `graph` | scheduled | rebuilds the knowledge graph + reconstitution manifest |
| `wakeup` | daily 05:00 | morning start |

**Business loops are org-specific and belong to the org's own repo, not
to this SOP.** CRM reconcilers, deal-stage watchers, follow-up chasers,
and standup nudges follow the same pattern — script in `~/bin`, plist
beside it — but which ones exist depends on how the org sells.

### The messaging channel

```bash
imsg <number|alias> <message>          # positional send
imsg send --to <n> --text <t>          # native subcommand
imsg chats|history|watch|react|read    # passthrough
```

Aliases live in `~/.imsg-contacts`. Transport is the Homebrew `imsg`
binary at `/opt/homebrew/bin/imsg` — the TCC grants from Phase 0 sit on
that exact path, which is why a wrapper should delegate to it rather than
reimplement sending. iMessage only; **text is reliable, attachments are
not.** Send a link.

**Verify each loop by its output, not by `launchctl list`.** A loaded job
with a non-zero last exit is a broken loop that looks installed.

```bash
launchctl list | grep "com.$ORG" | awk '$2!=0'    # anything printed is failing
```

---

## Phase 9 — fleetdeck

One launcher page for every server and LaunchAgent on the Mac, plus the
tmux fleet as a chat. Installed to `~/srv/fleetdeck`. The repo *is* the
deployment — nothing is copied out except the launcher script and the
plists.

```bash
git clone https://github.com/widebandz/fleetdeck.git ~/srv/fleetdeck
cd ~/srv/fleetdeck && ./install.sh
fleetdeck status && fleetdeck url
```

Four surfaces, ports from `config.json`: portal **8790** · chat **8783** ·
ttyd **8784** (loopback only, proxied under `/t`, never linked) · adopt
**8793**.

```bash
fleetdeck start|stop|restart|status|doctor|url|log|edit|audit|icons
fleetdeck adopt <repo-url>          # inspect only; --yes installs
fleetdeck icons                     # regenerate home-screen icons
```

**This is where `ORG` and `BRAND` land.** Identity lives in
`config.json` — `brand`, `label_prefix` (`com.$ORG`), `machine`, ports.
Nothing branded is hardcoded in the servers, which is exactly what makes
the build reusable per operator. **Leave `machine` empty** and it resolves
from Tailscale at boot; setting it pins the build to one host.

`adopt` **installs software**. Do not give it a `tailscale serve` mapping
without reading the README first; `install.sh` deliberately leaves it
unexposed.

---

## Phase 10 — Knowledge graph

Indexes the declared roots into cited claims, then fences one claim and
tries to break it. It lives **outside** the repos it reads, so no tree is
privileged by accident of location, and it indexes nothing of itself.

The engine is a private repo. On a build with granted access, clone it
after `gh auth` exists (Phase 3) — before that there is no credential to
clone with:

```bash
gh repo clone <org>/<graph-engine> ~/graph
cd ~/graph && npm install
npm run graph -- build
npm run graph -- status
npm run serve                       # the viewer
```

**Without access, Phase 10 is optional and the build is still complete.**
Every other phase stands on its own; the graph adds the question-answering
and the reconstitution score, not the machine's function. `verify.sh`
treats it as not-applicable rather than failed.

The corpus boundary is written down in `packs/$GRAPH_PACK/roots.yaml` —
declare every load-bearing tree there, including the main one. A root
that is load-bearing but undeclared is invisible to every question below.

What is indexed is **structure** — paths, imports, routes, DDL objects,
dependency names, document titles. Never client rows, secret values, or
file bodies.

```
ask ghosts          cited documents that do not exist
ask shared          same relative path in 2+ roots — identical or drifted (sha256)
ask deps            dependency versions that disagree across roots
ask contradictions  where two canonical sources disagree
ask roots           what is indexed, under whose authority
ask plane           the live view — sessions, ports, loaded jobs
```

### Reconstitution — the drill that scores the build

```bash
cd ~/glitch-cat && npm run drill
```

`RECONSTITUTION.md` is generated on every build and answers one question:
*if this disk died, what would be gone?* It splits every host artifact
into **reproducible** (has a source file in an indexed root) and
**unrecoverable** (exists here and nowhere else).

**That ratio is the score for this SOP.** A fresh build starts badly —
LaunchAgent definitions and tailnet endpoints exist only on the disk that
holds them. Every loop moved into `~/bin` with a plist committed beside
it moves one artifact across. Run the drill at the end of the build and
record the number in the build record.

---

## Phase 11 — Bonus repos

Optional surfaces. Install through `fleetdeck adopt <repo-url>` so they
land on the board with the rest of the fleet.

| Repo | What |
|---|---|
| **gods-eye-view** | photorealistic 3D globe — live aircraft, ships, satellites, quakes, public cams; voice control. `github.com/bilawalsidhu/gods-eye-view` |
| **watch-youtube** | watch/summarize YouTube as a Claude skill — [URL to record] |
| **instagram-transcript** | Instagram video → transcript — [URL to record] |
| **WIM** | Wideband Interactive Media · `github.com/widebandz/wim` |

---

## File structure

The shape the knowledge graph and the loops assume. Match it and every
command in this SOP works unmodified.

```
~/
├── bin/                       operator commands — git repo, private remote
│   └── (imsg, cost-watch, gmail-overview, watchdog, …)
├── srv/
│   └── fleetdeck/             the deck — portal · chat · ttyd · adopt
├── glitch-cat/                knowledge graph; indexes the roots, never itself
│   └── packs/$GRAPH_PACK/roots.yaml   ← the corpus boundary, written down
├── app/                       the work repo
├── <other-declared-roots>/    anything else load-bearing, declared in roots.yaml
├── .claude/
│   ├── CLAUDE.md              global MD          ┐
│   ├── USER.md                operator profile   ├ 200 lines each, max
│   ├── settings.json          statusLine · enabledPlugins · permissions
│   ├── statusline-command.sh
│   ├── skills/<name>/SKILL.md
│   ├── agents/<name>.md
│   └── projects/<slug>/memory/MEMORY.md          ┘
├── .config/tmux/              tmux.conf · boot · save · healthcheck · plugins/
├── .gmail-mcp/                OAuth for the email recap loop
├── .imsg-contacts             messaging aliases
├── .sop-vars                  the variables from §Variables
└── Library/LaunchAgents/      the loops, labeled com.$ORG.*
```

**The rule that keeps a build recoverable:** anything in
`~/Library/LaunchAgents` has a script in a git repo and a plist committed
beside it. A loop that exists only as a plist on one disk is an
unrecoverable artifact, and the drill in Phase 10 will say so.

---

## Verification — done is defined as

```bash
source ~/.sop-vars
sqlite3 ~/Library/Messages/chat.db "select count(*) from message;"  # FDA
claude --version && claude mcp list                                 # 6 ✔ Connected
launchctl list | grep "com.$ORG" | awk '$2!=0'                      # prints nothing
tailscale serve status                                              # surfaces mapped
tmux ls                                                             # standing sessions
cd ~/glitch-cat && npm run graph -- status && npm run drill         # non-zero counts, drill passes
fleetdeck doctor                                                    # all surfaces up
cd ~/app && npm test && npm run dev -- -H 0.0.0.0                   # app builds and serves
```

Then, from the **phone**: open the fleetdeck portal over the tailnet URL
and confirm a real padlock. Then send yourself a text from the machine.
If both work, the build is complete.

---

## Failure modes that cost a re-do

| Symptom | Cause | Fix |
|---|---|---|
| Message scanning returns nothing | Full Disk Access missing on the exact binary path | grant to `/opt/homebrew/bin/imsg`, not the wrapper |
| Agent can't send texts | Automation grant never approved | Privacy → Automation → Terminal → Messages |
| Playwright screenshots are black | Screen Recording not granted | Privacy → Screen Recording |
| Loops die overnight | machine sleeps, or background items blocked | `pmset -a sleep 0`; allow background items |
| Phone surface won't open | HTTP on tailnet, or bound to loopback | `tailscale serve --https`; bind `-H 0.0.0.0` |
| Status line prints `\033[0;32m` literally | colors written as plain strings | use `$'\033[0;32m'` |
| Status line blank | `jq` missing, or script not executable | `brew install jq`; `chmod +x` |
| `command not found: claude` | `~/.local/bin` off PATH | add to `.zshrc`, reopen terminal |
| `code not found` | shell command never installed | Cmd+Shift+P in VS Code |
| Vercel deploy blocked | a second GitHub identity | re-auth `gh` as `$GH_USER` |
| Migration "ran" but object missing | `db push` re-ran the ledger | apply individually; verify the object |
| Env vars missing in prod | stale `.vercel/project.json` | re-link; prefer platform secrets |
| Sessions gone after reboot | LaunchAgent not loaded | `launchctl` load the boot job |
| Board works here, breaks on the next machine | `machine` pinned in `config.json` | leave it empty; resolve from Tailscale |

---

## Build record

Consistency is a claim until it is recorded. Fill this per machine and
commit it beside the SOP.

```
Machine ________________  Operator ________________  Date ____________
ORG ____________  GH_USER ____________  BRAND ____________

Phase 0  permissions      [ ]      Phase 6  web stack        [ ]
Phase 1  accounts         [ ]      Phase 7  tmux             [ ]
Phase 2  editor           [ ]      Phase 8  loops            [ ]
Phase 3  homebrew         [ ]      Phase 9  fleetdeck        [ ]
Phase 4  tailscale        [ ]      Phase 10 graph + drill    [ ]
Phase 5  claude layer     [ ]      Phase 11 bonus repos      [ ]

Drill score at handover:  ______ reproducible / ______ unrecoverable
Deviations from this SOP (and why):
_________________________________________________________________
```

A deviation is not a failure. An **unrecorded** deviation is what makes
the next build different from this one.

---

## Appendix A — Reference implementation

The build this SOP was extracted from, as a worked example. These are
example values, not the procedure — substitute your own from §Variables.

| Variable | Reference value |
|---|---|
| `ORG` | `wideband` → LaunchAgents `com.wideband.*` |
| `GH_USER` | `widebandz` |
| `GRAPH_PACK` | `wideband` |
| Roots declared | the work repo, a reference codebase, a voice/middleware tree, `~/bin` |
| Standing sessions | `main · prod · UI · media · messages · texts · terminal · tunnel · GHL · pillars · private · question · sop` |
| Org-specific loops | deal-stage watcher, contract-signed watcher, follow-up chaser, three standup nudges, CRM reconciler |
| Drill score | 46 reproducible / 80 unrecoverable — the unrecoverable side dominated by LaunchAgent definitions and tailnet endpoints |

### Known gaps in the reference build

Recorded because a SOP that only describes the happy path is a brochure.

1. Global `~/.claude/CLAUDE.md` and `~/.claude/USER.md` do not exist yet.
2. Project `CLAUDE.md` is 337 lines and `AGENTS.md` is 730 — both over
   the 200-line cap in §5.5.
3. **No MD editing surface for a non-technical operator.** `fleetdeck
   edit` opens `services.json` in `$EDITOR`; it does not serve the five
   MD files. A docs tile on the portal that reads and writes those paths
   is a build item, not an install step.
4. Two bonus repo URLs unrecorded — watch-youtube, instagram-transcript.
5. One loop is loaded but last-exited non-zero — the exact case §Phase 8
   warns about.
6. `fleetdeck adopt` installs software and is correctly left off the
   tailnet.

---

## Out of scope

- The full LaunchAgent inventory of any given machine. This SOP installs
  the core set; the complete list is whatever the drill reports.
- Per-org business process — client onboarding, delivery, sales.
- Autonomous agent fleets running past a human merge gate.
