# Migrating and auditing a fleet

## Where the truth already lives

Four sources, none of which is complete on its own:

| Source | Knows | Does not know |
|---|---|---|
| live `tmux` | which sessions exist right now, and what each pane is running | why any of them exists |
| `sessions.conf` (`tm-standard`) | the names and roots that should be recreated | anything about purpose or boundaries |
| `~/.imsg-routing.json` | a one-line description for the sessions the router can address | sessions nobody routes to |
| `identity/*.md` | mission, exclusions, approval limits, bootstrap | nothing, until someone writes it |

`tm-memory doctor` reconciles all four and reports the gaps. It changes nothing.

## Adopting an existing fleet

```bash
tm-memory adopt --dry-run     # what would be drafted
tm-memory adopt               # draft cards for uncovered live sessions
tm-memory adopt --session X   # one session
```

Every draft is `role: unassigned`. Which sessions hold a durable role is exactly
the judgment `adopt` must not make — so it records that nobody has decided,
which is true, and leaves promotion to a human edit.

For each live session with no card, `adopt` writes a draft from evidence only:

- **name** — the live session name.
- **root** — the directory most of its panes sit in (the rule `tm-standard`
  uses), not the session's nominal path.
- **concern** — the router's description if there is one, kept as evidence
  rather than as a decision; otherwise left empty. Never a guess from the
  directory or session name.
- **bootstrap** — inferred *only* from a pane already running an approved
  agent. A session at a bare shell gets an empty bootstrap, because there is no
  evidence of which agent belongs there.
- **owner**, **responsibilities**, **exclusions** — `UNVERIFIED`. These are
  judgment: two competent operators would answer differently, which is exactly
  why they cannot be derived.

A draft is not an identity. Until the `UNVERIFIED` markers are replaced, the
card records that nobody has decided, which is honest and useful; a fabricated
mission is neither.

`adopt` never overwrites an existing card and never deletes one. A card for a
session that is not running is not an error — a durable concern is allowed to
be offline, and deleting it is how a fleet quietly forgets a client.

## Reading the drift report

`tm-memory doctor` sections, and what each one actually means:

- **live sessions with no identity card** — the fleet has grown past what is
  written down. Run `adopt`, then fill in the judgment fields.
- **live sessions with no assigned role** — drafted but never decided on.
  `>>` sends off this machine (a chat binding, or a route that is not a
  `session:` handoff): that is a role on day one whatever its age, and the
  unassigned default of *ask before anything leaves this machine* is exactly
  backwards for it. `>>` is derived from `~/.imsg-chatbind.json`, so a session
  bound this morning is flagged this morning. `**` has been alive over a week
  and probably has a de facto concern. Neither is an error: a genuinely
  disposable session may stay unassigned forever.
- **handoff drift** — a `session:` route naming a session with no card. Cheap to
  fix and worth fixing: an unnamed counterpart is how two sessions start trading
  the same work.
- **cards with no live session** — offline concerns. `tm-standard apply`
  recreates the session; `tm-memory resume` gets an agent back into it.
- **sessions not running an agent** — recovery candidates. These are exactly the
  panes recovery refuses to type into.
- **routing entries with no live session** — the router can propose a target
  that cannot receive anything. Confirm before editing the router; a name may
  belong to a concern that is temporarily down, not a dead one.
- **live sessions the router cannot describe** — still addressable by name, but
  the interpreter has to guess when the operator does not name a target, and a
  guess has routed a message to the wrong place before.
- **no session standard** — `sessions.conf` is absent or empty. Nothing would be
  recreated on a new Mac. This is the failure the whole standard exists to
  prevent, and it is silent until a machine is rebuilt.

Exit code is the number of hard errors. Warnings (missing roots, stale state,
over-length cards) do not fail the report.

## Backup and rollback

```bash
tm-memory backup            # snapshot identity/ and state/ under backups/<stamp>/
tm-memory rollback          # restore the newest snapshot
tm-memory rollback <stamp>  # restore a named one
```

`rollback` snapshots the current state before replacing it, so restoring the
wrong snapshot is itself reversible. Back up before any bulk edit or before
adopting a large fleet for the first time.

## Order for a first migration

1. `tm-memory doctor` — record the starting picture.
2. `tm-memory backup` — cheap, and the only thing that makes step 4 safe.
3. `tm-memory adopt --dry-run`, then `tm-memory adopt`.
4. Promote the sessions that have real roles: fill in concern, responsibilities,
   exclusions and approval limits, then set `role: assigned`. Work from what the
   session has actually been doing — its root, its scrollback, its router
   description — never from the name alone. Leave the rest `unassigned`; that is
   a finished state, not a backlog.
5. `tm-memory check` until clean.
6. `tm-standard save` once the live fleet matches what should be recreated, so
   names and roots survive a new Mac and the cards survive with them.

Steps 4 and 6 are judgment. Do not batch them into one pass over 30 sessions
and expect the result to mean anything — a card written without knowing the
concern is a confident wrong answer that every future agent will inherit. The
long-lived, heavily used sessions are where promotion pays; start there, and let
the rest stay unassigned until they earn a name.
