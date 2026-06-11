#!/usr/bin/python3
# -*- coding:utf-8 -*-
import sys
import os
import time
import logging
import threading
import requests
import io
import gc
import socket
import resource
import signal
import json
import subprocess
import math
import calendar
import tomllib
from collections import deque
from datetime import datetime, timezone, timedelta, date as date_cls
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
from logging.handlers import RotatingFileHandler

# --- GMAIL IMPORTS ---
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# --- SYSTEM LIMITS ---
try:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
except Exception as e:
    print(f"Failed to set rlimit: {e}")

# --- PATHS ---
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
LIB_DIR = os.path.join(BASE_DIR, 'lib')
FONT_DIR = os.path.join(BASE_DIR, 'fnt')
ICON_DIR = os.path.join(BASE_DIR, 'icons')
LOG_FILE = os.path.join(BASE_DIR, 'dashboard.log')
MESSAGE_FILE = os.path.join(BASE_DIR, 'dashboard_message.json')

# --- LOCAL SETTINGS ---
_cfg_path = os.path.join(BASE_DIR, 'settings_local.toml')
try:
    with open(_cfg_path, 'rb') as _f:
        _cfg = tomllib.load(_f)
    _w = _cfg.get('widgets', {})
    ENABLE_CALENDAR    = _w.get('enable_calendar', False)
    ENABLE_TASKS       = _w.get('enable_tasks', False)
    ENABLE_CLAUDE      = _w.get('enable_claude', False)
    ENABLE_SPOTIFY     = _w.get('enable_spotify', False)
    _loc = _cfg.get('location', {})
    LOCATION_LAT = _loc.get('lat', 44.8240855)
    LOCATION_LON = _loc.get('lon', 20.4934273)
    _lfm = _cfg.get('lastfm', {})
    LASTFM_CONF = {'API_KEY': _lfm.get('api_key', ''), 'USERNAME': _lfm.get('username', '')}
    LANGUAGE = _cfg.get('display', {}).get('language', 'en')
    FORECAST_DAYS = _cfg.get('weather', {}).get('forecast_days', 5)
except FileNotFoundError:
    ENABLE_CALENDAR = False
    ENABLE_TASKS = False
    ENABLE_CLAUDE = False
    ENABLE_SPOTIFY = False
    LOCATION_LAT = 49.6790190
    LOCATION_LON = 20.5495183
    LASTFM_CONF = {'API_KEY': '', 'USERNAME': ''}
    LANGUAGE = 'en'
    FORECAST_DAYS = 5

# --- LANGUAGE STRINGS ---
LANG_DIR = os.path.join(BASE_DIR, 'lang')
try:
    with open(os.path.join(LANG_DIR, f'{LANGUAGE}.toml'), 'rb') as _f:
        STRINGS = tomllib.load(_f)
except FileNotFoundError:
    try:
        with open(os.path.join(LANG_DIR, 'en.toml'), 'rb') as _f:
            STRINGS = tomllib.load(_f)
    except FileNotFoundError:
        STRINGS = {}

# --- API ENDPOINTS ---
API_ENDPOINTS = {
    'weather': 'http://api.open-meteo.com/v1/forecast',
    'air_quality': 'http://air-quality-api.open-meteo.com/v1/air-quality',
    'btc': 'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart',
    'eth': 'https://api.coingecko.com/api/v3/coins/ethereum/market_chart',
    'lastfm': 'http://ws.audioscrobbler.com/2.0/'
}

# --- FILES & SCOPES ---
GMAIL_TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')
GOOGLE_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/tasks.readonly',
]

if os.path.exists(LIB_DIR):
    sys.path.append(LIB_DIR)
    epd_dir = os.path.join(LIB_DIR, 'waveshare_epd')
    if os.path.exists(epd_dir):
        sys.path.insert(0, epd_dir)

try:
    import epd10in85g
except ImportError:
    pass

# --- LOGGING ---
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1 * 1024 * 1024, backupCount=1)
file_handler.setFormatter(formatter)

logger.handlers.clear()
logger.addHandler(console_handler)
logger.addHandler(file_handler)

icon_cache = {}
refresh_event = threading.Event()


class HardwareTimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise HardwareTimeoutError("Hardware Busy-Wait Timeout")


def refresh_signal_handler(signum, frame):
    refresh_event.set()


# --- ROBUST NETWORK MANAGER ---
class NetworkManager:
    def __init__(self):
        self.session = None
        self.create_session()

    def create_session(self):
        if self.session:
            try:
                self.session.close()
            except:
                pass
        gc.collect()
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=5, pool_maxsize=10,
            max_retries=requests.adapters.Retry(total=1, backoff_factor=0.5)
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

    def get_json(self, url, headers=None, data=None, method='GET', timeout=10):
        try:
            if self.session is None: self.create_session()
            if method == 'POST':
                resp = self.session.post(url, headers=headers, data=data, timeout=timeout)
            else:
                resp = self.session.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.create_session()
            return None

    def get_image(self, url, timeout=15):
        try:
            if self.session is None: self.create_session()
            resp = self.session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            self.create_session()
            return None


net = NetworkManager()


# --- GLOBAL DATA STORE ---
class DataStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.weather = {}
        self.aqi = 0
        self.gmail_unread = 0
        self.spotify = {'status': 'PAUSED', 'text': '', 'cover': None}
        self.claude = {'error': False, 'five_hour': {}, 'seven_day': {}}
        self.calendar_events = []
        self.tasks_items = []
        self.sysload = {'cpu': 0, 'ram_free': 0, 'history': deque(maxlen=30)}
        self.crypto = {'btc': 0, 'eth': 0, 'btc_hist': [], 'eth_hist': []}
        self.ping = {'current': 0, 'history': deque(maxlen=50)}

        self.last_update = {
            'weather': 0, 'gmail': 0,
            'spotify': 0, 'crypto': 0, 'sysload': 0, 'ping': 0,
            'claude': 0, 'calendar': 0, 'tasks': 0,
            'aqi': 0,
        }
        self.data_changed = threading.Event()
        self.last_fingerprint = None


data_store = DataStore()


def get_data_fingerprint(ds):
    with ds.lock:
        return (
            ds.weather.get('current', {}).get('temperature_2m'),
            ds.weather.get('current', {}).get('weather_code'),
            ds.gmail_unread,
            str(ds.calendar_events),
            ds.spotify.get('status'),
            ds.spotify.get('text'),
            ds.claude.get('five_hour', {}).get('utilization'),
            ds.claude.get('seven_day', {}).get('utilization'),
            ds.aqi,
            str(ds.tasks_items),
            str(ds.weather.get('daily', {}).get('precipitation_probability_max')),
        )


# --- HELPERS ---
def fetch_with_retry(url, retries=3, delay=5, timeout=10):
    for attempt in range(retries):
        data = net.get_json(url, timeout=timeout)
        if data:
            return data
        if attempt < retries - 1:
            time.sleep(delay)
    return None


def get_cached_icon(name, size, is_white=False):
    key = f"{name}_{size[0]}x{size[1]}_{'white' if is_white else 'black'}"
    if key not in icon_cache:
        path = os.path.join(ICON_DIR, f"{name}.bmp")
        if os.path.exists(path):
            try:
                with Image.open(path) as f_img:
                    img = f_img.convert("L").resize(size)
                    img = ImageOps.invert(img)
                    icon_cache[key] = img.convert("1")
            except:
                return None
        else:
            icon_cache[key] = None
    return icon_cache.get(key)


def time_until(iso_str):
    if not iso_str: return STRINGS.get('not_available', 'N/A')
    try:
        target = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        diff = target - now
        if diff.total_seconds() < 0: return STRINGS.get('resetting', 'Resetting...')
        hours, rem = divmod(diff.total_seconds(), 3600)
        days, hours = divmod(hours, 24)
        if days > 0:
            return STRINGS.get('time_days_hours', '{days}d {hours}h').format(days=int(days), hours=int(hours))
        else:
            minutes = rem // 60
            return STRINGS.get('time_hours_minutes', '{hours}h {minutes}m').format(hours=int(hours), minutes=int(minutes))
    except Exception:
        return STRINGS.get('not_available', 'N/A')


# --- AUTH & FETCH THREADS ---

def auth_claude():
    global ENABLE_CLAUDE
    if not ENABLE_CLAUDE: return
    try:
        import claude
        success = claude.interactive_auth()
        if not success:
            ENABLE_CLAUDE = False
            print("Claude widget is disabled.")
    except ImportError:
        print("claude.py not found. Claude widget disabled.")
        ENABLE_CLAUDE = False


def auth_google():
    if os.path.exists(GMAIL_TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_PATH, GOOGLE_SCOPES)
            if creds.valid:
                return
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(GMAIL_TOKEN_PATH, 'w') as f: f.write(creds.to_json())
                return
        except Exception:
            pass

    if not os.path.exists(os.path.join(BASE_DIR, 'credentials.json')):
        print("Google credentials.json not found — Gmail and Calendar disabled.")
        return

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(
            os.path.join(BASE_DIR, 'credentials.json'), GOOGLE_SCOPES)
        flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
        auth_url, _ = flow.authorization_url(prompt='consent')
        print("\n--- GOOGLE AUTHORIZATION REQUIRED ---")
        print(f"Open this URL in your browser:\n\n{auth_url}\n")
        code = input("Paste the authorization code here: ").strip()
        flow.fetch_token(code=code)
        creds = flow.credentials
        with open(GMAIL_TOKEN_PATH, 'w') as f: f.write(creds.to_json())
        print("Google Authorization Successful!\n")
    except Exception as e:
        print(f"Google auth failed: {e}")


def update_data_thread():
    while True:
        now = time.time()

        if now - data_store.last_update['weather'] > 600:
            weather_url = f"{API_ENDPOINTS['weather']}?latitude={LOCATION_LAT}&longitude={LOCATION_LON}&current=temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m,weather_code,is_day,uv_index&daily=temperature_2m_max,temperature_2m_min,weather_code,sunrise,sunset,precipitation_probability_max&timezone=auto&forecast_days={FORECAST_DAYS + 1}"
            w_data = fetch_with_retry(weather_url, timeout=30)
            if w_data:
                with data_store.lock:
                    data_store.weather = w_data
                data_store.last_update['weather'] = now

        if now - data_store.last_update['aqi'] > 600:
            aqi_url = f"{API_ENDPOINTS['air_quality']}?latitude={LOCATION_LAT}&longitude={LOCATION_LON}&current=european_aqi"
            a_data = net.get_json(aqi_url, timeout=30)
            if a_data:
                val = a_data.get('current', {}).get('european_aqi')
                if val is not None:
                    with data_store.lock:
                        data_store.aqi = int(round(val))
            data_store.last_update['aqi'] = now

        if now - data_store.last_update['gmail'] > 300:
            try:
                creds = None
                if os.path.exists(GMAIL_TOKEN_PATH):
                    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_PATH, GOOGLE_SCOPES)
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        with open(GMAIL_TOKEN_PATH, 'w') as t: t.write(creds.to_json())
                if creds and creds.valid:
                    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
                    label_info = service.users().labels().get(userId='me', id='INBOX').execute()
                    with data_store.lock: data_store.gmail_unread = label_info.get('messagesUnread', 0)
            except:
                pass
            data_store.last_update['gmail'] = now

        if ENABLE_CALENDAR and now - data_store.last_update['calendar'] > 300:
            try:
                creds = None
                if os.path.exists(GMAIL_TOKEN_PATH):
                    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_PATH, GOOGLE_SCOPES)
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        with open(GMAIL_TOKEN_PATH, 'w') as t: t.write(creds.to_json())
                if creds and creds.valid:
                    cal_service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
                    now_iso = datetime.now(timezone.utc).isoformat()
                    cal_list = cal_service.calendarList().list().execute()
                    calendar_ids = {}
                    for cal in cal_list.get('items', []):
                        name = cal.get('summary', '')
                        if cal.get('primary'):
                            calendar_ids[cal['id']] = 'personal'
                        elif 'rodzin' in name.lower():
                            calendar_ids[cal['id']] = 'family'
                    all_events = []
                    for cal_id, cal_type in calendar_ids.items():
                        result = cal_service.events().list(
                            calendarId=cal_id, timeMin=now_iso,
                            maxResults=10, singleEvents=True, orderBy='startTime'
                        ).execute()
                        for ev in result.get('items', []):
                            start = ev['start'].get('dateTime', ev['start'].get('date', ''))
                            end   = ev['end'].get('dateTime', ev['end'].get('date', ''))
                            is_allday = 'T' not in start
                            try:
                                if is_allday:
                                    dt_ev = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                                    event_date = datetime.strptime(start, '%Y-%m-%d').date()
                                    dt_end = None
                                else:
                                    dt_ev = datetime.fromisoformat(start.replace('Z', '+00:00'))
                                    event_date = dt_ev.astimezone().date()
                                    dt_end = datetime.fromisoformat(end.replace('Z', '+00:00')) if end else None
                            except Exception:
                                dt_ev = datetime.now(timezone.utc)
                                event_date = dt_ev.date()
                                is_allday = True
                                dt_end = None
                            all_events.append({
                                'title': ev.get('summary', '?'),
                                'calendar': cal_type,
                                'dt': dt_ev,
                                'dt_end': dt_end,
                                'event_date': event_date,
                                'allday': is_allday,
                            })
                    all_events.sort(key=lambda e: e['dt'])
                    with data_store.lock: data_store.calendar_events = all_events[:8]
            except Exception as e:
                logging.error(f"Calendar error: {e}")
            data_store.last_update['calendar'] = now

        if ENABLE_TASKS and now - data_store.last_update['tasks'] > 300:
            try:
                creds = None
                if os.path.exists(GMAIL_TOKEN_PATH):
                    creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_PATH, GOOGLE_SCOPES)
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        with open(GMAIL_TOKEN_PATH, 'w') as t: t.write(creds.to_json())
                if creds and creds.valid:
                    tasks_service = build('tasks', 'v1', credentials=creds, cache_discovery=False)
                    result = tasks_service.tasks().list(
                        tasklist='@default', showCompleted=False,
                        showHidden=False, maxResults=10
                    ).execute()
                    items = []
                    for t in result.get('items', []):
                        due = t.get('due', '')
                        due_str = ''
                        if due:
                            try:
                                due_date = datetime.strptime(due[:10], '%Y-%m-%d').date()
                                today = datetime.now().date()
                                delta = (due_date - today).days
                                if delta == 0:
                                    due_str = STRINGS.get('calendar_today', 'dziś')
                                elif delta == 1:
                                    due_str = STRINGS.get('calendar_tomorrow', 'jutro')
                                elif delta > 1:
                                    due_str = f"+{delta}"
                                else:
                                    due_str = f"{delta}d"
                            except Exception:
                                pass
                        items.append({'title': t.get('title', '?'), 'due': due_str})
                    with data_store.lock: data_store.tasks_items = items
            except Exception as e:
                logging.error(f"Tasks error: {e}")
            data_store.last_update['tasks'] = now

        # Claude Data Fetching (Run external script every 10 min)
        if ENABLE_CLAUDE and now - data_store.last_update['claude'] > 600:
            try:
                subprocess.run([sys.executable, os.path.join(BASE_DIR, 'claude.py')], capture_output=True, timeout=30)
                usage_path = os.path.join(BASE_DIR, 'usage.json')
                if os.path.exists(usage_path):
                    with open(usage_path, 'r') as f:
                        usage_data = json.load(f)
                    with data_store.lock:
                        data_store.claude = usage_data
                        if "error" in usage_data and "five_hour" not in usage_data:
                            data_store.claude['error'] = True
                        else:
                            data_store.claude['error'] = False
                else:
                    with data_store.lock:
                        data_store.claude['error'] = True
            except Exception as e:
                logging.error(f"Claude update error: {e}")
                with data_store.lock:
                    data_store.claude['error'] = True
            data_store.last_update['claude'] = now

        if ENABLE_SPOTIFY and now - data_store.last_update['spotify'] > 20:
            url = f"{API_ENDPOINTS['lastfm']}?method=user.getrecenttracks&user={LASTFM_CONF['USERNAME']}&api_key={LASTFM_CONF['API_KEY']}&format=json&limit=2&rnd={int(now)}"
            s_data = net.get_json(url, timeout=5)
            if s_data:
                try:
                    tracks = s_data.get('recenttracks', {}).get('track', [])
                    if isinstance(tracks, dict): tracks = [tracks]
                    if tracks:
                        current_track = tracks[0]
                        is_playing = current_track.get('@attr', {}).get('nowplaying') == 'true'
                        if is_playing:
                            track_name = current_track.get('name', 'Unknown')
                            artist = current_track.get('artist', {}).get('#text', 'Unknown')
                            img_url = ""
                            for img in current_track.get('image', []):
                                if img.get('size') == 'extralarge': img_url = img.get('#text', '')
                            cover_dithered = None
                            if img_url:
                                img_bytes = net.get_image(img_url)
                                if img_bytes:
                                    img_pil = Image.open(io.BytesIO(img_bytes)).convert("L").resize((120, 120))
                                    enhancer = ImageEnhance.Contrast(img_pil)
                                    img_pil = enhancer.enhance(3.0)
                                    cover_dithered = img_pil.convert("1", dither=Image.NONE)
                            with data_store.lock:
                                data_store.spotify = {'status': 'PLAYING', 'text': f"{artist} - {track_name}",
                                                      'cover': cover_dithered}
                        else:
                            with data_store.lock:
                                data_store.spotify = {'status': 'PAUSED', 'text': '', 'cover': None}
                except:
                    pass
            data_store.last_update['spotify'] = now

        gc.collect()
        new_fp = get_data_fingerprint(data_store)
        if new_fp != data_store.last_fingerprint:
            data_store.last_fingerprint = new_fp
            data_store.data_changed.set()
        time.sleep(1)


# --- GRAPHICS FUNCTIONS ---
def draw_icon(draw, x, y, name, size=(40, 40), is_white=False):
    icon = get_cached_icon(name, size, is_white)
    if icon:
        draw.bitmap((x, y), icon, fill="white" if is_white else "black")
    else:
        draw.rectangle((x, y, x + size[0], y + size[1]), outline="white" if is_white else "black")


def draw_sparkline(draw, x, y, data, max_items=50, width=400, height=60, color="black", style="bar"):
    if not data: return
    max_val = max(data) if max(data) > 0 else 1
    step = width / max(max_items - 1, 1)

    if style == "line":
        points = []
        for i, val in enumerate(data):
            px = x + i * step
            py = y + height - (val / max_val) * height
            points.append((px, py))
        if len(points) > 1: draw.line(points, fill=color, width=2)
    elif style == "bar":
        bar_w = max(int(step) - 1, 1)
        for i, val in enumerate(data):
            bh = int((val / max_val) * height)
            bx = x + i * step
            by = y + height - bh
            draw.rectangle((bx, by, bx + bar_w, y + height), fill=color)


def get_weather_icon(code, is_day=1):
    if code == 0:
        return "icon_sun" if is_day else "icon_moon"
    elif code in [1, 2]:
        return "icon_partly-cloudy-day"
    elif code == 3:
        return "icon_clouds"
    elif code in [45, 48]:
        return "icon_wind"
    elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
        return "icon_rain"
    elif code in [71, 73, 75, 85, 86]:
        return "icon_snow"
    elif code in [95, 96, 99]:
        return "icon_lightning"
    return "icon_sun"


def read_messages():
    try:
        with open(MESSAGE_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = [data]
        now = time.time()
        return [m for m in data if not (m.get('ttl', 0) > 0 and now - m.get('created_at', 0) > m['ttl'])]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def time_ago(ts):
    secs = int(time.time() - ts)
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    rem_mins = mins % 60
    if hours < 24:
        return f"{hours}h {rem_mins}m ago" if rem_mins else f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    rem_days = days % 7
    if weeks < 5:
        return f"{weeks}w {rem_days}d ago" if rem_days else f"{weeks}w ago"
    months = days // 30
    return f"{months}mo ago"


TRACKING = 2  # +px letterspacing for caps labels


def draw_tracked(draw, xy, text, font, fill, tracking=TRACKING):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + tracking


def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    current = ''
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


def moon_phase_index(dt):
    known_new = datetime(2000, 1, 6, 18, 14)
    days = (dt - known_new).total_seconds() / 86400
    return int((days % 29.53059) / 29.53059 * 8) % 8


def easter_date(year):
    # Anonymous Gregorian algorithm
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date_cls(year, month, day + 1)


PL_HOLIDAYS_FIXED = {
    (1, 1): 'NOWY ROK',
    (1, 6): 'TRZECH KRÓLI',
    (5, 1): 'ŚWIĘTO PRACY',
    (5, 3): 'KONSTYTUCJA 3 MAJA',
    (8, 15): 'WNIEBOWZIĘCIE NMP',
    (11, 1): 'WSZYSTKICH ŚWIĘTYCH',
    (11, 11): 'ŚWIĘTO NIEPODLEGŁOŚCI',
    (12, 24): 'WIGILIA',
    (12, 25): 'BOŻE NARODZENIE',
    (12, 26): 'DRUGI DZIEŃ ŚWIĄT',
}


def polish_holiday(d):
    fixed = PL_HOLIDAYS_FIXED.get((d.month, d.day))
    if fixed:
        return fixed
    easter = easter_date(d.year)
    offset = (d - easter).days
    return {
        0: 'WIELKANOC',
        1: 'PONIEDZIAŁEK WIELKANOCNY',
        49: 'ZIELONE ŚWIĄTKI',
        60: 'BOŻE CIAŁO',
    }.get(offset)


def wind_dir_label(deg):
    dirs = STRINGS.get('wind_dirs', ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])
    return dirs[int(((deg + 22.5) % 360) // 45)]


def fit_text(text, font, max_w):
    if font.getlength(text) <= max_w:
        return text
    while text and font.getlength(text + '…') > max_w:
        text = text[:-1]
    return text + '…'


def draw_tri(draw, x, y, size=13, up=True, fill='black'):
    if up:
        draw.polygon([(x, y + size), (x + size, y + size), (x + size / 2, y)], fill=fill)
    else:
        draw.polygon([(x, y), (x + size, y), (x + size / 2, y + size)], fill=fill)


def draw_drop(draw, x, y, size=13, fill='black'):
    r = size // 2
    draw.ellipse((x, y + size - 2 * r, x + 2 * r, y + size), fill=fill)
    draw.polygon([(x, y + size - r), (x + 2 * r, y + size - r), (x + r, y)], fill=fill)


def draw_usage_bar(draw, fonts, x, y, w, pct, label, sub):
    draw.text((x, y), label, font=fonts['small'], fill='black')
    draw.text((x + w - fonts['small'].getlength(sub), y), sub, font=fonts['small'], fill='black')
    by = y + 26
    draw.rectangle((x, by, x + w, by + 11), outline='black', width=2)
    fill_w = int((w - 4) * min(pct / 100.0, 1.0))
    if fill_w > 0:
        draw.rectangle((x + 2, by + 2, x + 2 + fill_w, by + 9),
                       fill='red' if pct >= 80 else 'black')


def draw_next_event_card(draw, fonts, x, w, top, h, ev, now_utc, today_date):
    draw.rectangle((x, top, x + w, top + h), fill='black')
    draw.text((x + 16, top + 8), STRINGS.get('next_title', 'NEXT'), font=fonts['label_knock'], fill='yellow')
    if ev.get('allday'):
        delta = (ev['event_date'] - today_date).days
        if delta == 0:
            big = STRINGS.get('calendar_today', 'today').upper()
        elif delta == 1:
            big = STRINGS.get('calendar_tomorrow', 'tomorrow').upper()
        else:
            big = f"+{delta}d"
        countdown = ''
    else:
        big = ev['dt'].astimezone().strftime('%H:%M')
        secs = (ev['dt'] - now_utc).total_seconds()
        if secs < 0:
            countdown = ''
        else:
            mins = int(secs // 60)
            days, rem = divmod(mins, 1440)
            hours, minutes = divmod(rem, 60)
            if days > 0:
                countdown = STRINGS.get('next_in_dh', 'in {days}d {hours}h').format(days=days, hours=hours)
            elif hours > 0:
                countdown = STRINGS.get('next_in_hm', 'in {hours}h {minutes}m').format(hours=hours, minutes=minutes)
            else:
                countdown = STRINGS.get('next_in_m', 'in {minutes}m').format(minutes=minutes)
    if countdown:
        draw.text((x + w - 16 - fonts['label_knock'].getlength(countdown), top + 8),
                  countdown, font=fonts['label_knock'], fill='yellow')
    draw.text((x + 16, top + 36), big, font=fonts['next_time'], fill='white')
    draw.text((x + 16, top + 94), fit_text(ev['title'], fonts['body_knock'], w - 32),
              font=fonts['body_knock'], fill='white')


def draw_next_event_rail(draw, fonts, x, y, w, ev, now_utc, today_date):
    draw.rectangle((x, y, x + w, y + 108), fill='black')
    tc = 'yellow' if ev.get('calendar') == 'family' else 'white'
    dt_end = ev.get('dt_end')
    ongoing = (not ev.get('allday')
               and ev['dt'] <= now_utc
               and dt_end is not None
               and now_utc < dt_end)
    if ongoing:
        header = STRINGS.get('current_title', 'NOW')
        draw_tracked(draw, (x + 12, y + 5), header, fonts['label_knock'], 'yellow')
        draw.line((x + 8, y + 34, x + w - 8, y + 34), fill='white', width=1)
        t_start = ev['dt'].astimezone().strftime('%H:%M')
        t_end   = dt_end.astimezone().strftime('%H:%M')
        TIME_LINE_H = 30   # cal_time line height
        time_block_h = TIME_LINE_H * 2
        time_font = fonts['cal_time']
        time_w = int(time_font.getlength(t_start))
        title_max_w = w - 34 - time_w
        lines = wrap_text(ev['title'], fonts['body_knock'], title_max_w)[:2]
        LINE_H, LABEL_LINE_H = 28, 26
        label_h = LABEL_LINE_H + (len(lines) - 1) * LINE_H
        block_h = max(time_block_h, label_h)
        block_y = y + 36 + (68 - block_h) // 2
        time_y  = block_y + (block_h - time_block_h) // 2
        title_y = block_y + (block_h - label_h) // 2
        draw.text((x + 12, time_y),                 t_start, font=time_font, fill=tc)
        draw.text((x + 12, time_y + TIME_LINE_H),   t_end,   font=time_font, fill=tc)
        tx = x + 12 + time_w + 10
        for i, line in enumerate(lines):
            draw.text((tx, title_y + i * LINE_H), line, font=fonts['body_knock'], fill=tc)
    else:
        draw_tracked(draw, (x + 12, y + 5), STRINGS.get('next_title', 'NEXT'),
                     fonts['label_knock'], 'yellow')
        if ev.get('allday'):
            delta = (ev['event_date'] - today_date).days
            if delta == 0:
                big = STRINGS.get('calendar_today', 'today').upper()
            elif delta == 1:
                big = STRINGS.get('calendar_tomorrow', 'tomorrow').upper()
            else:
                big = f"+{delta}d"
            countdown = ''
        else:
            big = ev['dt'].astimezone().strftime('%H:%M')
            secs = (ev['dt'] - now_utc).total_seconds()
            if secs < 0:
                countdown = ''
            else:
                mins = int(secs // 60)
                days, rem = divmod(mins, 1440)
                hours, minutes = divmod(rem, 60)
                if days > 0:
                    countdown = STRINGS.get('next_in_dh', 'in {days}d {hours}h').format(days=days, hours=hours)
                elif hours > 0:
                    countdown = STRINGS.get('next_in_hm', 'in {hours}h {minutes}m').format(hours=hours, minutes=minutes)
                else:
                    countdown = STRINGS.get('next_in_m', 'in {minutes}m').format(minutes=minutes)
        if countdown:
            draw.text((x + w - 12 - int(fonts['small_knock'].getlength(countdown)), y + 10),
                      countdown, font=fonts['small_knock'], fill='yellow')
        draw.line((x + 8, y + 34, x + w - 8, y + 34), fill='white', width=1)
        time_w = int(fonts['next_time'].getlength(big))
        title_max_w = w - 34 - time_w
        lines = wrap_text(ev['title'], fonts['body_knock'], title_max_w)[:2]
        TIME_H, LINE_H, LABEL_LINE_H = 48, 28, 26
        label_h = LABEL_LINE_H + (len(lines) - 1) * LINE_H
        block_h = max(TIME_H, label_h)
        block_y = y + 36 + (68 - block_h) // 2
        time_y  = block_y + (block_h - TIME_H) // 2
        title_y = block_y + (block_h - label_h) // 2
        draw.text((x + 12, time_y), big, font=fonts['next_time'], fill=tc)
        tx = x + 12 + time_w + 12
        for i, line in enumerate(lines):
            draw.text((tx, title_y + i * LINE_H), line, font=fonts['body_knock'], fill=tc)


def draw_claude_card(draw, fonts, x, w, top, h, claude, separator):
    if separator:
        draw.line((x + 8, top - 4, x + w, top - 4), fill='black', width=1)
    draw_tracked(draw, (x + 16, top + 4), STRINGS.get('claude_card', 'CLAUDE AI'),
                 fonts['label'], 'black')
    if claude.get('error'):
        draw.text((x + 16, top + 40), STRINGS.get('claude_error', 'Claude Usage Error'),
                  font=fonts['body22'], fill='black')
        return
    pct_5h = claude.get('five_hour', {}).get('utilization', 0)
    pct_7d = claude.get('seven_day', {}).get('utilization', 0)
    rem_5h = time_until(claude.get('five_hour', {}).get('resets_at'))
    rem_7d = time_until(claude.get('seven_day', {}).get('resets_at'))
    draw_usage_bar(draw, fonts, x + 16, top + 34, w - 32, pct_5h,
                   STRINGS.get('claude_5h_short', '5h · {pct}%').format(pct=pct_5h),
                   STRINGS.get('claude_reset', 'reset {time}').format(time=rem_5h))
    draw_usage_bar(draw, fonts, x + 16, top + 82, w - 32, pct_7d,
                   STRINGS.get('claude_7d_short', '7d · {pct}%').format(pct=pct_7d),
                   STRINGS.get('claude_reset', 'reset {time}').format(time=rem_7d))


def draw_message_slot(draw, fonts, x, w, top, h, msg):
    bg = msg.get('bg_color', 'white')
    tc = msg.get('text_color', 'black')
    bc = msg.get('border_color', '')
    draw.rectangle((x, top, x + w, top + h), fill=bg)
    if bc:
        draw.rectangle((x, top, x + w, top + h), outline=bc, width=4)
    y = top + 10
    header = msg.get('header', '').strip()
    created_at = msg.get('created_at')
    if header or created_at:
        if header:
            draw.text((x + 16, y), fit_text(header, fonts['strong'], w - 140), font=fonts['strong'], fill=tc)
        if created_at:
            ago = time_ago(created_at)
            draw.text((x + w - 16 - fonts['small'].getlength(ago), y + 4), ago, font=fonts['small'], fill=tc)
        draw.line((x + 16, top + 44, x + w - 16, top + 44), fill=tc, width=1)
        y = top + 54
    body = msg.get('body', '').strip()
    if body:
        for line in wrap_text(body, fonts['body22'], w - 32)[:2]:
            draw.text((x + 16, y), line, font=fonts['body22'], fill=tc)
            y += 28


def render_screen(epd, fonts):
    total_width = epd.width * 2
    Himage = Image.new('RGB', (total_width, epd.height), 'white')
    draw = ImageDraw.Draw(Himage)

    if not data_store.lock.acquire(timeout=2.0): return Himage
    try:
        weather = data_store.weather.copy()
        calendar_events = list(data_store.calendar_events)
        tasks_items = list(data_store.tasks_items)
        claude = data_store.claude.copy()
        aqi = data_store.aqi
    finally:
        data_store.lock.release()

    dt = datetime.now()
    now_utc = datetime.now(timezone.utc)
    today_date = dt.date()
    months_default = ['January','February','March','April','May','June','July','August','September','October','November','December']
    months_gen = STRINGS.get('months_genitive', STRINGS.get('months', months_default))
    weekdays_list = STRINGS.get('weekdays', ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])
    weekdays_full = STRINGS.get('weekdays_full', ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])

    BAND_H = 54
    rail_w = 380
    c3x = 916
    c3w = total_width - c3x - 12
    mid_x = rail_w + 24
    mid_w = c3x - 24 - mid_x
    MID_FLOOR = 382
    row_h = 33

    # --- MASTHEAD (full-width black band) ---
    draw.rectangle((0, 0, total_width, BAND_H), fill='black')
    date_line = STRINGS.get('masthead_date', '{weekday} {day} {month}').format(
        weekday=weekdays_full[dt.weekday()], day=dt.day, month=months_gen[dt.month - 1]).upper()
    draw.text((20, 8), date_line, font=fonts['masthead'], fill='white')
    holiday = polish_holiday(today_date)
    if holiday:
        hx = max(445, 20 + fonts['masthead'].getlength(date_line) + 30)
        draw.text((hx, 12), holiday, font=fonts['holiday'], fill='yellow')

    # right-aligned chain: sunrise/sunset · moon · AQI
    rx = total_width - 20
    if aqi:
        aqi_s = f"AQI {aqi}"
        aw = fonts['strong'].getlength(aqi_s)
        if aqi >= 60:
            draw.rectangle((rx - aw - 10, 8, total_width - 12, BAND_H - 8), fill='red')
            draw.text((rx - aw - 2, 14), aqi_s, font=fonts['strong'], fill='white')
        else:
            draw.text((rx - aw, 14), aqi_s, font=fonts['strong'],
                      fill='yellow' if aqi >= 40 else 'white')
        rx -= aw + 44

    moon_names = STRINGS.get('moon_phases', [''] * 8)
    moon_idx = moon_phase_index(dt)
    moon_name = moon_names[moon_idx] if len(moon_names) >= 8 else ''
    moon_w = 32 + fonts['body_knock'].getlength(moon_name)
    draw_icon(draw, int(rx - moon_w), 15, f"icon_moon_phase_{moon_idx}", (24, 24), is_white=True)
    draw.text((rx - moon_w + 32, 14), moon_name, font=fonts['body_knock'], fill='white')
    rx -= moon_w + 44

    daily = weather.get('daily', {})
    d_sunrise = daily.get('sunrise', [])
    d_sunset = daily.get('sunset', [])
    sr_time = d_sunrise[0][11:16] if d_sunrise else '--:--'
    ss_time = d_sunset[0][11:16] if d_sunset else '--:--'
    sun_w = 36 + fonts['body_knock'].getlength(sr_time) + 38 + fonts['body_knock'].getlength(ss_time)
    sx = rx - sun_w
    draw_tri(draw, sx, 20, 13, up=True, fill='yellow')
    draw.text((sx + 18, 14), sr_time, font=fonts['body_knock'], fill='white')
    sx2 = sx + 18 + fonts['body_knock'].getlength(sr_time) + 20
    draw_tri(draw, sx2, 20, 13, up=False, fill='yellow')
    draw.text((sx2 + 18, 14), ss_time, font=fonts['body_knock'], fill='white')

    # --- LEFT RAIL (current weather) ---
    if 'current' in weather:
        cur = weather['current']
        temp = cur.get('temperature_2m', 0)
        hum = cur.get('relative_humidity_2m', 0)
        pres = cur.get('surface_pressure', 0)
        w_code = cur.get('weather_code', 0)
        is_day = cur.get('is_day', 1)

        ry = BAND_H + 10 + 108 + 8  # below next event box (64+108+8=180)
        draw_icon(draw, 20, ry + 8, get_weather_icon(w_code, is_day), (70, 70))
        # hero temperature: big number + degree at ~40% size, raised
        temp_s = f"{math.floor(temp + 0.5)}"
        hx, hy = 100, ry - 14
        draw.text((hx, hy), temp_s, font=fonts['hero'], fill='black')
        nb = draw.textbbox((hx, hy), temp_s, font=fonts['hero'])
        draw.text((nb[2] + 4, nb[1] - 6), '°', font=fonts['hero_deg'], fill='black')

        uvx = min(rail_w - 70, nb[2] + 44)
        draw.text((uvx + 6, ry - 8), 'UV', font=fonts['small'], fill='black')
        uv_rounded = math.floor(cur.get('uv_index', 0.0) + 0.5)
        uv_s = str(uv_rounded)
        uw = fonts['uv'].getlength(uv_s)
        if uv_rounded >= 6:
            draw.rectangle((uvx - 4, ry + 14, uvx + 44, ry + 56), fill='red')
            draw.text((uvx - 4 + (48 - uw) / 2, ry + 14), uv_s, font=fonts['uv'], fill='white')
        else:
            draw.text((uvx - 4 + (48 - uw) / 2, ry + 14), uv_s, font=fonts['uv'], fill='black')

        ly = ry + 116
        draw.text((20, ly), STRINGS.get('humidity', 'Humidity: {hum}%').format(hum=hum),
                  font=fonts['body'], fill='black')
        draw.text((20, ly + 32), STRINGS.get('pressure', 'Press: {pres} hPa').format(pres=round(pres)),
                  font=fonts['body'], fill='black')
        wind_spd = cur.get('wind_speed_10m', 0)
        wind_deg = cur.get('wind_direction_10m', 0)
        draw_icon(draw, 20, ly + 66, 'icon_wind', (26, 26))
        draw.text((52, ly + 64), f"{math.floor(wind_spd + 0.5)} km/h {wind_dir_label(wind_deg)}",
                  font=fonts['body'], fill='black')

    draw.line((rail_w + 8, BAND_H + 10, rail_w + 8, MID_FLOOR), fill='black', width=1)

    # next event at top of left rail
    if ENABLE_CALENDAR and calendar_events:
        draw_next_event_rail(draw, fonts, 0, BAND_H + 10, rail_w,
                             calendar_events[0], now_utc, today_date)

    # --- MIDDLE (calendar + tasks, flow layout) ---
    y = BAND_H + 12
    if ENABLE_CALENDAR:
        draw_tracked(draw, (mid_x, y), STRINGS.get('calendar_title', 'UPCOMING'),
                     fonts['label'], 'black')
        y += 42
        if calendar_events:
            reserve = (row_h * min(len(tasks_items), 2) + 6) if (ENABLE_TASKS and tasks_items) else 0
            for ev in calendar_events:
                if y + row_h > MID_FLOOR - reserve:
                    break
                dt_ev = ev.get('dt')
                soon = (not ev.get('allday', True) and dt_ev is not None and
                        0 <= (dt_ev - now_utc).total_seconds() <= 10800)
                color = 'red' if soon else 'black'
                sq_color = 'black' if ev['calendar'] == 'personal' else 'yellow'
                draw.rectangle([mid_x + 2, y + 7, mid_x + 16, y + 21], fill=sq_color, outline='black')
                delta = (ev['event_date'] - today_date).days
                if delta == 0:
                    day_label = STRINGS.get('calendar_today', 'today')
                elif delta == 1:
                    day_label = STRINGS.get('calendar_tomorrow', 'tomorrow')
                else:
                    day_label = f"+{delta}"
                draw.text((mid_x + 28, y + 2), day_label.upper(), font=fonts['cal_day'], fill=color)
                if not ev.get('allday'):
                    draw.text((mid_x + 122, y), dt_ev.astimezone().strftime('%H:%M'),
                              font=fonts['cal_time'], fill=color)
                draw.text((mid_x + 200, y), fit_text(ev['title'], fonts['body'], mid_w - 206),
                          font=fonts['body'], fill=color)
                y += row_h
        else:
            draw.text((mid_x, y), STRINGS.get('calendar_empty', 'No upcoming events'),
                      font=fonts['body'], fill='black')
            y += row_h

    if ENABLE_TASKS:
        if tasks_items:
            y += 6
            for task in tasks_items:
                if y + row_h > MID_FLOOR:
                    break
                draw.rectangle([mid_x + 2, y + 7, mid_x + 16, y + 21], outline='black', width=2)
                due = task.get('due', '')
                tx = mid_x + 28
                if due:
                    draw.text((tx, y + 2), due.upper(), font=fonts['cal_day'], fill='black')
                    tx = mid_x + 122
                draw.text((tx, y + 1), fit_text(task['title'], fonts['body22'], mid_x + mid_w - tx - 6),
                          font=fonts['body22'], fill='black')
                y += row_h

    # --- FORECAST STRIP (bottom, rail + middle width) ---
    d_times = daily.get('time', [])
    if d_times:
        d_tmax = daily.get('temperature_2m_max', [])
        d_tmin = daily.get('temperature_2m_min', [])
        d_codes = daily.get('weather_code', [])
        d_rain = daily.get('precipitation_probability_max', [])
        sy = 390
        draw.line((20, sy, c3x - 24, sy), fill='black', width=1)
        n_days = min(FORECAST_DAYS, len(d_times) - 1)
        strip_w = c3x - 24 - 20
        cell_w = strip_w // max(n_days, 1)
        icon_sz = 40
        for slot in range(n_days):
            i = slot + 1  # skip today (index 0)
            ox = 20 + slot * cell_w
            try:
                day_dt = datetime.strptime(d_times[i], "%Y-%m-%d")
                day_label = weekdays_list[day_dt.weekday()]
            except Exception:
                day_label = d_times[i][-5:] if d_times[i] else ''
            draw_tracked(draw, (ox + 12, sy + 8), day_label.upper(), fonts['fc_day'], 'black')
            rain = int(d_rain[i]) if i < len(d_rain) and d_rain[i] is not None else 0
            if rain >= 30:
                rc = 'red' if rain >= 60 else 'black'
                rain_s = f"{rain}%"
                px = ox + cell_w - 12 - fonts['fc_rain'].getlength(rain_s)
                draw_drop(draw, int(px - 16), sy + 12, 11, fill=rc)
                draw.text((px, sy + 8), rain_s, font=fonts['fc_rain'], fill=rc)
            draw_icon(draw, ox + 12, sy + 36,
                      get_weather_icon(d_codes[i] if i < len(d_codes) else 0, 1), (icon_sz, icon_sz))
            tx = ox + 12 + icon_sz + 10
            tmax = math.floor(d_tmax[i] + 0.5) if i < len(d_tmax) else 0
            tmin = math.floor(d_tmin[i] + 0.5) if i < len(d_tmin) else 0
            draw.text((tx, sy + 34), f"{tmax}°", font=fonts['fc_hi'], fill='black')
            draw.text((tx, sy + 64), f"{tmin}°", font=fonts['fc_lo'], fill='black')

    # --- COLUMN 3 (messages preempt fallback cards top-down) ---
    draw.line((c3x - 12, BAND_H + 10, c3x - 12, 470), fill='black', width=1)
    SLOT_H, SLOT_GAP = 130, 6
    messages = read_messages()[:3]
    cards = []
    if ENABLE_CLAUDE:
        cards.append(('claude', claude))
    cards = cards[:max(0, 3 - len(messages))]
    slots = cards + [('msg', m) for m in messages]
    for i, (kind, payload) in enumerate(slots[:3]):
        top = BAND_H + 10 + i * (SLOT_H + SLOT_GAP)
        if kind == 'claude':
            draw_claude_card(draw, fonts, c3x, c3w, top, SLOT_H, payload, separator=(i > 0))
        else:
            draw_message_slot(draw, fonts, c3x, c3w, top, SLOT_H, payload)

    return Himage


# --- MAIN LOOP ---
def main():
    auth_google()
    auth_claude()

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.signal(signal.SIGUSR1, refresh_signal_handler)
    epd = None

    # Start data thread early so weather/data loads during EPD init+clear (~17s)
    t_data = threading.Thread(target=update_data_thread)
    t_data.daemon = True
    t_data.start()

    try:
        epd = epd10in85g.EPD()
        epd.Init()
        epd.Clear()
        epd.PowerOff()

        # Wait for initial weather load before first render (up to 45s)
        data_store.data_changed.wait(timeout=45)

        def load_font(name, size):
            return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

        # Direction C — Brutalist poster (Archivo family)
        AR_BLK = 'ArchivoBlack-Regular.ttf'
        AR_NB = 'ArchivoNarrow-Bold.ttf'
        AR_R = 'Archivo-Regular.ttf'
        AR_M = 'Archivo-Medium.ttf'
        AR_SB = 'Archivo-SemiBold.ttf'
        fonts = {
            'masthead':    load_font(AR_BLK, 32),  # date on black
            'holiday':     load_font(AR_NB, 28),   # holiday name on black
            'label':       load_font(AR_NB, 24),   # tracked caps labels
            'label_knock': load_font(AR_NB, 24),   # labels on black (26 clips Ę into separator)
            'hero':        load_font(AR_BLK, 130), # temperature number
            'hero_deg':    load_font(AR_BLK, 52),  # raised degree sign
            'next_time':   load_font(AR_BLK, 44),  # NASTĘPNE time
            'cal_time':    load_font(AR_NB, 26),   # calendar times
            'cal_day':     load_font(AR_NB, 24),   # DZIŚ/JUTRO/+N column (red rows >= 24px)
            'fc_day':      load_font(AR_NB, 24),   # forecast day abbrevs
            'fc_hi':       load_font(AR_BLK, 30),  # forecast hi temps
            'fc_lo':       load_font(AR_R, 22),    # forecast lo temps
            'fc_rain':     load_font(AR_NB, 24),   # rain % (red >= 24px)
            'body':        load_font(AR_R, 24),    # event titles, weather details
            'body22':      load_font(AR_R, 22),    # message body, tasks
            'body_knock':  load_font(AR_M, 23),    # body on black (bumped)
            'strong':      load_font(AR_SB, 24),   # message header, AQI
            'uv':          load_font(AR_BLK, 36),  # UV value
            'small':       load_font(AR_R, 20),    # timestamps, bar subs
            'small_knock': load_font(AR_M, 20),    # small on black (bumped)
        }

        refresh_counter = 0
        MIN_REFRESH_INTERVAL = 900   # 15 min — skip if nothing changed
        MSG_REFRESH_INTERVAL = 60    # minimum between message-triggered refreshes
        last_render_fingerprint = None

        while True:
            start_time = time.time()
            try:
                signal.alarm(90)
                image = render_screen(epd, fonts)
                image.save('/tmp/dashboard_debug.png')
                buf = epd.getbuffer(image)

                if refresh_counter >= 600:
                    logging.info("Full Refresh with Clear")
                    epd.sleep()   # release GPIO/SPI for clean reinit
                    epd.Init()
                    epd.Clear()
                    epd.display(buf)
                    refresh_counter = 0
                else:
                    logging.info("Full Refresh")
                    epd.PowerOn()
                    epd.display(buf)
                    refresh_counter += 1

                epd.PowerOff()
                signal.alarm(0)
                last_render_fingerprint = get_data_fingerprint(data_store)
                del image
                del buf
                if refresh_counter % 10 == 0: gc.collect()

            except HardwareTimeoutError:
                logging.critical("HARDWARE HANG DETECTED!")
                signal.alarm(0)
                logging.shutdown()
                os.execv(sys.executable, ['python'] + sys.argv)
            except OSError as e:
                signal.alarm(0)
                if e.errno == 24:
                    os.execv(sys.executable, ['python'] + sys.argv)
            except Exception as e:
                signal.alarm(0)
                logging.error(f"Unexpected error in main: {e}")

            data_store.data_changed.clear()
            refresh_event.clear()

            while True:
                elapsed = time.time() - start_time
                if refresh_event.is_set():
                    if elapsed >= MSG_REFRESH_INTERVAL:
                        refresh_event.clear()
                        break
                if elapsed >= MIN_REFRESH_INTERVAL:
                    if get_data_fingerprint(data_store) != last_render_fingerprint:
                        break
                    start_time = time.time()  # nothing changed — wait another interval
                remaining = max(0, MIN_REFRESH_INTERVAL - (time.time() - start_time))
                data_store.data_changed.wait(timeout=min(remaining, 1.0))
                data_store.data_changed.clear()

    except KeyboardInterrupt:
        try:
            signal.alarm(0)
            epd10in85g.epdconfig.module_exit(cleanup=True)  # epdconfig_g imported as epdconfig in driver
        except:
            pass
        exit()


if __name__ == '__main__':
    main()
