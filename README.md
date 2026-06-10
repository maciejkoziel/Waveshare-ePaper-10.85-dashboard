# Waveshare-ePaper-10.85 Dashboard

> **Fork of [czuryk/Waveshare-ePaper-10.85-dashboard](https://github.com/czuryk/Waveshare-ePaper-10.85-dashboard)**  
> Extended to support the **4-color (G) variant** of the display, running on a **Raspberry Pi Zero W**.

A fully functional E-ink dashboard running on a Raspberry Pi. Designed for the Waveshare 10.85" e-Paper display, this project aggregates essential daily information and smart home status into a clean, minimalist interface.

## Key Features

* **4-color display support (G variant):** Fully ported to the `epd10in85g` driver — supports Red, Yellow, Black, and White on the Waveshare 10.85" e-Paper (G) panel (SKU 30411). Full refresh only, 180s minimum interval.
* **Antigravity usage data:** Displays usage data for Antigravity, showing the limit and reset time.
* **Claude Code usage data:** Displays usage data for Claude Code, showing the 5-hour limit, 7-day limit, and reset times.
* **Weather & Air Quality:** Real-time temperature, humidity, wind direction/speed, UV index, 4-hour forecast, and AQI using the Open-Meteo API.
* **Strava Integration:** Total and yearly activity statistics (distance and ride counts), including breakdowns for biking and hiking.
* **Bambu Lab 3D Printer:** Live monitoring of print status, completion percentage, remaining time, and current layer progress.
* **Roborock Vacuum:** Live battery level, current status, and cleaned area tracking during active cleaning.
* **Spotify:** Displays the currently playing track and artist via Last.fm.
* **Gmail:** Tracks the number of unread emails in your primary inbox.
* **System Fallbacks:** Automatically switches to System Load (CPU/RAM), Cryptocurrency prices (BTC/ETH), and Ping/Internet quality when hardware integrations are disabled.

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
sudo apt install python3-pip python3-pil python3-numpy git tmux -y
```

### 2. Python Dependencies

```bash
pip3 install --break-system-packages requests Pillow \
  google-api-python-client google-auth-httplib2 google-auth-oauthlib \
  aiomqtt roborock
```

> `bambulabs_api` is bundled in `lib/`. The G-display driver (`epd10in85g` + `epdconfig_g`) is also bundled in `lib/waveshare_epd/`.

### 3. Clone and Run

```bash
git clone https://github.com/maciejkoziel/Waveshare-ePaper-10.85-dashboard.git
cd Waveshare-ePaper-10.85-dashboard
tmux new -s dashboard
python3 main.py
# Detach: Ctrl+B, then D
```

---

## Configuration

All widget toggles and API configs are at the top of `main.py`:

```python
ENABLE_STRAVA = False
ENABLE_BAMBU = False
ENABLE_ROBOROCK = False
ENABLE_ANTIGRAVITY = False
ENABLE_CLAUDE = False
ENABLE_SPOTIFY = False

LOCATION_LAT = 44.8240855
LOCATION_LON = 20.4934273
```

### Claude Code
1. Run `main.py` from the terminal for the first time.
2. Copy the authorization URL, open it in a browser, authorize, and paste back the redirect URL containing `code=...`.
3. Tokens are saved to `claude_creds.json`.

### Strava
1. Create a Strava API Application and note your Client ID and Secret.
2. Run `main.py` — it will print an authorization URL.
3. Authorize in browser, paste the redirect URL back. Tokens saved to `strava_token.json`.

### Roborock
1. Set your account email in `ROBOROCK_CONF` in `main.py`.
2. Run the script — enter the 6-digit OTP sent to your email. Session saved to `roborock_session.pkl`.

### Bambu Lab 3D Printer
1. On the printer: **Settings -> Network** — note IP, Serial Number, and Access Code.
2. Update `PRINTER_CONF` in `main.py`.

### Spotify (via Last.fm)
1. Connect your Spotify account to Last.fm.
2. Generate a Last.fm API Key and update `LASTFM_CONF` in `main.py`.

### Gmail
1. In Google Cloud Console: create a project, enable Gmail API, create OAuth 2.0 credentials (Desktop App).
2. Download the credentials JSON and place it as `credentials.json` in the project directory.
3. On first run the script will prompt for OAuth authorization and save `token.json`.

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
