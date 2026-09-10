# Brewfile — the core CLIs from SOP Phase 3.
#
# Declarative on purpose: `brew bundle` is idempotent and reports what it did,
# where a list of `brew install` lines re-resolves every formula on every run
# and gives you no way to diff intent against reality (`brew bundle check`).

# ── required ────────────────────────────────────────────────────────────────
brew "node"       # Next.js, the Vercel CLI, Playwright
brew "git"
brew "gh"         # auth as $GH_USER; the identity the whole build depends on
brew "tmux"
brew "jq"         # the status line parses its JSON input with this
brew "python"     # the vendored loops are stdlib-only python3
brew "sqlite"     # reading the Messages DB in verify.sh
brew "ffmpeg"     # media encode for capture and render
brew "ttyd"       # fleetdeck's chat surface shells out to this

# ── stack ───────────────────────────────────────────────────────────────────
brew "supabase/tap/supabase"

# ── optional, referenced by tmux keybinds ───────────────────────────────────
# Each of these has a fallback in tmux.conf, so a machine without them still
# gets working keybinds — they just print a line saying what is missing.
brew "lazygit"

# ── casks ───────────────────────────────────────────────────────────────────
# Tailscale is deliberately NOT here. The Mac App Store build does not ship the
# CLI, and `brew install --cask tailscale` has pointed at both builds over time.
# SOP Phase 4 installs the standalone app from tailscale.com and links the CLI
# explicitly, because `tailscale serve` is load-bearing for every phone surface.
cask "visual-studio-code"
