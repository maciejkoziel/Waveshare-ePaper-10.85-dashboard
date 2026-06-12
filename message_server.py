#!/usr/bin/python3
# -*- coding:utf-8 -*-
"""
Dashboard message server.
Stores up to 3 messages in round-robin fashion (newest replaces oldest).
Signals main.py to refresh after each change.

API:
  POST   /message  — add message (JSON body, see schema below); oldest dropped when queue full
  DELETE /message  — clear all messages sent from the caller's IP
  GET    /message  — get current message list

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
MAX_MESSAGES = 3

try:
    with open(os.path.join(BASE_DIR, 'settings_local.toml'), 'rb') as _f:
        _cfg = tomllib.load(_f)
    PORT = _cfg.get('message_server', {}).get('port', 5000)
    AUTO_CLEAR_HOURS = _cfg.get('message_server', {}).get('auto_clear_hours', 0)
except FileNotFoundError:
    PORT = 5000
    AUTO_CLEAR_HOURS = 0

VALID_COLORS = {'black', 'white', 'red', 'yellow'}


def _notify_dashboard():
    try:
        result = subprocess.run(['pgrep', '-f', 'main.py'], capture_output=True, text=True)
        for pid in result.stdout.strip().split('\n'):
            if pid.strip():
                os.kill(int(pid.strip()), signal.SIGUSR1)
    except Exception:
        pass


def _read_messages():
    try:
        with open(MESSAGE_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = [data]
        if AUTO_CLEAR_HOURS > 0:
            now = time.time()
            data = [m for m in data if now - m.get('created_at', 0) <= AUTO_CLEAR_HOURS * 3600]
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write_messages(msgs):
    if msgs:
        with open(MESSAGE_FILE, 'w') as f:
            json.dump(msgs, f)
    else:
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
            msgs = _read_messages()
            if not msgs:
                self._send_json(404, {'error': 'no messages'})
            else:
                self._send_json(200, msgs)
        else:
            self._send_json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path not in ('/message', '/message/reset'):
            self._send_json(404, {'error': 'not found'})
            return

        if self.path == '/message/reset':
            _write_messages([])
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
            'sender_ip':    self.client_address[0],
        }
        msgs = _read_messages()
        msgs.append(msg)
        _write_messages(msgs[-MAX_MESSAGES:])
        _notify_dashboard()
        self._send_json(200, {'ok': True})

    def do_DELETE(self):
        if self.path == '/message':
            sender_ip = self.client_address[0]
            msgs = _read_messages()
            _write_messages([m for m in msgs if m.get('sender_ip') != sender_ip])
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
