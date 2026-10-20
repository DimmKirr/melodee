#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Kerem Kilic (Ellic Studio)
"""E2E: load Melodee firmware into the fm1-emu WASM emulator and verify boot."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_fixtures import E2ETestCase

FWSC_PATH = Path(__file__).resolve().parents[1] / 'build' / 'melodee.fwsc'
BOOT_PATTERN = 'instructions/s'


class LoadMelodeeFirmwareTest(E2ETestCase):
    """Upload melodee.fwsc into the emulator and verify it boots."""

    _emu_page = None

    @classmethod
    def setUpClass(cls):
        if not FWSC_PATH.is_file():
            raise unittest.SkipTest(
                f'Melodee firmware not built ({FWSC_PATH}). '
                'Run "task build" first.')
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        if cls._emu_page:
            try:
                cls._emu_page.close()
            except Exception:
                pass
        super().tearDownClass()

    def _get_emu_page(self):
        """Return a shared emulator page, booting firmware on first call."""
        if self.__class__._emu_page is None:
            page = self.new_emu_page()
            page.wait_for_load_state('networkidle', timeout=30_000)
            page.set_input_files('#open', str(FWSC_PATH))
            page.click('#start')
            page.wait_for_function(
                f'() => document.getElementById("status")'
                f'?.textContent?.includes("{BOOT_PATTERN}")',
                timeout=60_000)
            page.wait_for_timeout(1500)
            self.__class__._emu_page = page
        return self.__class__._emu_page

    def test_01_upload_and_boot_melodee_firmware(self):
        page = self._get_emu_page()
        self.screenshot(page, 'emulator', 'booted-melodee')
        status = page.text_content('#status')
        self.assertIn(BOOT_PATTERN, status)
        self.assertIn('melodee', status.lower())

    def test_02_start_button_hidden_after_boot(self):
        page = self._get_emu_page()
        self.assertTrue(
            page.evaluate('() => document.getElementById("start")?.hidden'),
            'Start button should be hidden after boot')

    def test_03_lcd_canvas_renders_after_boot(self):
        page = self._get_emu_page()
        self.screenshot(page, 'emulator-lcd', 'after-boot')
        canvas = page.query_selector('canvas')
        self.assertIsNotNone(canvas, 'LCD canvas should exist after boot')

    def test_04_navigate_to_about_and_verify_version(self):
        """Hold HOME to open Settings, scroll to About, enter it."""
        page = self._get_emu_page()

        self.long_push(page, '7', hold_ms=900)
        self.screenshot(page, 'settings-menu', 'opened')

        # K2 (physical enc 3): menu_sel += clicks (clamped). 19 items to About.
        self.send_enc(page, 3, 19, delay_ms=500)
        self.screenshot(page, 'settings-menu', 'at-about')

        self.push(page, 'x', delay_ms=800)
        self.screenshot(page, 'about-screen', 'version')

        # PRESET (physical enc 6): scroll the About document.
        self.send_enc(page, 6, 3, delay_ms=400)
        self.screenshot(page, 'about-screen', 'scrolled')

        self.push(page, 'z', delay_ms=300)
        self.long_push(page, '7', hold_ms=900)

    def test_05_write_emulator_log(self):
        page = self._get_emu_page()
        self.write_log(page)


if __name__ == '__main__':
    unittest.main()
