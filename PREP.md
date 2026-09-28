# Before setup day

Send this to the client the day before. Everything here happens away from
the new Mac, on whatever device they already have.

The first milestone is a real text exchange with your new agent. You handle
the account sign-ins and macOS approvals yourself; Wideband handles the
repeatable installation. Preparing the accounts below avoids waiting for
verification codes on setup day.

---

## What you will receive

Wideband sends one disk image containing the branded **Wideband Setup** app,
`READ ME FIRST.txt`, and a Privacy & Security shortcut. You do not need a
separate localhost link or technical checklist.

Open the app and follow one action at a time. It saves progress and installs a
resumable copy in your user Applications folder. If you close it or restart the
Mac, reopen **Applications → Wideband Setup**.

An unsigned pilot requires a one-time **Privacy & Security → Open Anyway**
approval. A signed and notarized production build opens normally. On a brand
new Mac, Terminal may appear behind the branded guide for Homebrew's one
administrator-password prompt. Your typing is intentionally invisible in that
prompt; Wideband never receives the password.

The guide labels every step as **Wideband installs**, **You approve**, or **We
customize together**. macOS permission checks update automatically after you
approve them.

The first time Wideband Setup opens, it also asks whether it may check
`https://os.wideband.ai/version` when the app starts. That optional request
sends no setup answers or machine identifiers. You can decline and use the
manual **Check for Updates…** menu item later.

---

## Before your first text

- Have your **personal iPhone** and its phone number ready. The generic setup
  asks for that number in one private macOS dialog, including country code.
  Wideband binds replies only to the exact one-to-one chat from this phone.
- Decide on an **OS display name**, a **head-agent name**, and a first goal:
  Research, Build a website, or Proposal (advanced). You can choose and edit
  these in Wideband Setup; the OS display name does not rename the Mac.
- Have an **administrator account on an Apple silicon Mac running macOS 14 or
  newer**, plus power and Wi-Fi. The iMessage transport cannot run on macOS 13.

---

## Accounts needed for the first text

**Separate agent Apple Account** — account.apple.com
Create or choose an Apple Account for the agent Mac that is different from the
Apple Account on your personal iPhone. Confirm you can sign in and receive its
verification codes. This separate identity lets the agent text you as a distinct
sender. Keep its password and verification codes in your own password manager;
Wideband Setup never asks for them.

**Claude Code access** — claude.ai
Have the account you want the head agent to use ready for Claude Code sign-in.
Wideband opens Claude's own sign-in flow on the Mac; it does not collect your
password or verification codes. Confirm the account can run Claude Code before
you expect the first agent reply.

Keep access to the email address and phone that receive these accounts'
verification codes. Sign-ins and two-factor challenges stay with you.

### Later operator details and accounts

These are useful for deployment and the phone board, but they do not block the
first working iMessage conversation:

| Detail | When needed |
|---|---|
| **Company short name** | Later full operator build; a lowercase slug such as `northside` labels its background jobs. |
| **GitHub username and code-commit email** | When the agent starts working with repositories and deployments. Choose the intended GitHub identity deliberately. |
| **Work repository and graph pack** | When connecting the agent to the work you want it to do. |
| **Tailscale account** | When publishing Fleetdeck's private HTTPS phone link. Sign in on the Mac and phone. On the Mac, enable Tailscale's Start on Login setting, restart, and confirm it reconnects after you sign in. Then test the private HTTPS link on the phone. |
| **Vercel, Supabase, and other developer accounts** | Only when the chosen first project needs them. |

---

## On the day, have ready

- The new Mac, **plugged into power** — it will be downloading for a while
- Your **wifi password**
- Your **personal iPhone**, for account verification and the real text test
- The **separate agent Apple Account** and **Claude Code access** above
- An **administrator account** on the Mac — the one you create when you first
  turn it on

---

## What we will never ask for

**Your passwords.** You sign in yourself, on your own machine, every time.
We watch the screen and help when something is confusing, and that is the
whole of it. If anyone asks you to send a password for this setup, that is
not us.

---

## Tell us beforehand if

- **You are moving from an old Mac** and plan to use Migration Assistant.
  This changes the order of the day — a migrated machine arrives with old
  settings that can quietly conflict with the new ones, and we would
  rather plan for it than discover it.
- **This Mac was recently upgraded from an older major macOS release.** Apple
  Command Line Tools can need updating, reinstalling, or reselecting even when
  an old Homebrew folder remains. Wideband will inspect both separately before
  making changes; do not run a broad ownership command from an error message
  alone.
- **The network is filtered** — a corporate, school, or guest network, or
  one with content filtering on the router. Some of these block the sites the
  setup downloads from, and it fails in a way that looks like our mistake
  rather than the network. If you can, have a phone hotspot available as a
  backup on the day.
- **The Mac is managed by an IT department** or enrolled in device
  management. Managed machines often block the permissions this setup
  needs, and that is better to find out now than three hours in.
- **You are not an administrator** on the machine. Most of setup requires
  it.
- **You already have an agent Apple Account or Claude Code access.** We can
  use the intended accounts rather than create duplicates, provided the agent
  Apple Account differs from the one on your personal iPhone.

---

## What happens on the day

Wideband Setup performs the repeatable machine work while you sign the separate
agent Apple Account into Messages and approve Full Disk Access for the exact app
named **Wideband Agent**. Send a fresh iMessage from your personal phone to the
agent account, then confirm a real agent reply arrives in that same chat.
Accessibility, Screen Recording, Messages Automation, Remote Login, and Screen
Sharing are guided later if your work or support requires them.

The readiness screen distinguishes software that the Mac verified from account
or real-world outcomes that only you can confirm. Neither of us waits on the
other — that is deliberate, and it is why this sheet exists.

After the first reply, Wideband prepares your chosen first job and the local
Fleetdeck phone view. A private HTTPS link, iPhone home-screen shortcut,
deployment accounts, and scheduled briefs have their own later checks. Once
you open the Fleetdeck board on your phone and confirm it works, Wideband
queues two setup texts in your verified chat. They keep the board links,
Claude and tmux commands, and Tailscale and Termius app links at hand.
