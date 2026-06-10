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
import urllib.parse
import tomllib
from collections import deque
from datetime import datetime, timezone
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

# --- LOCAL SETTINGS ---
_cfg_path = os.path.join(BASE_DIR, 'settings_local.toml')
try:
    with open(_cfg_path, 'rb') as _f:
        _cfg = tomllib.load(_f)
    _w = _cfg.get('widgets', {})
    ENABLE_STRAVA      = _w.get('enable_strava', False)
    ENABLE_BAMBU       = _w.get('enable_bambu', False)
    ENABLE_CALENDAR    = _w.get('enable_calendar', False)
    ENABLE_ANTIGRAVITY = _w.get('enable_antigravity', False)
    ENABLE_CLAUDE      = _w.get('enable_claude', False)
    ENABLE_SPOTIFY     = _w.get('enable_spotify', False)
    _loc = _cfg.get('location', {})
    LOCATION_LAT = _loc.get('lat', 44.8240855)
    LOCATION_LON = _loc.get('lon', 20.4934273)
    _p = _cfg.get('printer', {})
    PRINTER_CONF = {'IP': _p.get('ip', ''), 'SERIAL': _p.get('serial', ''), 'ACCESS_CODE': _p.get('access_code', '')}
    _lfm = _cfg.get('lastfm', {})
    LASTFM_CONF = {'API_KEY': _lfm.get('api_key', ''), 'USERNAME': _lfm.get('username', '')}
    LANGUAGE = _cfg.get('display', {}).get('language', 'en')
    FORECAST_DAYS = _cfg.get('weather', {}).get('forecast_days', 5)
except FileNotFoundError:
    ENABLE_STRAVA = False
    ENABLE_BAMBU = False
    ENABLE_CALENDAR = False
    ENABLE_ANTIGRAVITY = False
    ENABLE_CLAUDE = False
    ENABLE_SPOTIFY = False
    LOCATION_LAT = 49.6790190
    LOCATION_LON = 20.5495183
    PRINTER_CONF = {'IP': '', 'SERIAL': '', 'ACCESS_CODE': ''}
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
    'weather': 'https://api.open-meteo.com/v1/forecast',
    'strava_token': 'https://www.strava.com/oauth/token',
    'strava_auth': 'https://www.strava.com/oauth/authorize',
    'strava_activities': 'https://www.strava.com/api/v3/athlete/activities',
    'btc': 'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart',
    'eth': 'https://api.coingecko.com/api/v3/coins/ethereum/market_chart',
    'lastfm': 'http://ws.audioscrobbler.com/2.0/'
}

STRAVA_CONF = {
    'TOKEN_FILE': os.path.join(BASE_DIR, 'strava_token.json')
}

# --- FILES & SCOPES ---
GMAIL_TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')
GOOGLE_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar.readonly',
]

if os.path.exists(LIB_DIR):
    sys.path.append(LIB_DIR)
    epd_dir = os.path.join(LIB_DIR, 'waveshare_epd')
    if os.path.exists(epd_dir):
        sys.path.insert(0, epd_dir)

try:
    import epd10in85g
    import bambulabs_api as bl
except ImportError:
    pass

# --- LOGGING ---
logging.getLogger("bambulabs_api").setLevel(logging.CRITICAL)
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
global_printer = None
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
        self.strava = {
            'rides': 0, 'total_distance': 0,
            'rides_curr': 0, 'distance_curr': 0,
            'rides_prev': 0, 'distance_prev': 0,
            'bike_total': 0, 'hike_total': 0
        }
        self.printer = {'status': 'OFFLINE'}
        self.gmail_unread = 0
        self.spotify = {'status': 'PAUSED', 'text': '', 'cover': None}
        self.claude = {'error': False, 'five_hour': {}, 'seven_day': {}}
        self.antigravity = {'error': False, 'models': []}
        self.calendar_events = []
        self.sysload = {'cpu': 0, 'ram_free': 0, 'history': deque(maxlen=30)}
        self.crypto = {'btc': 0, 'eth': 0, 'btc_hist': [], 'eth_hist': []}
        self.ping = {'current': 0, 'history': deque(maxlen=50)}

        self.last_update = {
            'weather': 0, 'strava': 0, 'printer': 0, 'gmail': 0,
            'spotify': 0, 'crypto': 0, 'sysload': 0, 'ping': 0,
            'claude': 0, 'antigravity': 0, 'calendar': 0,
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
            ds.printer.get('status'),
            str(ds.calendar_events),
            ds.spotify.get('status'),
            ds.spotify.get('text'),
            ds.claude.get('five_hour', {}).get('utilization'),
            ds.claude.get('seven_day', {}).get('utilization'),
            str(ds.antigravity.get('models', [])),
        )


# --- HELPERS ---
def fetch_with_retry(url, retries=3, delay=5):
    for attempt in range(retries):
        data = net.get_json(url)
        if data:
            return data
        if attempt < retries - 1:
            time.sleep(delay)
    return None


def ping_printer(ip):
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '1', ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except:
        return False


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


def auth_antigravity():
    global ENABLE_ANTIGRAVITY
    if not ENABLE_ANTIGRAVITY: return
    try:
        import antigravity
        success = antigravity.interactive_auth()
        if not success:
            ENABLE_ANTIGRAVITY = False
            print("Antigravity widget is disabled.")
    except ImportError:
        print("antigravity.py not found. Antigravity widget disabled.")
        ENABLE_ANTIGRAVITY = False


def auth_strava():
    global ENABLE_STRAVA
    if not ENABLE_STRAVA: return

    if os.path.exists(STRAVA_CONF['TOKEN_FILE']):
        return

    print("\n--- STRAVA CONFIGURATION REQUIRED ---")
    c_id = input("Enter Strava Client ID (or press Enter to disable): ").strip()
    if not c_id:
        print("Strava is disabled. Fallback widget (System Load) will be used.\n")
        ENABLE_STRAVA = False
        return

    c_secret = input("Enter Strava Client Secret: ").strip()

    auth_url = (
        f"{API_ENDPOINTS['strava_auth']}?"
        f"client_id={c_id}&"
        f"response_type=code&"
        f"redirect_uri=http://localhost&"
        f"approval_prompt=force&"
        f"scope=activity:read_all"
    )

    print("\n[!] To get a token with the correct permissions, open this link in your browser:\n")
    print(f"--> {auth_url} <--\n")
    print("Click 'Authorize'. You will be redirected to an empty/error page (localhost).")
    print("Look at the address bar. Copy the 'code' parameter.")

    code_input = input("Enter the 'code' from the URL (or paste the full URL): ").strip()

    if not code_input:
        print("Authorization cancelled. Strava is disabled.\n")
        ENABLE_STRAVA = False
        return

    if 'code=' in code_input:
        try:
            parsed = urllib.parse.urlparse(code_input)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get('code', [code_input])[0]
        except:
            code = code_input.split('code=')[1].split('&')[0]
    else:
        code = code_input

    print("Fetching Access Token...")
    data = {'client_id': c_id, 'client_secret': c_secret, 'code': code, 'grant_type': 'authorization_code'}

    try:
        resp = requests.post(API_ENDPOINTS['strava_token'], data=data)
        resp.raise_for_status()
        token_data = resp.json()
        token_data['client_id'] = c_id
        token_data['client_secret'] = c_secret

        with open(STRAVA_CONF['TOKEN_FILE'], 'w') as f:
            json.dump(token_data, f, indent=4)
        print("Strava Authorization Successful!\n")
    except Exception as e:
        print(f"Failed to fetch Strava tokens: {e}")
        ENABLE_STRAVA = False


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


def fetch_strava_data():
    if not os.path.exists(STRAVA_CONF['TOKEN_FILE']): return None
    with open(STRAVA_CONF['TOKEN_FILE'], 'r') as f:
        token_data = json.load(f)

    c_id = token_data.get('client_id')
    c_secret = token_data.get('client_secret')

    if time.time() > token_data.get('expires_at', 0):
        data = {'client_id': c_id, 'client_secret': c_secret, 'grant_type': 'refresh_token',
                'refresh_token': token_data.get('refresh_token')}
        new_token = net.get_json(API_ENDPOINTS['strava_token'], data=data, method='POST')
        if new_token and 'access_token' in new_token:
            new_token['client_id'] = c_id
            new_token['client_secret'] = c_secret
            token_data = new_token
            with open(STRAVA_CONF['TOKEN_FILE'], 'w') as f:
                json.dump(token_data, f, indent=4)
        else:
            return None

    access_token = token_data['access_token']

    now_year = datetime.now().year
    start_curr_ts = datetime(now_year, 1, 1).timestamp()
    start_prev_ts = datetime(now_year - 1, 1, 1).timestamp()
    end_prev_ts = datetime(now_year - 1, 12, 31, 23, 59, 59).timestamp()

    page = 1
    total_rides, total_dist = 0, 0
    rides_curr, dist_curr = 0, 0
    rides_prev, dist_prev = 0, 0
    bike_total, hike_total = 0, 0

    headers = {"Authorization": f"Bearer {access_token}"}

    while True:
        url = f"{API_ENDPOINTS['strava_activities']}?page={page}&per_page=100"
        activities = net.get_json(url, headers=headers)
        if not activities: break

        for act in activities:
            t = act.get('type')
            d = act.get('distance', 0)
            act_time = datetime.strptime(act['start_date'], "%Y-%m-%dT%H:%M:%SZ").timestamp()

            if t in ['Ride', 'VirtualRide', 'EBikeRide', 'GravelRide', 'MountainBikeRide']:
                total_rides += 1
                total_dist += d
                bike_total += d
                if act_time >= start_curr_ts:
                    rides_curr += 1
                    dist_curr += d
                elif start_prev_ts <= act_time <= end_prev_ts:
                    rides_prev += 1
                    dist_prev += d
            elif t in ['Hike', 'Walk']:
                hike_total += d

        if len(activities) < 100: break
        page += 1

    return {
        "rides": total_rides,
        "total_distance": round(total_dist / 1000, 1),
        "rides_curr": rides_curr,
        "distance_curr": round(dist_curr / 1000, 1),
        "rides_prev": rides_prev,
        "distance_prev": round(dist_prev / 1000, 1),
        "bike_total": round(bike_total / 1000, 1),
        "hike_total": round(hike_total / 1000, 1)
    }




def update_data_thread():
    global global_printer

    if ENABLE_BAMBU:
        try:
            global_printer = bl.Printer(PRINTER_CONF['IP'], PRINTER_CONF['ACCESS_CODE'], PRINTER_CONF['SERIAL'])
        except Exception as e:
            logging.error(f"Bambu init error: {e}")
            global_printer = None

    is_connected = False

    while True:
        now = time.time()

        if now - data_store.last_update['weather'] > 600:
            weather_url = f"{API_ENDPOINTS['weather']}?latitude={LOCATION_LAT}&longitude={LOCATION_LON}&current=temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m,weather_code,is_day,uv_index&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=auto&forecast_days={FORECAST_DAYS}"
            w_data = fetch_with_retry(weather_url)
            if w_data:
                with data_store.lock:
                    data_store.weather = w_data
                data_store.last_update['weather'] = now

        if ENABLE_STRAVA:
            if now - data_store.last_update['strava'] > 900:
                s_data = fetch_strava_data()
                if s_data:
                    with data_store.lock: data_store.strava = s_data
                data_store.last_update['strava'] = now

        if ENABLE_BAMBU:
            update_interval = 5 if is_connected else 15
            if now - data_store.last_update['printer'] > update_interval:
                is_alive = ping_printer(PRINTER_CONF['IP'])
                if is_alive:
                    try:
                        if not is_connected and global_printer:
                            global_printer.connect()
                            time.sleep(1)
                            is_connected = True
                        if global_printer:
                            status = global_printer.get_state()
                            if status and status != "UNKNOWN":
                                with data_store.lock:
                                    data_store.printer = {
                                        'status': status,
                                        'percentage': global_printer.get_percentage(),
                                        'remaining_time': global_printer.get_time(),
                                        'layers': f"{global_printer.current_layer_num()}/{global_printer.total_layer_num()}"
                                    }
                    except Exception as e:
                        is_connected = False
                        with data_store.lock:
                            data_store.printer['status'] = 'OFFLINE'
                        try:
                            if global_printer: global_printer.disconnect()
                        except:
                            pass
                else:
                    if is_connected:
                        is_connected = False
                        try:
                            global_printer.disconnect()
                        except:
                            pass
                    with data_store.lock:
                        data_store.printer['status'] = 'OFFLINE'
                data_store.last_update['printer'] = now
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
                            is_allday = 'T' not in start
                            try:
                                if is_allday:
                                    dt_ev = datetime.strptime(start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                                    event_date = datetime.strptime(start, '%Y-%m-%d').date()
                                else:
                                    dt_ev = datetime.fromisoformat(start.replace('Z', '+00:00'))
                                    event_date = dt_ev.astimezone().date()
                            except Exception:
                                dt_ev = datetime.now(timezone.utc)
                                event_date = dt_ev.date()
                                is_allday = True
                            all_events.append({
                                'title': ev.get('summary', '?'),
                                'calendar': cal_type,
                                'dt': dt_ev,
                                'event_date': event_date,
                                'allday': is_allday,
                            })
                    all_events.sort(key=lambda e: e['dt'])
                    with data_store.lock: data_store.calendar_events = all_events[:8]
            except Exception as e:
                logging.error(f"Calendar error: {e}")
            data_store.last_update['calendar'] = now

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

        if ENABLE_ANTIGRAVITY and now - data_store.last_update['antigravity'] > 60:
            try:
                subprocess.run([sys.executable, os.path.join(BASE_DIR, 'antigravity.py')], capture_output=True, timeout=30)
                limits_path = os.path.join(BASE_DIR, 'limits.json')
                if os.path.exists(limits_path):
                    with open(limits_path, 'r', encoding='utf-8') as f:
                        limits_data = json.load(f)
                    with data_store.lock:
                        data_store.antigravity = limits_data
                        if "error" in limits_data:
                            data_store.antigravity['error'] = True
                        else:
                            data_store.antigravity['error'] = False
                else:
                    with data_store.lock:
                        data_store.antigravity['error'] = True
            except Exception as e:
                logging.error(f"Antigravity update error: {e}")
                with data_store.lock:
                    data_store.antigravity['error'] = True
            data_store.last_update['antigravity'] = now

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


def render_screen(epd, fonts):
    total_width = epd.width * 2
    Himage = Image.new('RGB', (total_width, epd.height), 'white')
    draw = ImageDraw.Draw(Himage)

    if not data_store.lock.acquire(timeout=2.0): return Himage
    try:
        weather = data_store.weather.copy()
        strava = data_store.strava.copy()
        printer = data_store.printer.copy()
        gmail_unread = data_store.gmail_unread
        calendar_events = list(data_store.calendar_events)
        spotify = data_store.spotify.copy()
        claude = data_store.claude.copy()
        antigravity = data_store.antigravity.copy()
    finally:
        data_store.lock.release()

    dt = datetime.now()
    months = STRINGS.get('months', ['January','February','March','April','May','June','July','August','September','October','November','December'])
    weekdays_list = STRINGS.get('weekdays', ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'])
    col_w = total_width // 3

    # --- CALENDAR (spans col1 + col2) ---
    col1_x = 20
    y_cal_div = 65

    weekdays_full = STRINGS.get('weekdays_full', ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])
    cal_line = f"{dt.year} - {months[dt.month - 1]}  ·  {dt.day} - {weekdays_full[dt.weekday()]}"
    cal_max_w = col_w * 2 - col1_x - 20
    cal_max_h = y_cal_div - 20
    def fit_cal_font(text):
        size = cal_max_h
        while size > 8:
            f = fonts['cal_font_cache'].get(size) or ImageFont.truetype(
                os.path.join(FONT_DIR, 'Doto-Bold.ttf'), size)
            fonts['cal_font_cache'][size] = f
            bb = draw.textbbox((0, 0), text, font=f)
            if (bb[2] - bb[0]) <= cal_max_w and (bb[3] - bb[1]) <= cal_max_h:
                return f
            size -= 1
        return fonts['cal_font_cache'][8]
    f_cal = fit_cal_font(cal_line)
    bb_cal = draw.textbbox((0, 0), cal_line, font=f_cal)
    cal_text_h = bb_cal[3] - bb_cal[1]
    cal_text_y = max(0, 10 + (y_cal_div - 10 - cal_text_h) // 2 - 25)
    draw.text((col1_x, cal_text_y), cal_line, font=f_cal, fill="black")

    draw.line((col1_x, y_cal_div, col_w * 2 - 20, y_cal_div), fill="black", width=2)

    # --- COLUMN 1 (Weather) ---
    if 'current' in weather:
        cur = weather['current']
        temp = cur.get('temperature_2m', 0)
        hum = cur.get('relative_humidity_2m', 0)
        pres = cur.get('surface_pressure', 0)
        w_code = cur.get('weather_code', 0)
        is_day = cur.get('is_day', 1)
        uv_index = cur.get('uv_index', 0.0)

        temp_rounded = math.floor(temp + 0.5)

        draw_icon(draw, col1_x, y_cal_div, get_weather_icon(w_code, is_day), (90, 90))
        draw.text((col1_x + 100, y_cal_div), f"{temp_rounded}°C", font=fonts['80'], fill="black")

        uv_x, uv_y = col1_x + 310, y_cal_div + 5
        uv_rounded = math.floor(uv_index + 0.5)
        draw.text((uv_x, uv_y), "UV", font=fonts['28'], fill="black")
        uv_val_str = str(uv_rounded)
        try:
            bbox = draw.textbbox((0, 0), uv_val_str, font=fonts['60'])
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(uv_val_str, font=fonts['60'])

        uv_val_x, uv_val_y = uv_x + 45, y_cal_div
        if uv_rounded >= 6:
            pad = 5
            draw.rectangle((uv_val_x - pad, uv_val_y - pad + 10, uv_val_x + tw + pad, uv_val_y + th + pad), fill="black")
            draw.text((uv_val_x, uv_val_y), uv_val_str, font=fonts['60'], fill="white")
        else:
            draw.text((uv_val_x, uv_val_y), uv_val_str, font=fonts['60'], fill="black")

        draw.text((col1_x + 100, y_cal_div + 90), STRINGS.get('humidity', 'Humidity: {hum}%').format(hum=hum), font=fonts['20'], fill="black")
        draw.text((col1_x + 100, y_cal_div + 115), STRINGS.get('pressure', 'Press: {pres} hPa').format(pres=pres), font=fonts['20'], fill="black")

        draw.line((col1_x, 210, col_w - 20, 210), fill="black", width=2)

        daily = weather.get('daily', {})
        d_times = daily.get('time', [])
        d_tmax = daily.get('temperature_2m_max', [])
        d_tmin = daily.get('temperature_2m_min', [])
        d_codes = daily.get('weather_code', [])

        n_days = min(FORECAST_DAYS, len(d_times))
        slot_w = (col_w - 40) // max(n_days, 1)
        icon_sz = min(50, slot_w - 10)
        f_y = 220
        for i in range(n_days):
            off_x = col1_x + (i * slot_w)
            try:
                day_dt = datetime.strptime(d_times[i], "%Y-%m-%d")
                day_label = weekdays_list[day_dt.weekday()]
            except Exception:
                day_label = d_times[i][-5:] if d_times[i] else ''
            draw.text((off_x + 4, f_y), day_label, font=fonts['20'], fill="black")
            draw_icon(draw, off_x + 4, f_y + 24, get_weather_icon(d_codes[i] if i < len(d_codes) else 0, 1), (icon_sz, icon_sz))
            tmax = math.floor(d_tmax[i] + 0.5) if i < len(d_tmax) else 0
            tmin = math.floor(d_tmin[i] + 0.5) if i < len(d_tmin) else 0
            draw.text((off_x + 4, f_y + 24 + icon_sz + 2), f"{tmax}°", font=fonts['20'], fill="black")
            draw.text((off_x + 4, f_y + 24 + icon_sz + 20), f"{tmin}°", font=fonts['20'], fill="black")

    draw.line((col_w, y_cal_div, col_w, 470), fill="black", width=2)

    # --- COLUMN 2 (Widgets) ---
    col2_x = col_w + 20

    if ENABLE_STRAVA:
        y1 = y_cal_div + 15
        draw_icon(draw, col2_x, y1, "icon_strava", (60, 60))
        draw.text((col2_x + 70, y1), STRINGS.get('strava_title', 'STRAVA STATS'), font=fonts['28'], fill="black")

        draw.text((col2_x + 70, y1 + 35),
                  STRINGS.get('strava_year_stats', '{year}: {dist} km | {prev_year}: {prev_dist} km').format(
                      year=dt.year, dist=strava.get('distance_curr', 0),
                      prev_year=dt.year - 1, prev_dist=strava.get('distance_prev', 0)),
                  font=fonts['20'], fill="black")
        draw.text((col2_x + 70, y1 + 60),
                  STRINGS.get('strava_total', 'Total: {dist} km | {rides} acts').format(
                      dist=strava.get('total_distance', 0), rides=strava.get('rides', 0)),
                  font=fonts['20'], fill="black")

        draw_icon(draw, col2_x + 70, y1 + 85, "icon_bike", (30, 30))
        draw.text((col2_x + 105, y1 + 90), f"{strava.get('bike_total', 0)} km", font=fonts['20'], fill="black")

        draw_icon(draw, col2_x + 220, y1 + 85, "icon_hike", (30, 30))
        draw.text((col2_x + 255, y1 + 90), f"{strava.get('hike_total', 0)} km", font=fonts['20'], fill="black")

        draw.line((col2_x, 165, col_w * 2 - 20, 165), fill="black", width=2)
        y2 = 185
    else:
        y2 = y_cal_div + 15

    if ENABLE_CALENDAR:
        draw.text((col2_x, y2), STRINGS.get('calendar_title', 'NADCHODZĄCE'), font=fonts['cal28'], fill="black")
        now_utc = datetime.now(timezone.utc)
        today_date = datetime.now().date()
        row_h = 27
        # Fixed column positions: [sq] [day_label] [HH:MM] [title]
        x_day   = col2_x + 18   # day label ("dziś", "jutro", "+3")
        x_time  = col2_x + 88   # HH:MM (fixed, blank for all-day)
        x_title = col2_x + 148  # event title
        ey = y2 + 35
        if calendar_events:
            for ev in calendar_events:
                if ey + row_h > 318:
                    break
                dt_ev = ev.get('dt')
                soon = (not ev.get('allday', True) and dt_ev is not None and
                        0 <= (dt_ev - now_utc).total_seconds() <= 10800)
                text_color = "red" if soon else "black"
                sq_color = "black" if ev['calendar'] == 'personal' else "yellow"
                draw.rectangle([col2_x + 2, ey + 5, col2_x + 13, ey + 16], fill=sq_color, outline="black")
                delta = (ev['event_date'] - today_date).days
                if delta == 0:
                    day_label = STRINGS.get('calendar_today', 'dziś')
                elif delta == 1:
                    day_label = STRINGS.get('calendar_tomorrow', 'jutro')
                else:
                    day_label = f"+{delta}"
                time_part = '' if ev.get('allday') else dt_ev.astimezone().strftime('%H:%M')
                draw.text((x_day, ey), day_label, font=fonts['cal20'], fill=text_color)
                if time_part:
                    draw.text((x_time, ey), time_part, font=fonts['cal20'], fill=text_color)
                title = ev['title']
                if len(title) > 22:
                    title = title[:21] + '…'
                draw.text((x_title, ey), title, font=fonts['cal20'], fill=text_color)
                if soon:
                    draw.text((x_day + 1, ey), day_label, font=fonts['cal20'], fill=text_color)
                    if time_part:
                        draw.text((x_time + 1, ey), time_part, font=fonts['cal20'], fill=text_color)
                    draw.text((x_title + 1, ey), title, font=fonts['cal20'], fill=text_color)
                ey += row_h
        else:
            draw.text((col2_x, ey), STRINGS.get('calendar_empty', 'Brak nadchodzących wydarzeń'), font=fonts['cal20'], fill="black")
    elif ENABLE_BAMBU:
        p_status = str(printer.get('status', 'OFFLINE')).upper()
        draw_icon(draw, col2_x, y2, "icon_3d", (60, 60))
        draw.text((col2_x + 70, y2), STRINGS.get('printer_title', 'PRINTER: {status}').format(status=p_status), font=fonts['28'], fill="black")
        if p_status not in ["OFFLINE", "UNKNOWN", "FINISH"]:
            percent = printer.get('percentage', 0)
            draw.rectangle((col2_x + 70, y2 + 40, col2_x + 400, y2 + 60), outline="black")
            draw.rectangle((col2_x + 70, y2 + 40, col2_x + 70 + int(330 * (percent / 100)), y2 + 60), fill="black")
            draw.text((col2_x + 70, y2 + 70),
                      f"{percent}% | Rem: {printer.get('remaining_time', '0')}m | {printer.get('layers', '0/0')} L",
                      font=fonts['20'], fill="black")

    draw.line((col2_x, 320, col_w * 2 - 20, 320), fill="black", width=2)

    y3 = 340
    if ENABLE_ANTIGRAVITY:
        draw_icon(draw, col2_x, y3, "icon_cpu", (50, 50))
        draw.text((col2_x + 60, y3), STRINGS.get('antigravity_title', 'ANTIGRAVITY USAGE'), font=fonts['28'], fill="black")

        if antigravity.get('error'):
            draw.text((col2_x + 60, y3 + 35), STRINGS.get('error_loading_data', 'Error loading data'), font=fonts['20'], fill="black")
        else:
            models = antigravity.get('models', [])
            opus = next((m for m in models if m.get('modelId') == 'claude-opus-4-6-thinking'), None)
            gemini = next((m for m in models if m.get('modelId') == 'gemini-3-pro-high'), None)

            y_off = y3 + 35
            for m_data in (opus, gemini):
                if m_data:
                    label = "Opus 4.6" if m_data.get('modelId') == 'claude-opus-4-6-thinking' else "Gemini 3Pro"
                    pct = m_data.get('usedPercentage', 0)
                    rem_time = time_until(m_data.get('resetDate'))

                    draw.text((col2_x + 60, y_off), STRINGS.get('antigravity_model', '{label} {pct}% | In {time}').format(label=label, pct=pct, time=rem_time), font=fonts['20'], fill="black")

                    bx, bw, bh = col2_x + 60, 330, 15
                    draw.rectangle((bx, y_off + 25, bx + bw, y_off + 25 + bh), outline="black", width=2)
                    fill_w = int((bw - 4) * min(pct / 100.0, 1.0))
                    if fill_w > 0: draw.rectangle((bx + 2, y_off + 27, bx + 2 + fill_w, y_off + 25 + bh - 2), fill="black")

                    y_off += 50

    draw.line((col_w * 2, 10, col_w * 2, 470), fill="black", width=2)

    # --- COLUMN 3 (Claude/Spotify/Progress, Gmail) ---
    col3_x = col_w * 2 + 30

    # 1. Claude AI OR Spotify OR Time Progress
    sp_y = 10
    # Clear background for widget
    draw.rectangle((col3_x, sp_y, col3_x + 420, sp_y + 130), fill="white")

    if ENABLE_CLAUDE:
        draw.text((col3_x, sp_y), STRINGS.get('claude_title', 'CLAUDE AI USAGE'), font=fonts['28'], fill="black")

        if claude.get('error'):
            draw.text((col3_x, sp_y + 50), STRINGS.get('claude_error', 'Claude Usage Error'), font=fonts['24'], fill="black")
        else:
            # 5-Hour Limit
            pct_5h = claude.get('five_hour', {}).get('utilization', 0)
            resets_5h = claude.get('five_hour', {}).get('resets_at')
            rem_5h = time_until(resets_5h)

            draw.text((col3_x, sp_y + 40), STRINGS.get('claude_5h', '5-Hour Limit: {pct}% (Resets in {time})').format(pct=pct_5h, time=rem_5h), font=fonts['20'], fill="black")
            bx, bw, bh = col3_x, 400, 15
            draw.rectangle((bx, sp_y + 65, bx + bw, sp_y + 65 + bh), outline="black", width=2)
            fill_w = int((bw - 4) * min(pct_5h / 100.0, 1.0))
            if fill_w > 0: draw.rectangle((bx + 2, sp_y + 67, bx + 2 + fill_w, sp_y + 65 + bh - 2), fill="black")

            # 7-Day Limit
            pct_7d = claude.get('seven_day', {}).get('utilization', 0)
            resets_7d = claude.get('seven_day', {}).get('resets_at')
            rem_7d = time_until(resets_7d)

            draw.text((col3_x, sp_y + 90), STRINGS.get('claude_7d', '7-Day Limit: {pct}% (Resets in {time})').format(pct=pct_7d, time=rem_7d), font=fonts['20'], fill="black")
            draw.rectangle((bx, sp_y + 115, bx + bw, sp_y + 115 + bh), outline="black", width=2)
            fill_w = int((bw - 4) * min(pct_7d / 100.0, 1.0))
            if fill_w > 0: draw.rectangle((bx + 2, sp_y + 117, bx + 2 + fill_w, sp_y + 115 + bh - 2), fill="black")

    elif ENABLE_SPOTIFY:
        if spotify['cover']:
            Himage.paste(spotify['cover'], (col3_x, sp_y))
        else:
            draw_icon(draw, col3_x, sp_y, "icon_spotify", (120, 120))

        status_ico = "icon_play" if spotify['status'] == 'PLAYING' else "icon_pause"
        draw_icon(draw, col3_x + 140, sp_y + 10, status_ico, (30, 30))

        if spotify['status'] == 'PLAYING':
            words = spotify['text'].split(' - ')
            artist = words[0] if len(words) > 0 else "Unknown"
            track = words[1] if len(words) > 1 else ""
            draw.text((col3_x + 180, sp_y + 10), artist[:20], font=fonts['28'], fill="black")
            draw.text((col3_x + 140, sp_y + 50), track[:25], font=fonts['24'], fill="black")

    else:
        # Fallback: Time Progress
        tp_y = sp_y
        draw.text((col3_x, tp_y), STRINGS.get('time_progress_title', 'TIME PROGRESS'), font=fonts['28'], fill="black")

        day_pct = (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400.0
        days_in_m = calendar.monthrange(dt.year, dt.month)[1]
        month_pct = (dt.day - 1 + (dt.hour / 24.0)) / days_in_m
        days_in_y = 366 if calendar.isleap(dt.year) else 365
        year_pct = (dt.timetuple().tm_yday - 1 + (dt.hour / 24.0)) / days_in_y

        def draw_prog(y_offset, label, pct):
            draw.text((col3_x, tp_y + y_offset), label, font=fonts['24'], fill="black")
            bx = col3_x + 110
            bw = 200
            bh = 20
            draw.rectangle((bx, tp_y + y_offset + 2, bx + bw, tp_y + y_offset + bh + 2), outline="black", width=2)
            if pct > 0:
                fill_w = int((bw - 4) * min(pct, 1.0))
                if fill_w > 0:
                    draw.rectangle((bx + 2, tp_y + y_offset + 4, bx + 2 + fill_w, tp_y + y_offset + bh), fill="black")
            draw.text((bx + bw + 15, tp_y + y_offset), f"{int(pct * 100)}%", font=fonts['24'], fill="black")

        draw_prog(40, STRINGS.get('label_day', 'DAY'), day_pct)
        draw_prog(75, STRINGS.get('label_month', 'MONTH'), month_pct)
        draw_prog(110, STRINGS.get('label_year', 'YEAR'), year_pct)

    draw.line((col3_x, 150, total_width - 20, 150), fill="black", width=2)

    # 2. Gmail
    gm_y = 170
    draw_icon(draw, col3_x, gm_y, "icon_mail", (60, 60))
    draw.text((col3_x + 80, gm_y + 10), STRINGS.get('gmail_unread', 'Unread Inbox: {count}').format(count=gmail_unread), font=fonts['35'], fill="black")

    return Himage


# --- MAIN LOOP ---
def main():
    auth_google()
    auth_strava()
    auth_claude()
    auth_antigravity()

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.signal(signal.SIGUSR1, refresh_signal_handler)
    epd = None

    try:
        epd = epd10in85g.EPD()
        epd.Init()
        epd.Clear()
        epd.PowerOff()

        def load_font(name, size):
            return ImageFont.truetype(os.path.join(FONT_DIR, name), size)

        fonts = {
            'cal_font_cache': {},
            '20': load_font('AtkinsonHyperlegible-Regular.ttf', 20),
            '24': load_font('AtkinsonHyperlegible-Regular.ttf', 24),
            '28': load_font('AtkinsonHyperlegible-Regular.ttf', 28),
            '32': load_font('AtkinsonHyperlegible-Regular.ttf', 32),
            '35': load_font('AtkinsonHyperlegible-Regular.ttf', 35),
            '40': load_font('AtkinsonHyperlegible-Regular.ttf', 40),
            '60': load_font('AtkinsonHyperlegible-Regular.ttf', 60),
            '80': load_font('AtkinsonHyperlegible-Regular.ttf', 80),
            'cal20': load_font('AtkinsonHyperlegible-Regular.ttf', 20),
            'cal28': load_font('AtkinsonHyperlegible-Bold.ttf', 28),
        }

        t_data = threading.Thread(target=update_data_thread)
        t_data.daemon = True
        t_data.start()

        refresh_counter = 0
        MIN_REFRESH_INTERVAL = 180

        while True:
            start_time = time.time()
            try:
                signal.alarm(90)
                image = render_screen(epd, fonts)
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
                    refresh_event.clear()
                    break
                if elapsed >= MIN_REFRESH_INTERVAL:
                    break
                remaining = MIN_REFRESH_INTERVAL - elapsed
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
