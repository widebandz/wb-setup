#!/usr/bin/env bash
# Claude Code status line: directory | model | context window usage

input=$(cat)

cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // ""')
model=$(echo "$input" | jq -r '.model.display_name // ""')
used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
remaining=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')

# Shorten home directory
home="$HOME"
short_cwd="${cwd/#$home/~}"

# Build context segment
ctx_segment=""
if [ -n "$used" ]; then
  used_int=$(printf '%.0f' "$used")
  remaining_int=$(printf '%.0f' "$remaining")

  # Color based on usage: green -> yellow -> red.
  # $'...' so these hold real ESC bytes: printf only expands \033 in its format
  # string, and this segment reaches it as a %s argument — written "\033[0;32m"
  # it printed literally.
  if [ "$used_int" -ge 80 ]; then
    color=$'\033[0;31m'   # red
  elif [ "$used_int" -ge 50 ]; then
    color=$'\033[0;33m'   # yellow
  else
    color=$'\033[0;32m'   # green
  fi
  reset=$'\033[0m'
  ctx_segment=" | ${color}ctx: ${used_int}% used / ${remaining_int}% left${reset}"
fi

printf "\033[0;36m%s\033[0m | \033[0;35m%s\033[0m%s" "$short_cwd" "$model" "$ctx_segment"
