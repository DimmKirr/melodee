#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Kerem Kilic (Ellic Studio)
"""Shared fixtures for Playwright E2E tests of the Melodee web editor."""
import http.server
import os
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / 'web'
EMU_DIR = Path(__file__).resolve().parent / 'fm1-emu'
RESULTS_DIR = Path(__file__).resolve().parent / 'results'
CHROMIUM_PATH = os.environ.get('CHROMIUM_PATH')

EMU_LIVE_URL = 'https://joakimeriksson.github.io/fm1-emu/?fw=local&mhz=100'


def _make_handler(directory):
    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)
        def end_headers(self):
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
            super().end_headers()
        def log_message(self, fmt, *args):
            pass
    return _Handler


def _find_free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _debug():
    return os.environ.get('E2E_DEBUG', '') not in ('', '0')


_run_timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')


class E2ETestCase(unittest.TestCase):
    """Base class that starts a static file server and a Playwright browser."""

    _server = None
    _thread = None
    _emu_server = None
    _emu_thread = None
    _pw = None
    _browser = None
    base_url = None
    emu_url = None
    _screenshot_dir = None

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            try:
                from patchright.sync_api import sync_playwright
            except ImportError:
                raise unittest.SkipTest(
                    'neither playwright nor patchright installed '
                    '(pip install playwright)')
        port = _find_free_port()
        cls._server = http.server.HTTPServer(
            ('127.0.0.1', port), _make_handler(WEB_DIR))
        cls._thread = threading.Thread(
            target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        cls.base_url = f'http://127.0.0.1:{port}'
        if EMU_DIR.is_dir():
            emu_port = _find_free_port()
            cls._emu_server = http.server.HTTPServer(
                ('127.0.0.1', emu_port), _make_handler(EMU_DIR))
            cls._emu_thread = threading.Thread(
                target=cls._emu_server.serve_forever, daemon=True)
            cls._emu_thread.start()
            cls.emu_url = (
                f'http://127.0.0.1:{emu_port}/?fw=local&mhz=100&debug=1')
        else:
            cls.emu_url = EMU_LIVE_URL
        cls._pw = sync_playwright().start()
        launch_kwargs = dict(headless=True)
        if CHROMIUM_PATH and os.path.isfile(CHROMIUM_PATH):
            launch_kwargs['executable_path'] = CHROMIUM_PATH
        cls._browser = cls._pw.chromium.launch(**launch_kwargs)
        test_module = cls.__module__.rsplit('.', 1)[-1]
        cls._screenshot_dir = (
            RESULTS_DIR / f'{_run_timestamp}-{test_module}' / 'screenshots')
        if _debug():
            cls._screenshot_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls._browser:
            cls._browser.close()
        if cls._pw:
            cls._pw.stop()
        if cls._server:
            cls._server.shutdown()
        if cls._emu_server:
            cls._emu_server.shutdown()

    def new_page(self, mock=True):
        """Open the editor in a fresh browser page. mock=True adds ?mock=1."""
        page = self._browser.new_page()
        suffix = '?mock=1' if mock else ''
        page.goto(f'{self.base_url}/editor.html{suffix}')
        return page

    def new_emu_page(self):
        """Open the fm1-emu WASM emulator in a fresh browser page.

        Console messages are captured in page._console_logs (list of str).
        """
        page = self._browser.new_page()
        page._console_logs = []
        page.on('console', lambda msg: page._console_logs.append(
            f'[{msg.type}] {msg.text}'))
        page.on('pageerror', lambda err: page._console_logs.append(
            f'[pageerror] {err}'))
        page.goto(self.emu_url)
        return page

    def _results_dir(self):
        test_module = self.__class__.__module__.rsplit('.', 1)[-1]
        return RESULTS_DIR / f'{_run_timestamp}-{test_module}'

    def write_log(self, page, filename='fm1-emulator.log'):
        """Write emulator diagnostics, #fm1log DOM log, and JS console to a file."""
        results = self._results_dir()
        results.mkdir(parents=True, exist_ok=True)
        info = page.evaluate('''() => {
            const r = {};
            r.status = document.getElementById('status')?.textContent || '';
            r.title = document.title || '';
            r.about = document.getElementById('about')?.textContent || '';
            r.firmware = document.querySelector(
                'select')?.selectedOptions?.[0]?.textContent || '';
            r.fm1log = document.getElementById('fm1log')?.textContent || '';
            const details = [];
            document.querySelectorAll('details').forEach(d => {
                d.open = true;
                details.push(d.textContent.trim());
            });
            r.details = details;
            return r;
        }''')
        lines = [
            f'title:    {info["title"]}',
            f'firmware: {info["firmware"]}',
            f'about:    {info["about"]}',
            f'status:   {info["status"]}',
        ]
        if info.get('details'):
            lines.append('')
            for i, d in enumerate(info['details']):
                lines.append(f'--- details[{i}] ---')
                lines.append(d)
        lines.append('')
        fm1log = info.get('fm1log', '')
        lines.append(f'--- #fm1log ({len(fm1log.splitlines())} lines) ---')
        lines.append(fm1log if fm1log else '(empty)')
        lines.append('')
        lines.append(f'--- JS console ({len(page._console_logs)} messages) ---')
        lines.extend(page._console_logs or ['(no console output)'])
        path = results / filename
        path.write_text('\n'.join(lines) + '\n')

    # -- FM-1 panel controls (keyboard mapping from fm1-emu) --
    # Buttons: keyboard key -> emulator button id
    #   "7" = HOME, "z" = OCT-, "x" = OCT+, Space = PLAY, "r" = REC
    #   "1"-"0" = FX SCL ENV LFO EDIT GLO HOME SAVE ARP SEQ
    # Encoders: ArrowDown/Up, ArrowLeft/Right, ","/".""

    @staticmethod
    def push(page, key, delay_ms=300):
        """Tap a button (press and release). Holds briefly so the firmware
        sees at least one frame with the button down."""
        page.keyboard.down(key)
        page.wait_for_timeout(80)
        page.keyboard.up(key)
        page.wait_for_timeout(delay_ms)

    @staticmethod
    def long_push(page, key, hold_ms=900, delay_ms=500):
        """Hold a button for hold_ms then release. For HOME-hold menu etc."""
        page.keyboard.down(key)
        page.wait_for_timeout(hold_ms)
        page.keyboard.up(key)
        page.wait_for_timeout(delay_ms)

    @staticmethod
    def rotate_down(page, clicks=1, delay_ms=400):
        """Turn encoder down (ArrowDown). Each click scrolls the menu."""
        for _ in range(clicks):
            page.keyboard.press('ArrowDown')
            page.wait_for_timeout(delay_ms)

    @staticmethod
    def rotate_up(page, clicks=1, delay_ms=400):
        """Turn encoder up (ArrowUp)."""
        for _ in range(clicks):
            page.keyboard.press('ArrowUp')
            page.wait_for_timeout(delay_ms)

    @staticmethod
    def rotate_left(page, clicks=1, delay_ms=400):
        """Turn encoder left (ArrowLeft)."""
        for _ in range(clicks):
            page.keyboard.press('ArrowLeft')
            page.wait_for_timeout(delay_ms)

    @staticmethod
    def rotate_right(page, clicks=1, delay_ms=400):
        """Turn encoder right (ArrowRight)."""
        for _ in range(clicks):
            page.keyboard.press('ArrowRight')
            page.wait_for_timeout(delay_ms)

    @staticmethod
    def send_enc(page, physical_enc, clicks, delay_ms=300):
        """Send encoder clicks directly to the firmware worklet.

        physical_enc: hardware encoder index (0-6). See PANEL_DEFAULT in
        panel.c for the role-to-physical mapping:
          SELECT=0, ALGO=1, PRESET→6, K1→2, K2→3, K3→4, K4→5
        """
        page.evaluate('''([enc, clicks]) => {
            document.documentElement.dataset.fm1cmd =
                JSON.stringify({op:"send", m:{type:"enc", enc, clicks}});
            window.dispatchEvent(new Event("fm1-cmd"));
        }''', [physical_enc, clicks])
        page.wait_for_timeout(delay_ms)

    def screenshot(self, page, screen_name, action_name='view'):
        """Save a screenshot when E2E_DEBUG=1."""
        if not _debug():
            return
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')
        test_name = self.id().rsplit('.', 1)[-1]
        filename = f'{now}-{test_name}-{screen_name}-{action_name}.png'
        path = self._screenshot_dir / filename
        page.screenshot(path=str(path))
