#!/usr/bin/env bash

if tmux has-session -t Obsidian 2>/dev/null; then
    tmux attach-session -t Obsidian
else
    tmuxinator start obsidian
fi
