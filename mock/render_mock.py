#!/usr/bin/env python3
"""Typography mockups for the e-ink dashboard (1360x480, 4-color).

Renders the real dashboard layout with sample Polish data in two font
directions:
  B "Editorial grotesk"  — Space Grotesk + IBM Plex Sans
  C "Brutalist poster"   — Archivo Black / Archivo Narrow / Archivo

Outputs (in mock/): dashboard_B.png, dashboard_C.png (quantized to the
4-color e-ink palette, no dithering) plus *_raw.png pre-quantization.
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FNT = os.path.join(ROOT, 'fnt')
ICONS = os.path.join(ROOT, 'icons')
OUT = os.path.dirname(os.path.abspath(__file__))

W, H = 1360, 480
YELLOW = (255, 255, 0)
RED = (255, 0, 0)

# ---------------------------------------------------------------- fonts

def F(name, size):
    return ImageFont.truetype(os.path.join(FNT, name), size)


def fonts_B():
    """Direction B — Editorial grotesk."""
    return {
        'masthead':   F('SpaceGrotesk-Bold.ttf', 34),       # date on black
        'label':      F('SpaceGrotesk-Medium.ttf', 22),     # tracked caps labels
        'label_knock': F('SpaceGrotesk-Bold.ttf', 22),      # labels on black (bumped)
        'hero':       F('SpaceGrotesk-Bold.ttf', 130),      # temperature number
        'hero_deg':   F('SpaceGrotesk-Bold.ttf', 52),       # raised degree sign
        'next_time':  F('SpaceGrotesk-Bold.ttf', 44),       # NASTEPNE time
        'cal_time':   F('SpaceGrotesk-Bold.ttf', 24),       # calendar times
        'cal_day':    F('SpaceGrotesk-Medium.ttf', 24),     # DZIS/JUTRO/PIA column (red rows >= 24px)
        'fc_day':     F('SpaceGrotesk-Medium.ttf', 22),     # forecast day abbrevs
        'fc_hi':      F('SpaceGrotesk-Bold.ttf', 30),       # forecast hi temps
        'fc_lo':      F('IBMPlexSans-Regular.ttf', 22),     # forecast lo temps
        'fc_rain':    F('IBMPlexSans-Bold.ttf', 24),        # rain % (red >= 24px)
        'body':       F('IBMPlexSans-Regular.ttf', 24),     # event titles, details
        'body22':     F('IBMPlexSans-Regular.ttf', 22),     # message body, tasks
        'body_knock': F('IBMPlexSans-Medium.ttf', 23),      # body on black (bumped)
        'strong':     F('IBMPlexSans-Bold.ttf', 24),        # message header, AQI
        'uv':         F('IBMPlexSans-Bold.ttf', 36),        # UV value
        'small':      F('IBMPlexSans-Regular.ttf', 20),     # timestamps, bar subs
        'small_knock': F('IBMPlexSans-Medium.ttf', 20),     # small on black (bumped)
        'tiny':       F('Tiny5-Regular.ttf', 20),
        'tracking':   2,
    }


def fonts_C():
    """Direction C — Brutalist poster."""
    return {
        'masthead':   F('ArchivoBlack-Regular.ttf', 32),
        'label':      F('ArchivoNarrow-Bold.ttf', 24),
        'label_knock': F('ArchivoNarrow-Bold.ttf', 24),  # 26 clips E-ogonek into separator
        'hero':       F('ArchivoBlack-Regular.ttf', 130),
        'hero_deg':   F('ArchivoBlack-Regular.ttf', 52),
        'next_time':  F('ArchivoBlack-Regular.ttf', 44),
        'cal_time':   F('ArchivoNarrow-Bold.ttf', 26),
        'cal_day':    F('ArchivoNarrow-Bold.ttf', 24),
        'fc_day':     F('ArchivoNarrow-Bold.ttf', 24),
        'fc_hi':      F('ArchivoBlack-Regular.ttf', 30),
        'fc_lo':      F('Archivo-Regular.ttf', 22),
        'fc_rain':    F('ArchivoNarrow-Bold.ttf', 24),
        'body':       F('Archivo-Regular.ttf', 24),
        'body22':     F('Archivo-Regular.ttf', 22),
        'body_knock': F('Archivo-Medium.ttf', 23),
        'strong':     F('Archivo-SemiBold.ttf', 24),
        'uv':         F('ArchivoBlack-Regular.ttf', 36),
        'small':      F('Archivo-Regular.ttf', 20),
        'small_knock': F('Archivo-Medium.ttf', 20),
        'tiny':       F('Tiny5-Regular.ttf', 20),
        'tracking':   2,
    }

# ---------------------------------------------------------------- helpers

icon_cache = {}


def get_icon(name, size, is_white=False):
    key = (name, size, is_white)
    if key not in icon_cache:
        path = os.path.join(ICONS, f"{name}.bmp")
        if os.path.exists(path):
            img = Image.open(path).convert('L').resize(size)
            icon_cache[key] = ImageOps.invert(img).convert('1')
        else:
            icon_cache[key] = None
    return icon_cache[key]


def draw_icon(draw, x, y, name, size=(40, 40), is_white=False):
    icon = get_icon(name, size, is_white)
    if icon:
        draw.bitmap((x, y), icon, fill='white' if is_white else 'black')
    else:
        draw.ellipse((x, y, x + size[0], y + size[1]),
                     outline='white' if is_white else 'black', width=3)


def draw_tri(draw, x, y, size=13, up=True, fill='black'):
    if up:
        draw.polygon([(x, y + size), (x + size, y + size), (x + size / 2, y)], fill=fill)
    else:
        draw.polygon([(x, y), (x + size, y), (x + size / 2, y + size)], fill=fill)


def draw_drop(draw, x, y, size=13, fill='black'):
    r = size // 2
    draw.ellipse((x, y + size - 2 * r, x + 2 * r, y + size), fill=fill)
    draw.polygon([(x, y + size - r), (x + 2 * r, y + size - r), (x + r, y)], fill=fill)


def tracked_len(text, font, tracking):
    if not text:
        return 0
    return sum(font.getlength(c) for c in text) + tracking * (len(text) - 1)


def draw_tracked(draw, xy, text, font, fill, tracking):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + tracking


def wrap_text(text, font, max_width):
    words, lines, current = text.split(), [], ''
    for word in words:
        test = (current + ' ' + word).strip()
        if font.getlength(test) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

# ---------------------------------------------------------------- render

def render(fs):
    img = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(img)
    trk = fs['tracking']

    BAND_H = 54
    rail_w = 380
    c3x = 916
    c3w = W - c3x - 12          # 432
    mid_x = rail_w + 24         # 404
    mid_w = c3x - 24 - mid_x    # 488
    MID_FLOOR = 382
    row_h = 33

    # --- MASTHEAD ---
    d.rectangle((0, 0, W, BAND_H), fill='black')
    d.text((20, 8), 'WEDNESDAY 11 JUNE', font=fs['masthead'], fill='white')

    rx = W - 20
    aqi_s = 'AQI 42'
    aw = fs['strong'].getlength(aqi_s)
    d.text((rx - aw, 14), aqi_s, font=fs['strong'], fill=YELLOW)   # 40-59 -> yellow
    rx -= aw + 44

    moon_name = 'Full Moon'
    moon_w = 32 + fs['body_knock'].getlength(moon_name)
    draw_icon(d, int(rx - moon_w), 15, 'icon_moon_phase_4', (24, 24), is_white=True)
    d.text((rx - moon_w + 32, 14), moon_name, font=fs['body_knock'], fill='white')
    rx -= moon_w + 44

    sr, ss = '04:31', '20:58'
    sun_w = 36 + fs['body_knock'].getlength(sr) + 38 + fs['body_knock'].getlength(ss)
    sx = rx - sun_w
    draw_tri(d, sx, 20, 13, up=True, fill=YELLOW)
    d.text((sx + 18, 14), sr, font=fs['body_knock'], fill='white')
    sx2 = sx + 18 + fs['body_knock'].getlength(sr) + 20
    draw_tri(d, sx2, 20, 13, up=False, fill=YELLOW)
    d.text((sx2 + 18, 14), ss, font=fs['body_knock'], fill='white')

    # --- LEFT RAIL: NOW box (ongoing event) ---
    bx, by, bw, bh = 10, 64, 360, 108
    d.rectangle((bx, by, bx + bw, by + bh), fill='black')
    draw_tracked(d, (bx + 12, by + 5), 'NOW', fs['label_knock'], YELLOW, trk)
    d.line((bx + 8, by + 34, bx + bw - 8, by + 34), fill='white', width=1)

    t_start, t_end = '15:00', '16:00'
    time_font = fs['cal_time']
    time_w = int(time_font.getlength(t_start))
    title_max = bw - 34 - time_w
    lines = wrap_text('Stand-up meeting', fs['body_knock'], title_max)[:2]
    TIME_LINE_H = 30
    time_block_h = TIME_LINE_H * 2
    LINE_H, LABEL_LINE_H = 28, 26
    label_h = LABEL_LINE_H + (len(lines) - 1) * LINE_H
    block_h = max(time_block_h, label_h)
    block_y = by + 36 + (68 - block_h) // 2
    time_y  = block_y + (block_h - time_block_h) // 2
    title_y = block_y + (block_h - label_h) // 2
    d.text((bx + 12, time_y),              t_start, font=time_font, fill=YELLOW)
    d.text((bx + 12, time_y + TIME_LINE_H), t_end,  font=time_font, fill=YELLOW)
    tx = bx + 12 + time_w + 10
    for i, line in enumerate(lines):
        d.text((tx, title_y + i * LINE_H), line, font=fs['body_knock'], fill=YELLOW)

    # --- LEFT RAIL: current weather ---
    ry = 180
    draw_icon(d, 20, ry + 8, 'icon_sun', (70, 70))
    # hero temperature: big number + degree at ~40% size, raised
    num = '21'
    hx, hy = 100, ry - 14
    d.text((hx, hy), num, font=fs['hero'], fill='black')
    nb = d.textbbox((hx, hy), num, font=fs['hero'])
    d.text((nb[2] + 4, nb[1] - 6), '°', font=fs['hero_deg'], fill='black')

    # UV box (UV >= 6 -> red)
    uvx = min(rail_w - 70, nb[2] + 44)
    d.text((uvx + 6, ry - 8), 'UV', font=fs['small'], fill='black')
    d.rectangle((uvx - 4, ry + 14, uvx + 44, ry + 56), fill='red')
    uv_s = '6'
    uw = fs['uv'].getlength(uv_s)
    d.text((uvx - 4 + (48 - uw) / 2, ry + 14), uv_s, font=fs['uv'], fill='white')

    ly = ry + 116
    d.text((20, ly), 'Humidity 54%', font=fs['body'], fill='black')
    d.text((20, ly + 32), '1013 hPa', font=fs['body'], fill='black')
    draw_icon(d, 20, ly + 66, 'icon_wind', (26, 26))
    d.text((52, ly + 64), '12 km/h NW', font=fs['body'], fill='black')

    # dividers
    d.line((rail_w + 8, BAND_H + 10, rail_w + 8, MID_FLOOR), fill='black', width=1)
    d.line((c3x - 12, BAND_H + 10, c3x - 12, 470), fill='black', width=1)

    # --- MIDDLE: calendar + tasks ---
    y = BAND_H + 12

    cal_rows = [
        ('yellow', 'TODAY', '15:00', 'Stand-up meeting',    'red'),    # ongoing
        ('yellow', 'TODAY', '17:00', 'Football training',   'black'),  # upcoming
        ('black',  'TOM',   '09:15', 'Dentist — Michael',   'black'),
        ('black',  'FRI',   '18:30', 'Cinema with Anna',    'black'),
    ]
    DAY_X, TIME_X, TITLE_X = mid_x + 28, mid_x + 122, mid_x + 200
    for sq, day, tm, title, color in cal_rows:
        d.rectangle((mid_x + 2, y + 7, mid_x + 16, y + 21), fill=sq, outline='black')
        d.text((DAY_X, y + 2), day, font=fs['cal_day'], fill=color)
        d.text((TIME_X, y), tm, font=fs['cal_time'], fill=color)
        d.text((TITLE_X, y), title, font=fs['body'], fill=color)
        y += row_h

    y += 6
    for task in ['Buy water filter', 'Schedule lawn mower service']:
        d.rectangle((mid_x + 2, y + 7, mid_x + 16, y + 21), outline='black', width=2)
        d.text((DAY_X, y + 1), task, font=fs['body22'], fill='black')
        y += row_h

    def usage_bar_inline(x, y, w, pct, label, sub, label_col_w=None):
        lw = label_col_w if label_col_w is not None else int(fs['small'].getlength(label))
        sw = int(fs['small'].getlength(sub))
        d.text((x, y), label, font=fs['small'], fill='black')
        d.text((x + w - sw, y), sub, font=fs['small'], fill='black')
        bar_x = x + lw + 8
        bar_end = x + w - sw - 8
        bar_w = max(0, bar_end - bar_x)
        if bar_w > 0:
            by = y + 4
            d.rectangle((bar_x, by, bar_x + bar_w, by + 12), outline='black', width=2)
            fill_w = int((bar_w - 4) * min(pct / 100.0, 1.0))
            if fill_w > 0:
                d.rectangle((bar_x + 2, by + 2, bar_x + 2 + fill_w, by + 10),
                             fill='red' if pct >= 80 else 'black')

    # --- COL3: 3 messages + compact claude ---
    COMPACT_H = 90
    c3_top = BAND_H + 10
    # compact claude: stacked letters + 2 aligned inline bars
    d.line((c3x + 8, c3_top - 4, c3x + c3w, c3_top - 4), fill='black', width=1)
    vfont = fs['tiny']
    letters = 'CLAUDE'
    sample_bb = vfont.getbbox('M')
    cell_h = sample_bb[3] - sample_bb[1] + 1
    max_lw = max(vfont.getbbox(c)[2] - vfont.getbbox(c)[0] for c in letters)
    total_h = len(letters) * cell_h
    ly = c3_top + (COMPACT_H - total_h) // 2
    for i, ch in enumerate(letters):
        cw = vfont.getbbox(ch)[2] - vfont.getbbox(ch)[0]
        d.text((c3x + 4 + (max_lw - cw) // 2, ly + i * cell_h), ch, font=vfont, fill='black')
    bx = c3x + max_lw + 12
    bw = c3w - max_lw - 20
    lbl_5h, lbl_7d = '5h · 42%', '7d · 81%'
    fixed_lw = max(int(fs['small'].getlength(lbl_5h)), int(fs['small'].getlength(lbl_7d)))
    usage_bar_inline(bx, c3_top + 8, bw, 42, lbl_5h, 'reset in 1 hr', label_col_w=fixed_lw)
    usage_bar_inline(bx, c3_top + 38, bw, 81, lbl_7d, 'reset in 3 days', label_col_w=fixed_lw)
    c3_top += COMPACT_H + 6

    SLOT_H, SLOT_GAP = 103, 5
    msgs = [
        ('PRINTER', '3m ago', YELLOW, 'red', 'Black ink low (12%)'),
        ('DINNER', '12m ago', 'white', '', 'Ready in the kitchen'),
        ('ALERT', '1h ago', 'white', 'black', 'Package delivered'),
    ]
    for i, (hdr, ago, bg, border, body) in enumerate(msgs):
        top = c3_top + i * (SLOT_H + SLOT_GAP)
        d.rectangle((c3x, top, c3x + c3w, top + SLOT_H), fill=bg)
        if border:
            d.rectangle((c3x, top, c3x + c3w, top + SLOT_H), outline=border, width=4)
        tc = 'black'
        d.text((c3x + 16, top + 10), hdr, font=fs['strong'], fill=tc)
        d.text((c3x + c3w - 16 - fs['small'].getlength(ago), top + 14), ago, font=fs['small'], fill=tc)
        d.line((c3x + 16, top + 44, c3x + c3w - 16, top + 44), fill=tc, width=1)
        d.text((c3x + 16, top + 54), body, font=fs['body22'], fill=tc)

    # --- FORECAST STRIP ---
    sy = 390
    d.line((20, sy, c3x - 24, sy), fill='black', width=1)
    fc = [
        ('THU', 20, 'icon_partly-cloudy-day', 24, 13),
        ('FRI', 60, 'icon_rain',              19, 12),
        ('SAT', 45, 'icon_rain-cloud',        21, 11),
        ('SUN', 10, 'icon_sun',               26, 14),
        ('MON',  0, 'icon_sun',               27, 15),
    ]
    strip_w = c3x - 24 - 20
    cell_w = strip_w // 5
    for slot, (day, rain, icon, hi, lo) in enumerate(fc):
        ox = 20 + slot * cell_w
        draw_tracked(d, (ox + 12, sy + 8), day, fs['fc_day'], 'black', trk)
        if rain >= 10:
            rc = 'red' if rain >= 60 else 'black'
            rain_s = f"{rain}%"
            px = ox + cell_w - 12 - fs['fc_rain'].getlength(rain_s)
            draw_drop(d, int(px - 16), sy + 12, 11, fill=rc)
            d.text((px, sy + 8), rain_s, font=fs['fc_rain'], fill=rc)
        draw_icon(d, ox + 12, sy + 36, icon, (40, 40))
        tx = ox + 12 + 40 + 10
        d.text((tx, sy + 34), f"{hi}°", font=fs['fc_hi'], fill='black')
        d.text((tx, sy + 64), f"{lo}°", font=fs['fc_lo'], fill='black')

    return img

# ---------------------------------------------------------------- output

def quantize(img):
    """Nearest-color map to the 4-color e-ink palette, no dithering."""
    pal = Image.new('P', (1, 1))
    pal.putpalette([0, 0, 0, 255, 255, 255, 255, 255, 0, 255, 0, 0] + [0, 0, 0] * 252)
    return img.quantize(palette=pal, dither=Image.Dither.NONE).convert('RGB')


if __name__ == '__main__':
    for tag, maker in (('B', fonts_B), ('C', fonts_C)):
        raw = render(maker())
        raw.save(os.path.join(OUT, f'dashboard_{tag}_raw.png'))
        quantize(raw).save(os.path.join(OUT, f'dashboard_{tag}.png'))
        print(f'dashboard_{tag}.png written')
