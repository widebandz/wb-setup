# Card and state schema

Two files per session, both under the memory directory (`tm-memory path`,
default `~/.config/agent-session-memory`, mode 0700, files 0600):

```
identity/<session>.md    stable
state/<session>.md       mutable
```

The frontmatter is a deliberately restricted format — `key: value`, or `key:`
followed by indented `- item` lines. No nesting. It parses without a YAML
dependency and stays readable to a human with no tooling.

`tm-memory check` rejects unknown fields, so a typo surfaces instead of being
silently ignored. Run it after every edit.

---

## identity/&lt;session&gt;.md

| Field | Required | Holds |
|---|---|---|
| `session` | yes | Canonical name. Must equal the filename stem and the tmux session name. |
| `role` | yes | `assigned` or `unassigned`. See the two regimes below. |
| `aliases` | | Other names this concern answers to. Must be unique fleet-wide and must not shadow another session's canonical name. |
| `concern` | if assigned | One line. The durable mission — what this session owns next month. |
| `root` | yes | Project root, written `~/…`. Warns if it does not exist. |
| `owner` | | Owning PM project or client. |
| `routing_in` | | Where work arrives from (`imsg-router`, a chat binding, a scheduled job). |
| `routing_out` | | Where results leave to. |
| `chat_binding` | | Bound chat identifier, e.g. `imsg:chat-21`. Never a phone number. |
| `tools` | | Tools and skills this session is allowed to use. |
| `approval` | | External side effects that require a human decision first. |
| `bootstrap` | | The command that starts this session's agent. Allowlisted. |
| `recovery_checks` | | Commands or assertions that prove the session is healthy after restore. |
| `updated` | yes | `YYYY-MM-DD`. |

### The two regimes

`role` decides how strictly the rest of the card is checked, because the two
states are different claims.

**`unassigned`** — nobody has decided what this session is for. `concern` is
optional, `UNVERIFIED` is allowed anywhere, and the body may stay as drafted.
This is the honest default: a session can do real work today without owning a
durable concern. It is *all state and no identity*.

**`assigned`** — this session owns a concern. `tm-memory check` then requires:

- a non-empty `concern`;
- a `## Responsibilities` section with at least one item;
- a `## Not this session` section with at least one item; and
- no `UNVERIFIED` anywhere in the body, the concern, or the owner.

That last rule is the whole gate. Promotion is a human edit — replace the
placeholders, then set `role: assigned` and run `tm-memory check`. There is no
`assign` command on purpose: flipping the field is trivial, and the work that
matters is deciding what goes in the two lists. A card that passes the assigned
check is one somebody actually thought about.

Demoting is the same edit in reverse and is not a failure. A concern that ended
should go back to `unassigned` or have its card deleted, rather than sit there
describing work nobody does.

Body sections:

```markdown
## Responsibilities

- What this session is answerable for.

## Not this session

- What it must refuse or hand off. This is the half that gets skipped and
  the half that prevents a recovered agent from wandering into other work.

## Recovery notes        (optional)

- Non-obvious things a returning agent needs: ordering, a service that must
  be up first, a state file it owns.
```

### `bootstrap` is allowlisted

The card is data an agent can edit, so the command it can cause to be typed
into a pane is constrained. The first word must be an approved launcher
(`claude`, `codex`, `dsh`; override with `TM_MEMORY_LAUNCHERS`), and the string
may not contain `;`, `|`, `&`, backticks, `$(`, `<`, `>`, or a newline.
Arguments are fine. Anything else is refused at `check` time, not at 3am
during a recovery.

### Worked examples

An unassigned session — sparse on purpose, and complete as it stands:

```markdown
---
session: scratch
role: unassigned
root: ~
bootstrap: claude
updated: 2026-09-23
---

## Responsibilities

- UNVERIFIED — no role assigned. Recovery treats this session as a fresh
  start rather than letting it inherit one.

## Not this session

- UNVERIFIED — record what this session must refuse once it has a role.
```

An assigned one:

```markdown
---
session: billing
role: assigned
aliases:
  - invoices
concern: the billing service — invoice generation, dunning, Stripe reconciliation
root: ~/work/billing
owner: Acme Co — retainer
routing_in:
  - imsg-router
routing_out:
  - operator summary after each reconciliation run
chat_binding:
tools:
  - repo edits, tests, local migrations
approval:
  - any Stripe call that moves money, including refunds
  - any migration against the production database
  - pushing to main or deploying
bootstrap: claude
recovery_checks:
  - git -C ~/work/billing status --short   (expect a clean tree)
  - the reconciliation job is not mid-run
updated: 2026-09-23
---

## Responsibilities

- Invoice generation and the dunning schedule.
- Reconciling Stripe events against local records, and reporting mismatches.

## Not this session

- Pricing and plan changes — those are a product decision, not a billing fix.
- Customer communication. Draft it, hand it over, do not send it.

## Recovery notes

- The reconciliation job holds a lock file; check it before running anything
  that writes, or two runs will double-post.
```

---

## state/&lt;session&gt;.md

Overwritten freely. This is the half that is allowed to be wrong after a week —
`tm-memory doctor` warns when it is older than 14 days and not `idle`.

| Field | Required | Holds |
|---|---|---|
| `session` | yes | Must match the identity card. |
| `status` | yes | `idle`, `working`, `blocked`, `awaiting-approval`, `handoff`, `retired`. |
| `assignment` | | The current piece of work, one line. |
| `next_safe_action` | | What a returning agent may do without asking. |
| `blockers` | | What is stopping progress, and who can unblock it. |
| `evidence` | | Last thing actually *verified*, with how it was verified. |
| `related` | | Files, tickets, PRs. Paths and IDs, not contents. |
| `updated` | yes | `YYYY-MM-DD`. |

```markdown
---
session: billing
status: blocked
assignment: reconcile the September Stripe export against local invoices
next_safe_action: re-run the read-only diff; do not write until the mismatch is explained
blockers:
  - 3 invoices have no matching Stripe event — needs a decision on which side is right
evidence:
  - reconcile --dry-run exited 0 with 3 mismatches listed (2026-09-23)
related:
  - ~/work/billing/scripts/reconcile.py
  - ticket BIL-412
updated: 2026-09-23
---
```

`evidence` is the field that earns its place: it distinguishes *ran and exited
0* from *looked right* from *a test failed before the fix and passes after*.
Write which one it was. A returning agent that cannot tell will redo the work
or, worse, trust it.
