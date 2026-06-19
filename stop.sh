#!/usr/bin/env bash

tmux kill-session -t Obsidian

osascript <<'EOF'
tell application "Ghostty"
    close front window
end tell
EOF
