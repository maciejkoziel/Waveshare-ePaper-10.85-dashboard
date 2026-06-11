#!/usr/bin/python3
# -*- coding:utf-8 -*-
"""
Dashboard message server.
Listens for incoming messages and writes them to dashboard_message.json,
then signals main.py to trigger an immediate display refresh.

API:
  POST   /message        — set message (JSON body, see schema below)
  DELETE /message        — clear message
  GET    /message        — get current message

Message schema:
  {
    "header":       "ALERT",           // optional, displayed large at top
    "body":         "Dinner is ready", // main message text, word-wrapped
    "text_color":   "black",           // black | white | red | yellow
    "bg_color":     "white",           // black | white | red | yellow
    "border_color": "red",             // black | white | red | yellow | "" (none)
    "ttl":          3600               // seconds until auto-clear; 0 = persistent
  }

Configure port in settings_local.toml:
  [message_server]
  port = 5000
"""

import json
import os
import signal
import subprocess
import time
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE_DIR = os.path.dirname(os.path.realpath(__file__))
MESSAGE_FILE = os.path.join(BASE_DIR, 'dashboard_message.json')

try:
    with open(os.path.join(BASE_DIR, 'settings_local.toml'), 'rb') as _f:
        _cfg = tomllib.load(_f)
    PORT = _cfg.get('message_server', {}).get('port', 5000)
except FileNotFoundError:
    PORT = 5000

VALID_COLORS = {'black', 'white', 'red', 'yellow'}


def _notify_dashboard():
    try:
        result = subprocess.run(['pgrep', '-f', 'main.py'], capture_output=True, text=True)
        for pid in result.stdout.strip().split('\n'):
            if pid.strip():
                os.kill(int(pid.strip()), signal.SIGUSR1)
    except Exception:
        pass


def _read_message():
    try:
        with open(MESSAGE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _write_message(msg):
    with open(MESSAGE_FILE, 'w') as f:
        json.dump(msg, f)


def _clear_message():
    try:
        os.remove(MESSAGE_FILE)
    except FileNotFoundError:
        pass


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/message':
            msg = _read_message()
            if msg is None:
                self._send_json(404, {'error': 'no message'})
            else:
                self._send_json(200, msg)
        else:
            self._send_json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path not in ('/message', '/message/reset'):
            self._send_json(404, {'error': 'not found'})
            return

        if self.path == '/message/reset':
            _clear_message()
            _notify_dashboard()
            self._send_json(200, {'ok': True})
            return

        length = int(self.headers.get('Content-Length', 0))
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {'error': 'invalid JSON'})
            return

        def _color(key, default):
            v = data.get(key, default)
            return v if v in VALID_COLORS else default

        msg = {
            'header':       str(data.get('header', '')),
            'body':         str(data.get('body', '')),
            'text_color':   _color('text_color', 'black'),
            'bg_color':     _color('bg_color', 'white'),
            'border_color': _color('border_color', '') if data.get('border_color') else '',
            'ttl':          max(0, int(data.get('ttl', 0))),
            'created_at':   time.time(),
        }
        _write_message(msg)
        _notify_dashboard()
        self._send_json(200, {'ok': True})

    def do_DELETE(self):
        if self.path == '/message':
            _clear_message()
            _notify_dashboard()
            self._send_json(200, {'ok': True})
        else:
            self._send_json(404, {'error': 'not found'})


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), _Handler)
    print(f'Dashboard message server listening on 0.0.0.0:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
