import logging
import threading
import os
import math
import time
import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from managers.menus.base_manager import BaseManager

FIFO_PATH = "/tmp/display.fifo"  # Same as ModernScreen

class VUScreen(BaseManager):
    """
    Modern VU Meter screen for Quadify:
    - Draws PNG background
    - Two white needles (L/R)
    - Artist and title at top
    """
    def __init__(self, display_manager, volumio_listener, mode_manager):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.logger = logging.getLogger(self.__class__.__name__)
        print("VUScreen __init__ CALLED")
        self.logger.setLevel(logging.WARNING)
        self.display_manager = display_manager
        self.mode_manager = mode_manager
        self.volumio_listener = volumio_listener

        # Font (use display_manager fonts, fallback to default)
        self.font_artist = ImageFont.truetype("/home/volumio/Quadify/src/assets/fonts/OpenSans-Regular.ttf", 10)
        self.font_title = ImageFont.truetype("/home/volumio/Quadify/src/assets/fonts/OpenSans-Regular.ttf", 12)
        self.font = self.font_title

        self.font = self.font_title or ImageFont.load_default()

        # Load and darken background VU image
        vuscreen_path = display_manager.config.get(
            "vuscreen_path", "/home/volumio/Quadify/src/assets/images/pngs/vuscreen.png"
        )
        try:
            bg_orig = Image.open(vuscreen_path).convert("RGBA")
            enhancer = ImageEnhance.Brightness(bg_orig)
            self.vu_bg = enhancer.enhance(0.6)  # 0.6 = darker
            self.logger.info(f"Loaded VU meter background: {vuscreen_path}")
        except Exception as e:
            self.logger.error(f"Could not load VU meter image: {e}")
            # fallback to black
            self.vu_bg = Image.new("RGBA", self.display_manager.oled.size, "black")

        # VU needle settings
        self.left_centre = (54, 68)
        self.right_centre = (200, 68)
        self.needle_length = 28
        self.min_angle = -70
        self.max_angle = 70

        # Spectrum (CAVA/FIFO) handling - pattern matches ModernScreen
        self.spectrum_thread = None
        self.running_spectrum = False
        self.spectrum_bars = [0] * 36  # Start with all zeroes

        # State & threading
        self.latest_state = None
        self.current_state = None
        self.state_lock = threading.Lock()
        self.update_event = threading.Event()
        self.stop_event = threading.Event()
        self.is_active = False

        self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
        self.update_thread.start()
        self.logger.info("VUScreen: Started background update thread.")

        # Connect to Volumio listener
        if self.volumio_listener:
            self.volumio_listener.state_changed.connect(self.on_volumio_state_change)
        self.logger.info("VUScreen initialised.")

    # ---------------- CAVA/FIFO Spectrum Thread ---------------------

    def _is_cava_running(self):
        """Returns True if cava.service is active, False otherwise."""
        try:
            out = subprocess.check_output(['systemctl', 'is-active', '--quiet', 'cava'])
            return True
        except subprocess.CalledProcessError:
            return False

    def _start_cava_service(self):
        """Starts or restarts cava.service."""
        try:
            subprocess.run(['systemctl', 'restart', 'cava'], check=True)
            self.logger.info("VUScreen: CAVA service restarted.")
        except Exception as e:
            self.logger.error(f"VUScreen: Failed to start/restart CAVA service: {e}")

    def _read_fifo(self):
        """
        Continuously read spectrum data from FIFO.
        Auto-reconnects if FIFO disappears (e.g. cava restarted).
        """
        fifo_path = FIFO_PATH
        retry_delay = 1.0  # seconds between retries

        self.logger.info("VUScreen: Spectrum thread started, reading %s", fifo_path)

        while self.running_spectrum:
            if not os.path.exists(fifo_path):
                self.logger.warning("VUScreen: FIFO %s not found. Retrying in %.1fs", fifo_path, retry_delay)
                time.sleep(retry_delay)
                continue

            try:
                with open(fifo_path, "r") as fifo:
                    for line in fifo:
                        if not self.running_spectrum:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            bars = [int(x) for x in line.split(";") if x.isdigit()]
                            if bars:
                                self.spectrum_bars = bars
                        except Exception as e:
                            self.logger.error("VUScreen: Failed to parse FIFO line '%s' -> %s", line, e)
            except Exception as e:
                self.logger.error("VUScreen: FIFO read error: %s. Retrying in %.1fs", e, retry_delay)
                time.sleep(retry_delay)

        self.logger.info("VUScreen: Spectrum thread exiting.")


    # ---------------- Volumio State Change Handler ------------------
    def on_volumio_state_change(self, sender, state):
        self.logger.debug(f"on_volumio_state_change called with state={state!r} (type={type(state)})")
        if not self.is_active or self.mode_manager.get_mode() != 'vuscreen':
            self.logger.debug("on_volumio_state_change: Not active or not in vuscreen mode. Ignoring.")
            return
        with self.state_lock:
            self.latest_state = state
        self.update_event.set()

    # ---------------- Background Display Update Loop ----------------
    def update_display_loop(self):
        self.logger.info("update_display_loop: Thread started.")
        while not self.stop_event.is_set():
            triggered = self.update_event.wait(timeout=0.1)
            with self.state_lock:
                if triggered and self.latest_state:
                    self.current_state = self.latest_state
                    self.latest_state = None
                    self.update_event.clear()
            # Always redraw, not just on update_event
            if self.is_active and self.mode_manager.get_mode() == 'vuscreen' and self.current_state:
                self.draw_display(self.current_state)
            # Sleep a tiny bit to avoid pegging the CPU
            time.sleep(0.05)


    def start_mode(self):
        self.logger.info("start_mode: Called.")
        self.logger.info("VUScreen start_mode LOG INFO")
        if self.mode_manager.get_mode() != 'vuscreen':
            self.logger.debug("start_mode: Not in vuscreen mode, aborting start.")
            return
        self.is_active = True
        self.logger.info("start_mode: VUScreen is now active.")

        # Ensure CAVA is running for VU
        if not self._is_cava_running():
            self.logger.info("VUScreen: CAVA not running, attempting to start.")
            self._start_cava_service()
        else:
            self.logger.info("VUScreen: CAVA already running.")

        # Start the CAVA spectrum thread if not already running
        if not self.spectrum_thread or not self.spectrum_thread.is_alive():
            self.running_spectrum = True
            self.spectrum_thread = threading.Thread(target=self._read_fifo, daemon=True)
            self.spectrum_thread.start()
            self.logger.info("VUScreen: Spectrum reading thread started.")

        if not self.update_thread.is_alive():
            self.stop_event.clear()
            self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
            self.update_thread.start()
            self.logger.info("VUScreen: update_thread (background redraw) started.")

        # Force Volumio to send current playback state immediately
        try:
            if self.volumio_listener and hasattr(self.volumio_listener, "socketIO") and self.volumio_listener.socketIO:
                self.logger.debug("VUScreen: Forcing getState from Volumio.")
                self.volumio_listener.socketIO.emit("getState", {})
        except Exception as e:
            self.logger.warning(f"VUScreen: Failed to emit 'getState'. Error => {e}")

        # Optionally force a redraw with any cached state (may be replaced when real state arrives)
        current_state = None
        if self.volumio_listener:
            current_state = self.volumio_listener.get_current_state()
            self.logger.info(f"start_mode: Forcing initial draw with state: {current_state}")
        if current_state:
            self.draw_display(current_state)



    def stop_mode(self):
        self.logger.info("stop_mode: Called.")
        if not self.is_active:
            self.logger.debug("stop_mode: Already inactive.")
            return

        self.is_active = False

        # Stop spectrum thread
        self.running_spectrum = False
        if self.spectrum_thread and self.spectrum_thread.is_alive():
            self.spectrum_thread.join(timeout=1)
            self.logger.info("VUScreen: Spectrum thread stopped.")

        # Stop update thread
        self.stop_event.set()
        self.update_event.set()
        if self.update_thread.is_alive():
            self.logger.info("stop_mode: Waiting for update thread to join.")
            self.update_thread.join(timeout=1)
        self.display_manager.clear_screen()
        self.logger.info("stop_mode: Display cleared.")

    def adjust_volume(self, volume_change):
        """
        Adjust volume from an external call (e.g. rotary). This
        emits a volume +/- to Volumio.
        """
        if not self.volumio_listener:
            self.logger.error("VUScreen: no volumio_listener, cannot adjust volume.")
            return

        if self.latest_state is None:
            self.logger.debug("VUScreen: latest_state=None => assume volume=100.")
            self.latest_state = {"volume": 100}

        with self.state_lock:
            curr_vol = self.latest_state.get("volume", 100)
            new_vol  = max(0, min(int(curr_vol) + volume_change, 100))

        self.logger.info(f"VUScreen: Adjusting volume from {curr_vol} to {new_vol}.")
        try:
            if volume_change > 0:
                self.volumio_listener.socketIO.emit("volume", "+")
            elif volume_change < 0:
                self.volumio_listener.socketIO.emit("volume", "-")
            else:
                self.volumio_listener.socketIO.emit("volume", new_vol)
        except Exception as e:
            self.logger.error(f"VUScreen: error adjusting volume => {e}")


    # -------- VU Needle Drawing & Display --------
    def level_to_angle(self, level):
        angle = self.min_angle + (level / 255) * (self.max_angle - self.min_angle)
        self.logger.debug(f"level_to_angle: level={level} -> angle={angle}")
        return angle

    def draw_needle(self, draw, centre, angle_deg, length, colour):
        angle_rad = math.radians(angle_deg - 90)  # -90: 0 deg points up
        x_end = int(centre[0] + length * math.cos(angle_rad))
        y_end = int(centre[1] + length * math.sin(angle_rad))
        self.logger.debug(
            f"draw_needle: centre={centre}, angle_deg={angle_deg}, end=({x_end},{y_end}), colour={colour}"
        )
        draw.line([centre, (x_end, y_end)], fill=colour, width=2)


    def draw_display(self, data):
        self.logger.info(f"draw_display: Called with data: {data}")

        # --- Spectrum safety / auto-restart ---
        if not self.mode_manager.config.get("cava_enabled", False):
            # User disabled spectrum → idle needles
            bars = [0] * 36
        else:
            if not self.running_spectrum:
                self.logger.warning("VUScreen: Spectrum enabled but thread not running – restarting.")
                self.running_spectrum = True
                self.spectrum_thread = threading.Thread(target=self._read_fifo, daemon=True)
                self.spectrum_thread.start()
            bars = self.spectrum_bars

        # --- Calculate levels ---
        left = right = 0
        if bars and len(bars) == 36:
            left = sum(bars[:18]) // 18
            right = sum(bars[18:]) // 18
        else:
            self.logger.warning(f"draw_display: Not enough spectrum bars (got {len(bars) if bars else 0})")

        self.logger.debug(f"draw_display: Calculated VU levels: left={left}, right={right}")

        # --- Frame base (background) ---
        try:
            frame = self.vu_bg.copy()
        except Exception as e:
            self.logger.error(f"draw_display: Failed to copy background: {e}")
            frame = Image.new("RGBA", self.display_manager.oled.size, "black")

        draw = ImageDraw.Draw(frame)
        width, height = self.display_manager.oled.size

        # --- Needles ---
        try:
            self.draw_needle(draw, self.left_centre, self.level_to_angle(left), self.needle_length, "white")
            self.draw_needle(draw, self.right_centre, self.level_to_angle(right), self.needle_length, "white")
            self.logger.debug("draw_display: Needles drawn.")
        except Exception as e:
            self.logger.error(f"draw_display: Error drawing needles: {e}")

        # --- Text overlays ---
        try:
            # Artist - Title line (truncate if too long)
            title = data.get("title", "Unknown Title")
            artist = data.get("artist", "Unknown Artist")
            max_length = 45
            combined = f"{artist} - {title}"
            if len(combined) > max_length:
                combined = combined[:max_length - 3] + "..."

            text_w, text_h = draw.textsize(combined, font=self.font)
            text_y = -4
            draw.text(((width - text_w) // 2, text_y), combined, font=self.font, fill="white")

            # Bottom info line: Vol / Samplerate / Bitdepth
            samplerate = data.get("samplerate", "N/A")
            bitdepth = data.get("bitdepth", "N/A")
            volume = data.get("volume", "N/A")
            info_text = f"Vol: {volume} / {samplerate} / {bitdepth}"
            info_w, info_h = draw.textsize(info_text, font=self.font_artist)
            info_y = text_y + text_h + 1
            draw.text(((width - info_w) // 2, info_y), info_text, font=self.font_artist, fill="white")

            self.logger.debug("draw_display: Artist/title and info line drawn.")
        except Exception as e:
            self.logger.error(f"draw_display: Error rendering text: {e}")

        # --- Final display ---
        try:
            frame = frame.convert(self.display_manager.oled.mode)
            self.display_manager.oled.display(frame)
            self.logger.info("draw_display: Frame sent to display.")
        except Exception as e:
            self.logger.error(f"draw_display: Error displaying frame: {e}")


    def display_playback_info(self):
        """
        If needed, manually refresh the display with the current state.
        """
        state = self.volumio_listener.get_current_state()
        if state:
            self.draw_display(state)
        else:
            self.logger.warning("VUScreen: No current volumio state available to display.")

    def toggle_play_pause(self):
        """Emit Volumio play/pause toggle if connected."""
        self.logger.info("VUScreen: Toggling play/pause.")
        if not self.volumio_listener or not self.volumio_listener.is_connected():
            self.logger.warning("VUScreen: Not connected to Volumio => cannot toggle.")
            return
        try:
            self.volumio_listener.socketIO.emit("toggle", {})
            self.logger.debug("VUScreen: Emitted 'toggle' event.")
        except Exception as e:
            self.logger.error(f"VUScreen: toggle_play_pause failed => {e}")
