#!/bin/sh
set -eu
project='/Users/zakharkorchagin/Documents/Codex/2026-11-10/https-spectral-tech-junior-ai-data'
label='com.spectral.salary-dashboard-refresh'
plist="$project/work/api_connector/$label.plist"
target="$HOME/Library/LaunchAgents/$label.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$project/work/api_connector/logs"
cp "$plist" "$target"
launchctl bootout "gui/$(id -u)" "$target" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$target"
printf 'Installed weekly refresh for Mondays at 09:00 local time.\n'
