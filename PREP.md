# Before setup day

Send this to the client the day before. Everything here happens away from
the new Mac, on whatever device they already have.

The reason it exists: on setup day the machine downloads on its own and
needs nobody, but account sign-ins need a person and a phone for the
two-factor codes. Those are the hours. Doing them the day before is the
difference between a morning and an afternoon.

---

## Four answers we need

Reply with these and the machine is configured from them. They are the
only identity in the whole build.

| | What we need | Notes |
|---|---|---|
| 1 | **A short name for your company** | lowercase, one word, no spaces — `northside`, `apexhvac`. It labels the background jobs on your machine. |
| 2 | **Your GitHub username** | from step 4 below. Pick it deliberately; changing it later breaks deployments. |
| 3 | **The email for your code commits** | usually your work address |
| 4 | **The phone number for daily briefs** | where the machine texts you its morning summary |

---

## Six accounts to create

In this order. Email is first because every other account sends its
verification there — a machine that cannot receive a code stalls, and it
stalls in a way that is hard to diagnose in the moment.

**1. Email — confirm access**
Not a new account, just a check: sign in, send yourself a message, confirm
it arrives. Have the password written down somewhere you can reach it.
Roughly half the delays on setup day are a forgotten mail password.

**2. Apple ID** — appleid.apple.com
You likely have one. Confirm you can sign in and that you can receive its
verification codes. This is what lets the machine text you.

**3. Anthropic** — claude.ai
Create the account and start a **Pro or Max** subscription. This one
matters most for timing: it is the last thing standing between a new
machine and a working one, so having it ready is the single biggest
saving on the day.

**4. GitHub** — github.com
Create the account. **The username you choose here becomes permanent** for
this machine — it signs your work and authorizes deployments, and a second
account added later is the most common cause of a deployment that refuses
to run. One account, chosen on purpose.

**5. Tailscale** — tailscale.com
Sign in with the GitHub account from step 4. This is the private network
that lets you reach the machine from your phone.

**6. Vercel and Supabase** — vercel.com, supabase.com
Both: sign in with GitHub. Do these after step 4 or they create separate
identities you will have to reconcile.

**Two-factor:** turn it on where offered, and keep your phone nearby. It
is worth the two minutes now rather than during setup.

---

## On the day, have ready

- The new Mac, **plugged into power** — it will be downloading for a while
- Your **wifi password**
- Your **phone**, for verification codes
- About **three hours**, though most of it is unattended
- An **administrator account** on the Mac — the one you create when you
  first turn it on

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
- **The Mac is managed by an IT department** or enrolled in device
  management. Managed machines often block the permissions this setup
  needs, and that is better to find out now than three hours in.
- **You are not an administrator** on the machine. Most of setup requires
  it.
- **You already have any of the six accounts** above. We will use them
  rather than create duplicates.

---

## What happens on the day

You will spend most of your time signing in and clicking through
permission dialogs while the machine downloads in the background. Neither
of us waits on the other — that is deliberate, and it is why this sheet
exists.

By the end, the machine texts you a daily brief, you can reach it from
your phone, and it can build and deploy your work.
