# src/display/screens/vu_screen.py

import logging
import threading
import os
import math
import time
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from managers.menus.base_manager import BaseManager

FIFO_PATH = "/tmp/display.fifo"


class VUScreen(BaseManager):
    """
    Analogue-style VU Meter screen for Quadify:
    - PNG background
    - Two white needles (L/R)
    - Artist + title at top
    - Volume / samplerate / bitdepth line at bottom
    """

    def __init__(self, display_manager, volumio_listener, mode_manager):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

        self.display_manager = display_manager
        self.mode_manager = mode_manager
        self.volumio_listener = volumio_listener

        # Fonts (fallback to default if missing)
        try:
            self.font_artist = ImageFont.truetype(
                "/home/volumio/Quadify/src/assets/fonts/OpenSans-Regular.ttf", 10
            )
            self.font_title = ImageFont.truetype(
                "/home/volumio/Quadify/src/assets/fonts/OpenSans-Regular.ttf", 12
            )
        except Exception:
            self.font_artist = self.font_title = ImageFont.load_default()
        self.font = self.font_title or ImageFont.load_default()

        # Background
        vuscreen_path = display_manager.config.get(
            "vuscreen_path",
            "/home/volumio/Quadify/src/assets/images/pngs/vuscreen.png",
        )
        try:
            bg_orig = Image.open(vuscreen_path).convert("RGBA")
            self.vu_bg = ImageEnhance.Brightness(bg_orig).enhance(0.6)
        except Exception as e:
            self.logger.error(f"VUScreen: Could not load background -> {e}")
            self.vu_bg = Image.new("RGBA", self.display_manager.oled.size, "black")

        # Needle geometry
        self.left_centre = (54, 68)
        self.right_centre = (200, 68)
        self.needle_length = 28
        self.min_angle = -70
        self.max_angle = 70

        # Spectrum (CAVA/FIFO)
        self.spectrum_thread = None
        self.running_spectrum = False
        self.spectrum_bars = [0] * 36

        # State / threading
        self.latest_state = None
        self.current_state = None
        self.state_lock = threading.Lock()
        self.update_event = threading.Event()
        self.stop_event = threading.Event()
        self.is_active = False
        self.update_thread = None
        self.last_update_time = time.time()

        # Hook Volumio
        if self.volumio_listener:
            self.volumio_listener.state_changed.connect(self.on_volumio_state_change)

    # ----------------- Volumio -----------------

    def on_volumio_state_change(self, sender, state):
        if not self.is_active or self.mode_manager.get_mode() != "vuscreen":
            return
        with self.state_lock:
            self.latest_state = state
        self.update_event.set()

    # ----------------- Threads -----------------

    def update_display_loop(self):
        self.logger.info("VUScreen: update_display_loop started.")
        self.last_update_time = time.time()
        while not self.stop_event.is_set():
            triggered = self.update_event.wait(timeout=0.1)
            with self.state_lock:
                if triggered and self.latest_state:
                    self.current_state = self.latest_state.copy()
                    self.latest_state = None
                    self.update_event.clear()
                    self.last_update_time = time.time()
                elif self.current_state:
                    status = (self.current_state.get("status") or "").lower()
                    duration_val = self.current_state.get("duration")
                    try:
                        duration_ok = int(duration_val) > 0
                    except Exception:
                        duration_ok = False

                    if status == "play" and duration_ok:
                        elapsed = time.time() - self.last_update_time
                        seek_val = int(self.current_state.get("seek") or 0)
                        self.current_state["seek"] = seek_val + int(elapsed * 1000)
                    self.last_update_time = time.time()

            if self.is_active and self.mode_manager.get_mode() == "vuscreen" and self.current_state:
                self.draw_display(self.current_state)

            time.sleep(0.05)

        self.logger.info("VUScreen: update_display_loop exiting.")

    def _read_fifo(self):
        fifo_path = FIFO_PATH
        retry_delay = 1.0
        self.logger.info("VUScreen: Spectrum thread started, reading %s", fifo_path)

        while self.running_spectrum:
            if not os.path.exists(fifo_path):
                time.sleep(retry_delay)
                continue
            try:
                with open(fifo_path, "r") as fifo:
                    for line in fifo:
                        if not self.running_spectrum:
                            break
                        bars = [int(x) for x in line.strip().split(";") if x.isdigit()]
                        if bars:
                            self.spectrum_bars = bars
            except Exception as e:
                self.logger.error("VUScreen: FIFO read error -> %s", e)
                time.sleep(retry_delay)

        self.logger.info("VUScreen: Spectrum thread exiting.")

    # ----------------- Mode Lifecycle -----------------

    def start_mode(self):
        if self.mode_manager.get_mode() != "vuscreen":
            return
        self.is_active = True
        self.display_manager.clear_screen()
        self.logger.info("VUScreen: Activated mode.")

        # Start spectrum thread
        if self.mode_manager.config.get("cava_enabled", False):
            if not self.running_spectrum:
                self.running_spectrum = True
                self.spectrum_thread = threading.Thread(target=self._read_fifo, daemon=True)
                self.spectrum_thread.start()

        # Start update thread
        if not self.update_thread or not self.update_thread.is_alive():
            self.stop_event.clear()
            self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
            self.update_thread.start()

        # Force state pull
        try:
            if self.volumio_listener and getattr(self.volumio_listener, "socketIO", None):
                self.volumio_listener.socketIO.emit("getState", {})
        except Exception as e:
            self.logger.warning(f"VUScreen: Failed to emit getState -> {e}")

        # Draw immediately if cached state
        state = self.volumio_listener.get_current_state() if self.volumio_listener else None
        if state:
            self.draw_display(state)

    def stop_mode(self):
        if not self.is_active:
            return
        self.is_active = False

        # Stop spectrum
        self.running_spectrum = False
        if self.spectrum_thread and self.spectrum_thread.is_alive():
            self.spectrum_thread.join(timeout=1)

        # Stop update loop
        self.stop_event.set()
        self.update_event.set()
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=1)

        self.display_manager.clear_screen()
        self.logger.info("VUScreen: Stopped mode.")

    # ----------------- Drawing -----------------

    def level_to_angle(self, level):
        return self.min_angle + (level / 255) * (self.max_angle - self.min_angle)

    def draw_needle(self, draw, centre, angle_deg, length, colour):
        angle_rad = math.radians(angle_deg - 90)
        x_end = int(centre[0] + length * math.cos(angle_rad))
        y_end = int(centre[1] + length * math.sin(angle_rad))
        draw.line([centre, (x_end, y_end)], fill=colour, width=2)

    def draw_display(self, data):
        # Levels
        bars = self.spectrum_bars if self.mode_manager.config.get("cava_enabled", False) else [0] * 36
        left = sum(bars[:18]) // 18 if len(bars) == 36 else 0
        right = sum(bars[18:]) // 18 if len(bars) == 36 else 0

        try:
            frame = self.vu_bg.copy()
        except Exception:
            frame = Image.new("RGBA", self.display_manager.oled.size, "black")

        draw = ImageDraw.Draw(frame)
        width, _ = self.display_manager.oled.size

        # Needles
        self.draw_needle(draw, self.left_centre, self.level_to_angle(left), self.needle_length, "white")
        self.draw_needle(draw, self.right_centre, self.level_to_angle(right), self.needle_length, "white")

        # Artist + Title
        title = data.get("title", "Unknown Title")
        artist = data.get("artist", "Unknown Artist")
        combined = f"{artist} - {title}"
        if len(combined) > 45:
            combined = combined[:42] + "..."
        text_w, text_h = draw.textsize(combined, font=self.font)
        draw.text(((width - text_w) // 2, -4), combined, font=self.font, fill="white")

        # Info line
        samplerate = data.get("samplerate", "N/A")
        bitdepth = data.get("bitdepth", "N/A")
        volume = data.get("volume", "N/A")
        info_text = f"Vol: {volume} / {samplerate} / {bitdepth}"
        info_w, _ = draw.textsize(info_text, font=self.font_artist)
        draw.text(((width - info_w) // 2, text_h), info_text, font=self.font_artist, fill="white")

        self.display_manager.display_pil(frame)

    # ----------------- External -----------------

    def adjust_volume(self, volume_change):
        if not self.volumio_listener:
            return
        if self.latest_state is None:
            self.latest_state = {"volume": 100}
        with self.state_lock:
            curr_vol = self.latest_state.get("volume", 100)
            new_vol = max(0, min(int(curr_vol) + volume_change, 100))
        try:
            if volume_change > 0:
                self.volumio_listener.socketIO.emit("volume", "+")
            elif volume_change < 0:
                self.volumio_listener.socketIO.emit("volume", "-")
            else:
                self.volumio_listener.socketIO.emit("volume", new_vol)
        except Exception as e:
            self.logger.error(f"VUScreen: adjust_volume failed -> {e}")

    def display_playback_info(self):
        state = self.volumio_listener.get_current_state()
        if state:
            self.draw_display(state)

    def toggle_play_pause(self):
        if not self.volumio_listener or not self.volumio_listener.is_connected():
            return
        try:
            self.volumio_listener.socketIO.emit("toggle", {})
        except Exception as e:
            self.logger.error(f"VUScreen: toggle_play_pause failed -> {e}")
