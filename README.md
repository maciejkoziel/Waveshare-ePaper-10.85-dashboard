# Waveshare-ePaper-10.85 Dashboard

> **Fork of [czuryk/Waveshare-ePaper-10.85-dashboard](https://github.com/czuryk/Waveshare-ePaper-10.85-dashboard)**  
> Extended to support the **4-color (G) variant** of the display, running on a **Raspberry Pi Zero W**.

A fully functional E-ink dashboard running on a Raspberry Pi. Designed for the Waveshare 10.85" e-Paper display, this project aggregates essential daily information and smart home status into a clean, minimalist interface.

## Key Features

* **4-color display support (G variant):** Fully ported to the `epd10in85g` driver — supports Red, Yellow, Black, and White on the Waveshare 10.85" e-Paper (G) panel (SKU 30411). Full refresh only, 180s minimum interval.
* **Weather:** Real-time temperature, humidity, wind direction/speed, UV index, 5/7-day forecast, sunrise/sunset times, and moon phase using the Open-Meteo API.
* **Google Calendar:** Upcoming events from your primary Google Calendar.
* **Google Tasks:** Active tasks from your Google Tasks lists.
* **Strava Integration:** Total and yearly activity statistics (distance and ride counts), including breakdowns for biking and hiking.
* **Bambu Lab 3D Printer:** Live monitoring of print status, completion percentage, remaining time, and current layer progress.
* **Roborock Vacuum:** Live battery level, current status, and cleaned area tracking during active cleaning.
* **Spotify:** Displays the currently playing track and artist via Last.fm.
* **Antigravity usage data:** Displays usage data for Antigravity, showing the limit and reset time.
* **Claude Code usage data:** Displays usage data for Claude Code, showing the 5-hour limit, 7-day limit, and reset times.
* **Custom message widget:** A dedicated right column that displays up to 3 messages sent over the network via a built-in HTTP server. New messages are added to a queue; the oldest is dropped when the queue is full. Supports header, body, e-ink colors, border, and per-message TTL. Any device on the network can push a message with a single `curl` command, and DELETE only removes messages sent from that device's IP.

---

## Hardware

| Component | Details |
|-----------|---------|
| Board | Raspberry Pi Zero W Rev 1.1 |
| Display panel | Waveshare 10.85" e-Paper (G) — SKU 30411 — 4-color |
| Display HAT | Waveshare 10.85" e-Paper HAT+ (BW HAT, physically compatible with G panel) |
| Resolution | 1360 × 480 |
| Colors | Red, Yellow, Black, White |

> **Note on display variants:** The original repo targets the BW (black/white) HAT+. This fork uses the 4-color G panel with a custom driver (`epd10in85g` + `epdconfig_g`). The G panel does **not** support partial refresh — every update is a full 21-second refresh.

---

## Prerequisites & Installation

### 1. System Setup

Enable SPI on your Raspberry Pi:
```bash
sudo raspi-config
# Interfacing Options -> SPI -> Enable
```

Install system dependencies:
```bash
sudo apt update
sudo apt install python3-pip python3-pil python3-numpy git -y
```

### 2. Python Dependencies

```bash
pip3 install --break-system-packages requests Pillow \
  google-api-python-client google-auth-httplib2 google-auth-oauthlib \
  aiomqtt roborock
```

> `bambulabs_api` is bundled in `lib/`. The G-display driver (`epd10in85g` + `epdconfig_g`) is also bundled in `lib/waveshare_epd/`.

### 3. Clone and Install

```bash
git clone https://github.com/maciejkoziel/Waveshare-ePaper-10.85-dashboard.git
cd Waveshare-ePaper-10.85-dashboard
bash install-service.sh
```

This installs and starts two systemd services that run on boot and restart automatically on failure:
- `dashboard.service` — the main display process (`main.py`)
- `dashboard-message.service` — the message HTTP server (`message_server.py`)

**Useful commands:**
```bash
systemctl status dashboard dashboard-message    # check status
journalctl -u dashboard -f                      # follow dashboard logs
journalctl -u dashboard-message -f              # follow message server logs
sudo systemctl restart dashboard dashboard-message
sudo systemctl stop dashboard dashboard-message
```

---

## Configuration

All config lives in `settings_local.toml` in the project directory (not committed to the repo). Create it before starting the service:

```toml
[widgets]
enable_strava      = false
enable_bambu       = false
enable_roborock    = false
enable_antigravity = false
enable_tasks       = false
enable_claude      = false
enable_spotify     = false
enable_calendar    = false

[location]
lat = 44.8240855
lon = 20.4934273

[printer]
ip          = "192.168.x.x"
serial      = "YOUR_SERIAL"
access_code = "YOUR_CODE"

[roborock]
email = "your@email.com"

[lastfm]
api_key  = "YOUR_KEY"
username = "YOUR_USERNAME"

[weather]
forecast_days = 5   # 5 or 7

[display]
language = "en"     # "en" or "pl"

[message_server]
port = 5000         # port for the custom message HTTP server
```

### Google (Gmail / Calendar / Tasks)
These three share a single OAuth flow:
1. In Google Cloud Console: create a project, enable the Gmail API, Google Calendar API, and Google Tasks API.
2. Create OAuth 2.0 credentials (Desktop App) and download the JSON as `credentials.json` in the project directory.
3. **Before starting the service**, run `python3 main.py` once in a terminal — it will print an authorization URL.
4. Open the URL in a browser, authorize, and paste the redirect URL back. Tokens saved to `token.json`.

### Claude Code
1. **Before starting the service**, run `python3 main.py` once in a terminal.
2. Copy the authorization URL, authorize in a browser, and paste back the redirect URL containing `code=...`.
3. Tokens are saved to `claude_creds.json`.

### Strava
1. Create a Strava API Application and note your Client ID and Secret.
2. **Before starting the service**, run `python3 main.py` — it will print an authorization URL.
3. Authorize in browser, paste the redirect URL back. Tokens saved to `strava_token.json`.

### Roborock
1. Set your account email under `[roborock]` in `settings_local.toml`.
2. **Before starting the service**, run `python3 main.py` — enter the 6-digit OTP sent to your email. Session saved to `roborock_session.pkl`.

### Bambu Lab 3D Printer
1. On the printer: **Settings -> Network** — note IP, Serial Number, and Access Code.
2. Set them under `[printer]` in `settings_local.toml`.

### Spotify (via Last.fm)
1. Connect your Spotify account to Last.fm.
2. Generate a Last.fm API Key and set `api_key` and `username` under `[lastfm]` in `settings_local.toml`.

### Custom Message Widget
The right column (col3) is driven by `message_server.py`, a lightweight HTTP server installed alongside the dashboard by `install-service.sh`.

Col3 displays up to **3 messages** stacked vertically, each in its own colored box. Messages are stored in a queue — when a 4th message arrives, the oldest is dropped. Each box shows a header, up to 2 lines of body text, and a "X ago" timestamp. Empty slots are invisible.

Send a message from any device on the network:
```bash
curl -X POST http://<pi-ip>:5000/message \
  -H 'Content-Type: application/json' \
  -d '{
    "header": "ALERT",
    "body": "Dinner is ready",
    "text_color": "black",
    "bg_color": "yellow",
    "border_color": "red",
    "ttl": 3600
  }'

# Clear messages sent from this device
curl -X DELETE http://<pi-ip>:5000/message

# View current queue
curl http://<pi-ip>:5000/message
```

Colors: `black`, `white`, `red`, `yellow`. `ttl: 0` = persistent; each message expires independently. DELETE only removes messages sent from the caller's IP — messages from other devices are unaffected. The server automatically signals the dashboard to refresh after each change.

---

## Architecture

- **Multi-threaded data fetching:** each service runs in its own background thread at its own interval
- **Thread-safe data store:** renderer reads a snapshot under a lock, never blocks fetch threads
- **Full refresh only (G variant):** ~21s per update, 180s minimum cycle enforced by sleep
- **Hardware watchdog:** `signal.alarm(90)` triggers self-restart on display hang
- **Periodic deep clean:** every 600 cycles, Init + Clear + display to eliminate ghosting

---

## G Display Notes

The 4-color G variant differs significantly from the BW version:

| | BW version | G (color) version |
|-|-----------|------------------|
| Colors | Black, White | Red, Yellow, Black, White |
| Full refresh | ~3.5s | **~21s** |
| Partial refresh | ✅ | ❌ Not available |
| Image mode | `"1"` (1bpp) | `"RGB"` → 4-color quantized |
| Driver | `epd10in85.py` | `epd10in85g.py` |
| Min refresh interval | 60s | **180s** |

Known hardware quirks fixed in this fork:
- Skip `0x00` (Panel Setting) in Init — causes power-on hang on BW HAT + G panel combo
- `Clear()` uses `width/4` bytes/row (not `width/2`) — official driver sends 2× too much data
- SPI writes always go through `_spi_m` fd only — writing to both fds garbles the Init sequence on the shared bus

---

## 3D Printed Case

Case STL files: [MakerWorld](https://makerworld.com/en/models/2322517-epaper-dashboard-waveshare-10-85)

## Video Assembly Guide

[![Assembly guide](https://img.youtube.com/vi/H964RpaJvu0/0.jpg)](https://youtu.be/H964RpaJvu0)
