# Repository context for software agents

Read [BUILD-MEMORY.md](BUILD-MEMORY.md) before changing the installer. It is
the durable engineering context for the product, including the client contract,
runtime architecture, security boundaries, release process, and proven E2E
behavior.

Preserve these invariants:

- The setup service binds only to loopback and every `/api/*` request requires
  the private token from the mode-`0600` connection file.
- UI callers may select only named, allowlisted actions; never add arbitrary
  shell execution to the API.
- Wideband Agent is the stable macOS permission principal. Do not move privacy
  checks back to Terminal, Python, or a package-manager path.
- The client must personally approve macOS privacy prompts, administrator
  password requests, account sign-ins, and two-factor challenges.
- Existing `~/.sop-vars`, client work, and curated configuration win over
  package defaults.
- A bare Mac cannot be assumed to have Git, Python, Homebrew, or modern Bash.
- `help.html` is generated from `TROUBLESHOOTING.md`; run
  `python3 render-help.py` after changing the source guide.

Before committing product changes, run:

```bash
./selftest.sh
git diff --check
```

For a release artifact, also run the packaging and audit checklist in
[BUILD-MEMORY.md](BUILD-MEMORY.md). Do not commit credentials, client identity,
local connection tokens, signing material, or VM passwords.
