# Claude Code Status Line Setup

Give this file to Claude Code (e.g. "read this file and set up my status line") and it
will recreate the exact status line configured on the original machine. It shows:
`path (git branch) | model | ctx:XX.X% | ses:XX% | wk:XX% | $cost`

## Instructions for Claude

1. Write the script below to `~/.claude/statusline-command.sh` (create the `~/.claude`
   directory first if it doesn't exist).
2. Make it executable: `chmod +x ~/.claude/statusline-command.sh`.
3. Open `~/.claude/settings.json` (create it as `{}` if missing) and merge in the
   `statusLine` key shown below — do NOT overwrite any other existing keys in that file.
4. Confirm to the user that the status line is set up and will take effect in a new
   Claude Code session.

## `~/.claude/settings.json` — merge this key in

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash ~/.claude/statusline-command.sh"
  }
}
```

## `~/.claude/statusline-command.sh` — full script content

```bash
#!/usr/bin/env bash
# Claude Code statusLine script (no jq/node/python dependency — parsed with grep -P)
input=$(cat)

get() {
  grep -oP "$1" <<< "$input" | head -1
}

# --- Location + git branch ---
cwd_raw=$(get '"workspace":\{[^}]*"current_dir":"\K[^"]*')
[ -z "$cwd_raw" ] && cwd_raw=$(get '"cwd":"\K[^"]*')
[ -z "$cwd_raw" ] && cwd_raw="$PWD"

cwd=$(printf '%s' "$cwd_raw" | sed 's|[\\][\\]|/|g; s|[\\]|/|g')

branch=""
if git --no-optional-locks -C "$cwd" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  branch=$(git --no-optional-locks -C "$cwd" branch --show-current 2>/dev/null)
  [ -z "$branch" ] && branch=$(git --no-optional-locks -C "$cwd" rev-parse --short HEAD 2>/dev/null)
fi

loc="$cwd"
[ -n "$branch" ] && loc="$cwd ($branch)"

# --- Model ---
model=$(get '"model":\{[^}]*"display_name":"\K[^"]*')
[ -z "$model" ] && model="Claude"

# --- Context window usage ---
ctx_used=$(get '"context_window":\{[^}]*"used_percentage":\K[0-9.]+')

# --- Rate limits (Claude.ai subscribers only) ---
five_hour=$(get '"five_hour":\{[^}]*"used_percentage":\K[0-9.]+')
seven_day=$(get '"seven_day":\{[^}]*"used_percentage":\K[0-9.]+')

# --- Session cost (provided directly by Claude Code, client-side estimate) ---
cost=$(get '"cost":\{[^}]*"total_cost_usd":\K[0-9.]+')
[ -z "$cost" ] && cost="0"
cost_fmt=$(printf '%.2f' "$cost")

# --- Assemble (dimmed, since the terminal renders the status line dim) ---
DIM='\033[2m'
RESET='\033[0m'

parts=("$loc" "$model")
[ -n "$ctx_used" ] && parts+=("ctx:$(printf '%.1f' "$ctx_used")%")
[ -n "$five_hour" ] && parts+=("ses:$(printf '%.0f' "$five_hour")%")
[ -n "$seven_day" ] && parts+=("wk:$(printf '%.0f' "$seven_day")%")
parts+=("\$${cost_fmt}")

out=""
for p in "${parts[@]}"; do
  if [ -z "$out" ]; then
    out="$p"
  else
    out="$out | $p"
  fi
done

printf "${DIM}%s${RESET}" "$out"
```
