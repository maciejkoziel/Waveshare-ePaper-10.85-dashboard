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

```bash
# 1. Edit locally, commit and push
git add -p && git commit -m "..." && git push

# 2. Pull on Pi and restart
ssh maciej@192.168.12.175 'cd ~/Waveshare-ePaper-10.85-dashboard && git pull && tmux kill-session -t dashboard; tmux new-session -d -s dashboard "python3 main.py"'

# Watch logs
ssh maciej@192.168.12.175 'tail -f ~/Waveshare-ePaper-10.85-dashboard/dashboard.log'

# Attach to running session
ssh maciej@192.168.12.175 'tmux attach -t dashboard'
```

## On-Demand Refresh

The dashboard refreshes on data change with a minimum interval of 180 seconds (Waveshare spec). You can trigger an immediate refresh at any time via SIGUSR1.

**After every change to the dashboard, always trigger a manual refresh to verify the result on screen:**

```bash
# Trigger immediate refresh from Mac
ssh maciej@192.168.12.175 'kill -USR1 $(pgrep -f main.py)'

# Or directly on the Pi
kill -USR1 $(pgrep -f main.py)
```

This skips the remaining wait in the current 60s cycle and renders immediately. The display still takes ~21s to physically refresh (inherent to e-paper hardware).

## Project Structure

```
main.py              # Main script — widget logic, rendering, main loop
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

## Architecture

**Multi-threaded, change-driven refresh:**
- Background threads fetch data per-service (`update_data_thread`, `roborock_update_thread`)
- Main loop renders on data change with `MIN_REFRESH_INTERVAL = 180` s rate-limit
- Hardware watchdog via `signal.alarm(90)` — hangs trigger `os.execv` self-restart
- Icon cache (`icon_cache` dict) prevents repeated disk reads
- GC runs every 10 refresh cycles
- Every 600 refreshes (~30h): full `sleep()` → `Init()` → `Clear()` to eliminate ghosting

**Refresh timing (G version — hardware enforced):**
- Full refresh: ~21 seconds per update
- Minimum cycle interval: 180 seconds (Waveshare requirement — do not lower)
- No partial refresh available
- `PowerOn()` / `PowerOff()` used each cycle to park panel rail without releasing GPIO/SPI

## Widget Toggles

At the top of `main.py`:

```python
ENABLE_STRAVA = False
ENABLE_BAMBU = False
ENABLE_ROBOROCK = False
ENABLE_ANTIGRAVITY = False
ENABLE_CLAUDE = False
ENABLE_SPOTIFY = False
```

Disabled widgets fall back to: CPU/RAM load or BTC/ETH crypto prices.

## Font Notes

Fonts live in `fnt/`. The active calendar font is **AntonSC-Regular.ttf** (Anton SC from Google Fonts) — it supports full Polish diacritics (ą ę ó ś ź ż etc.). All other widgets use **Aldrich-Regular.ttc**, which does NOT support Polish diacritics.

Available fonts:
- `Aldrich-Regular.ttc` — used for all widget text
- `AntonSC-Regular.ttf` — calendar widget, Polish diacritic support confirmed
- `Oregano-Regular.ttf`, `Oregano-Italic.ttf` — available, not currently used
- `BilboSwashCaps-Regular.ttf` — available, not currently used
- `advanced_led_board-7.ttc`, `Font.ttc` — legacy, retained

**To add a Google Font:** fetch the CSS from `fonts.googleapis.com`, extract the `.ttf` URL, `curl` it into `fnt/`, verify Polish chars render (use the PIL test snippet below), then load via `ImageFont.truetype`.

```python
# Verify font supports Polish chars before using
from PIL import ImageFont, Image, ImageDraw
f = ImageFont.truetype('fnt/SomeFont.ttf', 40)
img = Image.new('RGB', (800, 60), 'white')
draw = ImageDraw.Draw(img)
draw.text((0, 5), 'Październik Środa Poniedziałek', font=f, fill='black')
bb = draw.textbbox((0,0), 'test', font=f)
print('OK')  # no exception = font loaded and rendered
```

## Configuration

At the top of `main.py`:

```python
LOCATION_LAT = 49.6790190   # Mecina, Poland — Open-Meteo weather + AQI
LOCATION_LON = 20.5495183

PRINTER_CONF = {'IP': ..., 'SERIAL': ..., 'ACCESS_CODE': ...}
ROBOROCK_CONF = {'EMAIL': ...}
LASTFM_CONF = {'API_KEY': ..., 'USERNAME': ...}
```

## Layout

Display is 1360×480. `render_screen()` in `main.py` divides it into three equal columns (`col_w = 1360 // 3 = 453px`) with a top calendar band spanning col1+col2.

```
y=0  ┌──────────────────────────────────────────┬──────────────┐
     │  Calendar (single line, Anton SC)         │              │
y=65 ├──────────────────────────────────────────┤   col3       │
     │  col1 (Widgets)   │  col2 (Weather)       │  (Claude /   │
     │                   │                       │  Spotify /   │
     │  Strava (opt)     │  Temp + icon + UV     │  Progress /  │
y=165├───────────────────┤  (y=65–205)           │  Gmail)      │
     │  Bambu 3D printer │                       │              │
     │  (y=80 or 185)    │  Wind + AQI           │              │
     │                   │  (y=205–365)          │              │
y=320├───────────────────┼───────────────────────┤              │
     │  Roborock /       │  5-day forecast       │              │
     │  Antigravity /    │  (y=375–469)          │              │
     │  Ping / SysLoad   │                       │              │
y=470└───────────────────┴───────────────────────┴──────────────┘
```

**Key constants:**
- `y_cal_div = 65` — bottom of calendar band / top of col1+col2 content
- `C2 = 45` — vertical offset applied to all col2 y-coordinates (col2 shifted down to make room for calendar band)
- `col1_x = 20` — left margin
- `col2_x = col_w + 20` — col2 left edge
- `col3_x = col_w * 2 + 30` — col3 left edge
- Forecast `icon_sz` capped at 50 (not 60) to prevent bottom overflow after C2 shift

**i18n:** `lang/pl.toml` and `lang/en.toml`. All Polish strings use full diacritics. `weekdays_full` key holds unabbreviated weekday names used by the calendar.

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
