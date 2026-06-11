# Waveshare ePaper 10.85" Dashboard

E-ink dashboard running on a Raspberry Pi Zero W. Aggregates weather, smart home, fitness, and usage data into a clean display.

## SSH Access

Pi is always available at `maciej@192.168.12.175`. SSH in directly without asking the user — passwordless key auth is configured. Use this whenever you need to run, test, or inspect anything on the Pi.

## Hardware

| Component | Details |
|-----------|---------|
| Board | Raspberry Pi Zero W Rev 1.1 (BCM2835, armv6l) |
| RAM | 448 MB ARM / 64 MB GPU |
| OS | Raspbian Linux 6.12.75+rpt-rpi-v6 |
| Python | 3.13.5 |
| **Display panel** | **Waveshare 10.85" e-Paper (G) — SKU 30411 — 4-color raw panel** |
| **Display HAT** | **Waveshare 10.85" e-Paper HAT+ — BW HAT, physically compatible with G panel** |
| Resolution | 1360 × 480 |
| Colors | Red, Yellow, Black, White |
| SPI devices | `/dev/spidev0.0`, `/dev/spidev0.1` |
| Hostname | `raspberry-dashboard01` |
| IP | `192.168.12.175` |
| SSH user | `maciej` |

SPI is enabled in `/boot/firmware/config.txt` (`dtparam=spi=on`). I2C is disabled.

---

## Display — 10.85inch e-Paper HAT+ (G)

**Product page:** https://www.waveshare.com/10.85inch-e-paper-hat-plus-g.htm  
**Waveshare demo code:** https://github.com/waveshareteam/e-Paper/tree/master/E-paper_Separate_Program/10.85inch_e-Paper_G

### Specifications

| Property | Value |
|----------|-------|
| Colors | **Red / Yellow / Black / White** |
| Resolution | 1360 × 480 |
| Dot pitch | 0.191 × 0.191 mm |
| Display size | 259.76 × 91.68 mm |
| Full refresh time | **21 seconds** |
| Fast refresh time | **21 seconds** (same as full — no fast mode on G panel) |
| Partial refresh | **Not supported** |
| Recommended refresh interval | ≥ 180 seconds |
| Operating voltage | 3.3V (raw) / 3.3V–5V (with HAT) |
| Interface | SPI (CPOL=0, CPHA=0, SPI mode 0) |
| Standby current | < 0.01 µA |

### ⚠ Critical: Differences from BW version

The (G) color version is **fundamentally different** from the black/white `epd10in85`:

| | B/W version | (G) color version |
|-|------------|-------------------|
| Colors | Black, White | Red, Yellow, Black, White |
| Full refresh | 3.5s | **21s** |
| Partial refresh | ✅ 0.6s | ❌ **Not available** |
| Image mode | `"1"` (1bpp) | `"RGB"` → quantized to 4-color palette |
| Image size | `(width, height)` = `(1360, 480)` | `(width*2, height)` = `(1360, 480)` (dual-IC) |
| Driver file | `epd10in85.py` | `epd10in85g.py` |
| Init method | `epd.init()` | `epd.Init()` |
| Display method | `epd.display(buf)` + `epd.display_Partial(...)` | `epd.display(buf)` only |

**The G driver (`epd10in85g.py` + `epdconfig_g.py`) is fully in use. The BW driver (`epd10in85.py`) is unused.**

### GPIO Pin Wiring (Pi 40-pin header)

| Signal | BCM GPIO | Board Pin | Function |
|--------|----------|-----------|----------|
| VCC | — | 3.3V | Power |
| GND | — | GND | Ground |
| DIN | GPIO10 | 19 | SPI MOSI |
| CLK | GPIO11 | 23 | SPI SCLK |
| CS_M | GPIO8 | 24 | Master IC chip select (CE0) |
| CS_S | GPIO7 | 26 | Slave IC chip select (CE1) |
| DC | GPIO25 | 22 | Data/Command |
| RST | GPIO17 | 11 | Reset |
| BUSY | GPIO24 | 18 | Busy status (HIGH = busy) |
| PWR | GPIO18 | 12 | Power control |

> **Note:** GPIO7 and GPIO8 are kernel-owned SPI CS pins (`dtparam=spi=on`). The driver controls them via the `DEV_Config.so` C library through `spidev`, not via `gpiozero`/`lgpio` directly.

### Dual-IC Architecture

The display uses two driver ICs sharing all control pins except CS:
- **M (master) area:** left half — selected via CS_M (GPIO8/CE0)
- **S (slave) area:** right half — selected via CS_S (GPIO7/CE1)
- All commands/data are sent sequentially to M then S
- Image data must be split horizontally: M gets columns 0–679, S gets columns 680–1359

### Driver API (`epd10in85g.py`)

```python
import epd10in85g

EPD_WIDTH  = 680   # per IC (1360 // 2)
EPD_HEIGHT = 480

epd = epd10in85g.EPD()
epd.width   # 680
epd.height  # 480

# Color constants (RGB tuples for PIL)
epd.BLACK  = 0x000000   # (0,   0,   0)
epd.WHITE  = 0xffffff   # (255, 255, 255)
epd.YELLOW = 0x00ffff   # (255, 255, 0)  — note: BGR in the constant
epd.RED    = 0x0000ff   # (255, 0,   0)  — note: BGR in the constant
```

**Use PIL color names directly when drawing:**
```python
draw.rectangle([...], fill="red")
draw.text(..., fill="black")
draw.text(..., fill=(255, 255, 0))   # yellow
```

**Lifecycle:**
```python
epd.Init()              # initialize hardware (sends init sequence, waits for BUSY)
epd.Clear()             # fill white, trigger full refresh (~21s)
buf = epd.getbuffer(image)   # convert RGB image → 2bpp packed buffer
epd.display(buf)        # send buffer to both ICs, trigger full refresh (~21s)
epd.PowerOff()          # park panel rail — keeps GPIO/SPI claimed, avoids flicker on next wake
epd.PowerOn()           # wake panel (assumes Init already done — no re-init needed)
epd.sleep()             # full deep sleep (POWER_OFF + DEEP_SLEEP + module_exit)
```

**Production cycle (main.py):** `PowerOn()` → `display()` → `PowerOff()` every refresh. `sleep()` + `Init()` + `Clear()` only once every 600 cycles (~30h) to clear ghosting. This avoids the extra flash that a full sleep/wake would cause each cycle.

**After `sleep()`, must call `Init()` again before next `display()`.**

**`getbuffer(image)` details:**
- Input: PIL `Image` in `RGB` mode, size `(1360, 480)` or `(480, 1360)` (rotated automatically)
- Quantizes to 4-color palette: `{black=(0,0,0), white=(255,255,255), yellow=(255,255,0), red=(255,0,0)}`
- Output: list of bytes, 2 bits per pixel, 4 pixels packed per byte
- Palette index encoding: `00=black`, `01=white`, `10=yellow`, `11=red`

**Creating images:**
```python
from PIL import Image, ImageDraw

# Full canvas — must be 1360×480 for the G display
image = Image.new("RGB", (1360, 480), "white")
draw = ImageDraw.Draw(image)
draw.rectangle([(0, 0), (100, 100)], fill="red")
draw.text((10, 10), "Hello", font=font, fill="black")

buf = epd.getbuffer(image)
epd.display(buf)   # takes ~21 seconds
```

### Refresh Rules

1. **No partial refresh** — every update is a full refresh (21s)
2. **Minimum interval: 180 seconds** between refreshes (Waveshare recommendation)
3. **Always put display to sleep** when not refreshing — leaving it in high-voltage state causes irreversible damage
4. **After waking from sleep:** call `Init()` + `Clear()` before `display()` to avoid residual images
5. **Low temperature:** if below 0°C, let it stabilize at 25°C for 6 hours before refreshing

### Precautions

- Do not bend the FPC cable vertically or repeatedly
- Display is fragile — no dropping, hard pressing, or collisions
- Indoor use only — direct sunlight degrades the electrophoretic particles irreversibly
- Operating temperature: 0–50°C; Storage: below 30°C

---

## Repository

| | Path |
|-|------|
| Remote | `https://github.com/maciejkoziel/Waveshare-ePaper-10.85-dashboard.git` |
| Mac (local) | `/Users/mako/repos/Waveshare-ePaper-10.85-dashboard/` |
| Pi (production) | `/home/maciej/Waveshare-ePaper-10.85-dashboard/` |

**The Pi path is the live production copy.** The script runs from `/home/maciej/Waveshare-ePaper-10.85-dashboard/main.py`.

## Development Workflow

**After every code change: push → pull on Pi → restart → trigger refresh.**

```bash
# 1. Edit locally, commit and push
git add -p && git commit -m "..." && git push

# 2. Pull on Pi and restart
ssh maciej@192.168.12.175 'cd ~/Waveshare-ePaper-10.85-dashboard && git pull && tmux kill-session -t dashboard 2>/dev/null; tmux new-session -d -s dashboard "python3 main.py"'

# 3. Trigger immediate refresh (run after a few seconds for process to start)
ssh maciej@192.168.12.175 'kill -USR1 $(pgrep -f main.py | head -1)'

# Watch logs
ssh maciej@192.168.12.175 'tail -f ~/Waveshare-ePaper-10.85-dashboard/dashboard.log'

# Attach to running session
ssh maciej@192.168.12.175 'tmux attach -t dashboard'
```

## On-Demand Refresh

Dashboard refreshes on data change, min 180s interval. Trigger immediate refresh via SIGUSR1:

```bash
ssh maciej@192.168.12.175 'kill -USR1 $(pgrep -f main.py | head -1)'
```

Display still takes ~21s to physically update after signal.

## Project Structure

```
main.py              # Main script — widget logic, rendering, main loop
message_server.py    # Standalone HTTP server for col3 custom message widget (port 5000)
claude.py            # Claude Code usage data fetcher
antigravity.py       # Antigravity usage data fetcher
lib/
  waveshare_epd/     # Display drivers: epd10in85g.py + epdconfig_g.py (active), epd10in85.py (unused)
  bambulabs_api/     # Bundled Bambu Lab printer API
fnt/                 # Fonts (see Font Notes below)
icons/               # BMP icons for widgets
lang/                # i18n strings: en.toml, pl.toml
dashboard.log        # Rotating log (1 MB max, 1 backup)
```

Credential/token files (not in repo, created on first run):
- `strava_token.json` — Strava OAuth tokens
- `token.json` — Gmail OAuth token
- `credentials.json` — Gmail OAuth client credentials (must be placed manually)
- `roborock_session.pkl` — Roborock session
- `roborock_stats.json` — Roborock stats cache
- `claude_creds.json` — Claude Code OAuth tokens
- `dashboard_message.json` — current custom message for col3 (written by message_server.py)

## Architecture

**Multi-threaded, change-driven refresh:**
- Background threads fetch data per-service (`update_data_thread`, `roborock_update_thread`)
- Main loop renders on data change with `MIN_REFRESH_INTERVAL = 180` s rate-limit
- Hardware watchdog via `signal.alarm(90)` — hangs trigger `os.execv` self-restart
- Icon cache (`icon_cache` dict) prevents repeated disk reads
- GC runs every 10 refresh cycles
- Every 600 refreshes (~30h): full `sleep()` → `Init()` → `Clear()` to eliminate ghosting

**Weather fetch:** every 600s. Uses `fetch_with_retry(url, retries=3, delay=5)` — retries up to 3× with 5s delay on failure. `last_update['weather']` only set on success, so failed fetches retry next loop (~1s).

**Refresh timing (G version — hardware enforced):**
- Full refresh: ~21 seconds per update
- Minimum cycle interval: 180 seconds (Waveshare requirement — do not lower)
- No partial refresh available
- `PowerOn()` / `PowerOff()` used each cycle to park panel rail without releasing GPIO/SPI

## Widget Toggles

Controlled via `settings_local.toml` on Pi (not in repo):

```toml
[widgets]
enable_strava      = false
enable_bambu       = false
enable_roborock    = false
enable_antigravity = false
enable_claude      = false
enable_spotify     = false
```

Disabled widgets show empty col2 space. Col1 always shows weather. Col3 always shows the custom message widget (blank when no message is set).

## Font Notes

Fonts in `fnt/`. Active fonts:
- `ElmsSans-Regular.ttf` — all widget text (Elms Sans weight 400, Google Fonts)
- `Doto-Bold.ttf` — calendar band (Doto weight 700, dot-matrix style, Google Fonts)
- `Doto-Regular.ttf` — available, not active
- `AntonSC-Regular.ttf` — available, not active
- `Aldrich-Regular.ttc` — legacy, not active
- `Oregano-*.ttf`, `BilboSwashCaps-Regular.ttf` — available, not active

**To add Google Font:** fetch CSS from `fonts.googleapis.com`, extract `.ttf` URL, `curl` into `fnt/`, load via `ImageFont.truetype`.

```python
# Verify font renders before using
from PIL import ImageFont, Image, ImageDraw
f = ImageFont.truetype('fnt/SomeFont.ttf', 40)
img = Image.new('RGB', (800, 60), 'white')
draw = ImageDraw.Draw(img)
draw.text((0, 5), 'Październik Środa Poniedziałek', font=f, fill='black')
print('OK')
```

## Configuration

All config in `settings_local.toml` on Pi (not in repo, not committed):

```toml
[location]
lat = 49.6790190   # Mecina, Poland
lon = 20.5495183

[display]
language = "pl"    # "en" or "pl"

[weather]
forecast_days = 5  # 5 or 7

[message_server]
port = 5000        # HTTP port for message_server.py (default: 5000)
```

Location controls Open-Meteo weather API. Wrong coords → wrong weather data.

## Layout

Display 1360×480. `render_screen()` divides into three equal columns (`col_w = 453px`). Calendar band spans col1+col2 top.

```
y=0  ┌──────────────────────────────────────────┬──────────────┐
     │  Calendar (single line, Doto Bold)        │              │
y=65 ├──────────────────────────────────────────┤   col3       │
     │  col1 (Weather)   │  col2 (Widgets)       │  ┌────────┐ │
     │                   │                       │  │header  │ │
     │  Temp + icon + UV │  Strava (opt)         │  │body    │ │
     │  Humidity, Press  │  Bambu (opt)          │  │(2 lines│ │
     │  (y=65–200)       │                       │  │max)    │ │
y=210├───────────────────┤  ─────────────────    │  │X ago   │ │
     │  5-day forecast   │  Roborock /           │  └────────┘ │
     │  (y=220–480)      │  Antigravity (opt)    │  (top 1/3,  │
     │                   │                       │  ~y10–170)  │
y=470└───────────────────┴───────────────────────┴──────────────┘
```

**Key constants:**
- `y_cal_div = 65` — bottom of calendar band / top of col content
- `col1_x = 20` — left margin
- `col2_x = col_w + 20` — col2 left edge
- `col3_x = col_w * 2 + 30` — col3 left edge
- Col1 separator at y=210 (between current weather and forecast)
- Col2 separators at y=165 (after Strava) and y=320 (before Roborock/Antigravity)
- Forecast `f_y = 220`, `icon_sz` capped at 50

**i18n:** `lang/pl.toml` and `lang/en.toml`. All Polish strings use full diacritics. `weekdays_full` key holds unabbreviated weekday names used by calendar.

## Custom Message Widget (col3)

Col3 shows up to 3 messages sent over the network. When no messages are set, col3 is blank.

**Queue:** up to 3 messages, round-robin — newest replaces oldest. Each message stored with the sender's IP address.

**Slot geometry:** col3 full height split into 3 equal slots (150px each, 5px gap). Only occupied slots are rendered; empty slots are blank.

**Layout inside each slot:** header (`fonts['24']`) at top-left, "X ago" timestamp at top-right (`fonts['20']`), separator line, body (`fonts['20']`, max 2 lines). Timestamp formats: `Xs ago`, `Xm ago`, `Xh Ym ago`, `Xh ago`, `Xd ago`, `Xw Yd ago`, `Xw ago`, `Xmo ago`.

**message_server.py** runs as a separate process (tmux session `msgserver`) and listens on port 5000.

### Starting the message server

```bash
ssh maciej@192.168.12.175 'cd ~/Waveshare-ePaper-10.85-dashboard && tmux new-session -d -s msgserver "python3 message_server.py"'
```

### API

```bash
# Add a message (appended to queue; oldest dropped when queue full)
curl -X POST http://192.168.12.175:5000/message \
  -H 'Content-Type: application/json' \
  -d '{"header":"ALERT","body":"Dinner is ready","text_color":"black","bg_color":"yellow","border_color":"red","ttl":3600}'

# Clear all messages sent from this IP
curl -X DELETE http://192.168.12.175:5000/message

# Read current message list
curl http://192.168.12.175:5000/message
```

### Message schema

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `header` | string | any | Large text at top, optional |
| `body` | string | any | Main text, word-wrapped |
| `text_color` | string | `black` `white` `red` `yellow` | Default: `black` |
| `bg_color` | string | `black` `white` `red` `yellow` | Default: `white` |
| `border_color` | string | `black` `white` `red` `yellow` `""` | Empty = no border |
| `ttl` | int | seconds | `0` = persistent; auto-clears per message on expiry |

After any POST/DELETE the server sends SIGUSR1 to main.py, triggering an immediate display refresh.

State persists across restarts in `dashboard_message.json` (JSON array of up to 3 message objects).

## Pi Zero Constraints

- **Single-core ARMv6 at ~1 GHz** — avoid CPU-intensive operations in the render path
- **~270 MB available RAM** — keep image buffers small; `del` and `gc.collect()` after each frame
- **No hardware floating-point acceleration** — numpy ops are fine; avoid heavy image processing
- **SPI bandwidth limited** — display transfer for a full 1360×480 frame takes several seconds
- **No I2C** — only SPI is active
- **Full refresh ~21s** — the main loop sleep must account for this; effective cycle is ~200s minimum

## Dependencies (on Pi)

All already installed:
- `pillow`, `numpy`, `requests`, `flask`, `spidev`, `gpiod`, `gpiozero`, `rpi-lgpio`
- `google-api-python-client`, `google-auth-*` (Gmail)
- `aiomqtt`, `roborock` (Roborock)
- `bambulabs_api` — bundled in `lib/`

To add a new pip dependency:
```bash
ssh maciej@192.168.12.175 'pip3 install <package>'
```

---

## Troubleshooting

### Screen flickering during refresh — expected behavior

**Symptom:** Screen flashes through red/yellow/black/white several times during each refresh.

**Root cause:** This is the (G) panel's 4-color waveform — it physically cycles all ink states to clear afterimages before settling. Unavoidable. There is no alternative LUT, no fast mode, no partial refresh on this panel.

**Minimizing perceived flicker:**
- `MIN_REFRESH_INTERVAL = 180` — never go below this. At 30s it feels constant and violates spec.
- Use `PowerOn()` / `PowerOff()` between refreshes instead of `sleep()` / `Init()` — avoids the extra Reset/Init flash each cycle.
- `Clear()` once per 600 cycles, not per cycle — each `Clear()` is a full waveform flash.

### Display BUSY pin stuck — SPI not working

**Symptom:** BUSY never goes LOW after Init commands. TurnOnDisplay completes instantly (no actual refresh).

**Root cause:** bcm2835 C library (used by Waveshare's DEV_Config_32_b.so) corrupts SPI hardware registers, breaking kernel spidev driver.

**Fix: reboot Pi.**
```bash
ssh maciej@192.168.12.175 'sudo reboot'
```
After reboot, run test again with lgpio+spidev driver (NOT the .so approach).

**Source:** Waveshare FAQ — "Why does the e-Paper not respond when running the python demo? It may be that a C language demo based on the BCM2835 library has been run before. Restart the Raspberry Pi and then run the python demo."

### DEV_Config_32_b.so approach (bcm2835) — DO NOT USE

The Waveshare official G demo uses DEV_Config_32_b.so which calls bcm2835. On this Pi:
- Needs root (`/dev/mem`) to drive GPIO — prints "bcm2835 init success" but GPIO writes silently fail as non-root
- PWR pin stays LOW → display never powers on → BUSY stays LOW forever
- Even as root: leaves SPI in broken state after exit → reboot required

**Use `epdconfig_g.py` instead** (lgpio + spidev, no root, no side effects).

### GPIO busy error (`lgpio.error: 'GPIO busy'`)

**Cause:** Previous Python process died without releasing GPIO via `module_exit()`. GPIO pins claimed by lgpio are process-scoped — die on process exit — but if process was killed with SIGKILL the kernel may not release immediately.

**Fix:**
```bash
pkill -f main.py; sleep 2  # wait for kernel to release
```
Or reboot if persists.

### Root cause: spidev per-byte CE toggling

Standard `spidev` deasserts CE (chip select) between every `writebytes()` call — including between a command byte and its data bytes. The G display ICs treat that mid-frame CE HIGH edge as end-of-frame, so `0x12` (Display Refresh) never arms and BUSY stays LOW forever.

**Fix:** `spidev.no_cs = True` on both devices, drive GPIO8 (CS_M) and GPIO7 (CS_S) manually via `pinctrl`. This holds CE LOW across entire command+data frames, matching the official bcm2835 behavior. See `lib/waveshare_epd/epdconfig_g.py`.

### Why `0x00` (Panel Setting) breaks power-on

`0x00` with data `0x2F 0x29` causes `0x04` (power-on) to hang indefinitely — even with the held-CE fix. Specific to this BW HAT + G panel combination. Root cause unknown (likely panel variant mismatch). Solution: skip `0x00` in Init. The display works correctly using default OTP panel settings; resolution is set explicitly via `0x61`.

### Bug in official Waveshare `Clear()`: 2× too much data

Official `epd10in85g.py` Clear sends `width/2 = 340` bytes/row per IC. Correct is `width/4 = 170` bytes (at 2bpp, 680px/IC = 170 bytes/row). Sending double data causes `TurnOnDisplay` to hang. Fixed in our driver.

### Bug in `epdconfig_g.py`: double-write on shared SPI bus

`spidev0.0` and `spidev0.1` (`_spi_m` and `_spi_s`) share the same physical SPI bus (MOSI/CLK). The original `spi_writebyte` and `spi_writebyte2` wrote to both fds when both CS were active (e.g. during `CS_ALL(0)` in Init), sending every byte twice. This garbled the Init sequence — most critically the resolution register (0x61), causing corrupted display output. **Fix:** always write via `_spi_m` only; CS selection via pinctrl determines which IC listens.

### Testing the display

```bash
# After clean reboot, from Pi:
cd /home/maciej/Waveshare-ePaper-10.85-dashboard
python3 -u -c "
import sys; sys.path.insert(0,'lib/waveshare_epd')
from epd10in85g import EPD
from PIL import Image, ImageDraw
epd = EPD(); epd.Init()
img = Image.new('RGB',(1360,480),'white')
draw = ImageDraw.Draw(img)
draw.rectangle([(0,0),(679,479)],fill='black')
draw.rectangle([(680,0),(1359,239)],fill='red')
draw.rectangle([(680,240),(1359,479)],fill=(255,255,0))
epd.Clear(); epd.display(epd.getbuffer(img))
print('done'); epd.sleep()
"
```

Expected: Init completes in ~2s, Clear takes ~17-21s, display takes ~17-21s. Screen shows left=black, top-right=red, bottom-right=yellow.

---

## Documentation Workflow

- When stuck on a problem: search Waveshare wiki + GitHub demo code first.
- After solving: save solution + root cause in this file.
- Write docs in caveman style (terse, no filler — use `/caveman` skill when updating this file).
