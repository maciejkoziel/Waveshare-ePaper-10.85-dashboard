# Project Commit Command

This project's live code runs on the Pi at `maciej@192.168.12.175:/home/maciej/Waveshare-ePaper-10.85-dashboard/`.
The Pi repo is the source of truth for driver files not tracked locally (e.g. `epd10in85g.py`, `epdconfig_g.py`).

## Steps

1. SSH to the Pi and run `git status` to see what's changed.
2. Run `git diff` on the Pi for any modified tracked files to understand the changes.
3. Stage only relevant source files — exclude `__pycache__/`, `*.pyc`, `*.bak`, `dashboard.log`, `*.pkl`, `*.json` credential/cache files, and `venv/`.
   Use explicit `git add <file>` for each file, never `git add .` or `git add -A`.
4. If nothing meaningful is staged after filtering, report that and stop.
5. Analyze the diff and write a conventional commit message with emoji (same format as the global /commit command).
6. Commit on the Pi with that message.
7. Push from the Pi with `git push`.

## Pi repo path

```
/home/maciej/Waveshare-ePaper-10.85-dashboard/
```

## Files to never stage

- `**/__pycache__/`
- `**/*.pyc`
- `*.bak`
- `dashboard.log`
- `roborock_session.pkl`
- `roborock_stats.json`
- `strava_token.json`
- `token.json`
- `credentials.json`
- `usage.json`
- `limits.json`
- `venv/`
