import logging
import threading
import os
import math
import time
import subprocess
import fcntl
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from managers.menus.base_manager import BaseManager

FIFO_PATH = "/tmp/display.fifo"  # Same as ModernScreen

class DigitalVUScreen(BaseManager):
    """
    Modern VU Meter screen for Quadify:
    - Draws PNG background
    - Two white needles (L/R)
    - Artist and title at top
    """
    def __init__(self, display_manager, volumio_listener, mode_manager):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.logger = logging.getLogger(self.__class__.__name__)
        print("DigitalVUScreen __init__ CALLED")
        self.logger.setLevel(logging.WARNING)
        self.display_manager = display_manager
        self.mode_manager = mode_manager
        self.volumio_listener = volumio_listener

        # Font (use display_manager fonts, fallback to default)
        self.font_artist = ImageFont.truetype("/home/volumio/Quadify/src/assets/fonts/OpenSans-Regular.ttf", 10)
        self.font_title = ImageFont.truetype("/home/volumio/Quadify/src/assets/fonts/OpenSans-Regular.ttf", 14)
        self.font = self.font_title

        self.font = self.font_title or ImageFont.load_default()

        # Load and darken background VU image
        digitalvuscreen_path = display_manager.config.get(
            "digitalvuscreen_path", "/home/volumio/Quadify/src/assets/images/pngs/digitalvuscreen.png"
        )
        try:
            bg_orig = Image.open(digitalvuscreen_path).convert("RGBA")
            enhancer = ImageEnhance.Brightness(bg_orig)
            self.vu_bg = enhancer.enhance(0.6)  # 0.6 = darker
            self.logger.info(f"Loaded VU meter background: {digitalvuscreen_path}")
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

        self.left_peak_cell = 0
        self.right_peak_cell = 0
        self.left_peak_time = time.time()
        self.right_peak_time = time.time()
        self.peak_hold_ms = 1500  # Milliseconds to hold the peak marker

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
        self.logger.info("DigitalVUScreen: Started background update thread.")

        # Connect to Volumio listener
        if self.volumio_listener:
            self.volumio_listener.state_changed.connect(self.on_volumio_state_change)
        self.logger.info("DigitalVUScreen initialised.")

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
            self.logger.info("DigitalVUScreen: CAVA service restarted.")
        except Exception as e:
            self.logger.error(f"DigitalVUScreen: Failed to start/restart CAVA service: {e}")


    def _read_fifo(self):
        """
        Continuously read spectrum data from FIFO.
        Exits quickly when self.running_spectrum = False.
        """
        fifo_path = FIFO_PATH
        retry_delay = 1.0

        self.logger.info("DigitalVUScreen: Spectrum thread started, reading %s", fifo_path)

        while self.running_spectrum:
            if not os.path.exists(fifo_path):
                self.logger.warning("DigitalVUScreen: FIFO %s not found. Retrying in %.1fs", fifo_path, retry_delay)
                time.sleep(retry_delay)
                continue

            try:
                with open(fifo_path, "r") as fifo:
                    # set non-blocking mode
                    fd = fifo.fileno()
                    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

                    while self.running_spectrum:
                        try:
                            line = fifo.readline().strip()
                        except BlockingIOError:
                            time.sleep(0.05)
                            continue

                        if not line:
                            time.sleep(0.01)
                            continue

                        try:
                            bars = [int(x) for x in line.split(";") if x.isdigit()]
                            if bars:
                                self.spectrum_bars = bars
                        except Exception as e:
                            self.logger.error("DigitalVUScreen: Failed to parse FIFO line '%s' -> %s", line, e)

            except Exception as e:
                self.logger.error("DigitalVUScreen: FIFO read error: %s. Retrying in %.1fs", e, retry_delay)
                time.sleep(retry_delay)

        self.logger.info("DigitalVUScreen: Spectrum thread exiting.")



    # ---------------- Volumio State Change Handler ------------------
    def on_volumio_state_change(self, sender, state):
        self.logger.debug(f"on_volumio_state_change called with state={state!r} (type={type(state)})")
        if not self.is_active or self.mode_manager.get_mode() != 'digitalvuscreen':
            self.logger.debug("on_volumio_state_change: Not active or not in digitalvuscreen mode. Ignoring.")
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
            if self.is_active and self.mode_manager.get_mode() == 'digitalvuscreen' and self.current_state:
                self.draw_display(self.current_state)
            # Sleep a tiny bit to avoid pegging the CPU
            time.sleep(0.05)


    def start_mode(self):
        self.logger.info("start_mode: Called.")
        self.logger.info("DigitalVUScreen start_mode LOG INFO")
        if self.mode_manager.get_mode() != 'digitalvuscreen':
            self.logger.debug("start_mode: Not in digitalvuscreen mode, aborting start.")
            return
        self.is_active = True
        self.logger.info("start_mode: DigitalVUScreen is now active.")

        # Ensure CAVA is running for VU
        if not self._is_cava_running():
            self.logger.info("DigitalVUScreen: CAVA not running, attempting to start.")
            self._start_cava_service()
        else:
            self.logger.info("DigitalVUScreen: CAVA already running.")

        # Start the CAVA spectrum thread if not already running
        if not self.spectrum_thread or not self.spectrum_thread.is_alive():
            self.running_spectrum = True
            self.spectrum_thread = threading.Thread(target=self._read_fifo, daemon=True)
            self.spectrum_thread.start()
            self.logger.info("DigitalVUScreen: Spectrum reading thread started.")

        if not self.update_thread.is_alive():
            self.stop_event.clear()
            self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
            self.update_thread.start()
            self.logger.info("DigitalVUScreen: update_thread (background redraw) started.")

        # Force Volumio to send current playback state immediately
        try:
            if self.volumio_listener and hasattr(self.volumio_listener, "socketIO") and self.volumio_listener.socketIO:
                self.logger.debug("DigitalVUScreen: Forcing getState from Volumio.")
                self.volumio_listener.socketIO.emit("getState", {})
        except Exception as e:
            self.logger.warning(f"DigitalVUScreen: Failed to emit 'getState'. Error => {e}")

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
            self.logger.info("DigitalVUScreen: Spectrum thread stopped.")

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
            self.logger.error("DigitalVUScreen: no volumio_listener, cannot adjust volume.")
            return

        if self.latest_state is None:
            self.logger.debug("DigitalVUScreen: latest_state=None => assume volume=100.")
            self.latest_state = {"volume": 100}

        with self.state_lock:
            curr_vol = self.latest_state.get("volume", 100)
            new_vol  = max(0, min(int(curr_vol) + volume_change, 100))

        self.logger.info(f"DigitalVUScreen: Adjusting volume from {curr_vol} to {new_vol}.")
        try:
            if volume_change > 0:
                self.volumio_listener.socketIO.emit("volume", "+")
            elif volume_change < 0:
                self.volumio_listener.socketIO.emit("volume", "-")
            else:
                self.volumio_listener.socketIO.emit("volume", new_vol)
        except Exception as e:
            self.logger.error(f"DigitalVUScreen: error adjusting volume => {e}")

    def update_display_loop(self):
        self.logger.info("update_display_loop: Thread started.")
        last_update_time = time.time()
        while not self.stop_event.is_set():
            triggered = self.update_event.wait(timeout=0.1)
            with self.state_lock:
                if triggered and self.latest_state:
                    self.current_state = self.latest_state
                    self.latest_state = None
                    self.update_event.clear()
                    last_update_time = time.time()
                # Simulate seek/progress if track is playing
                elif self.current_state and "seek" in self.current_state and "duration" in self.current_state:
                    elapsed = time.time() - last_update_time
                    self.current_state["seek"] = self.current_state.get("seek", 0) + int(elapsed * 1000)
                    last_update_time = time.time()

            if self.is_active and self.mode_manager.get_mode() == 'digitalvuscreen' and self.current_state:
                self.draw_display(self.current_state)
            time.sleep(0.05)
        
    def truncate(text, max_length=40):
        return (text[:max_length-3] + "...") if len(text) > max_length else text

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
        self.logger.info("DigitalVUScreen: draw_display called.")

        # --- Spectrum handling ---
        if not self.mode_manager.config.get("cava_enabled", False):
            bars = [0] * 36
        else:
            if not self.running_spectrum:
                self.logger.warning("DigitalVUScreen: Spectrum enabled but thread not running – restarting.")
                self.running_spectrum = True
                self.spectrum_thread = threading.Thread(target=self._read_fifo, daemon=True)
                self.spectrum_thread.start()
            bars = self.spectrum_bars

        # --- Calculate left/right levels ---
        left = right = 0
        if bars and len(bars) == 36:
            left = sum(bars[:18]) // 18
            right = sum(bars[18:]) // 18
        else:
            self.logger.warning("DigitalVUScreen: Not enough spectrum bars (got %s)", len(bars) if bars else 0)

        self.logger.debug("DigitalVUScreen: Calculated VU levels: left=%s, right=%s", left, right)

        # --- Frame setup ---
        try:
            frame = self.vu_bg.copy()
        except Exception as e:
            self.logger.error("DigitalVUScreen: Failed to copy background: %s", e)
            frame = Image.new("RGBA", self.display_manager.oled.size, "black")

        draw = ImageDraw.Draw(frame)
        screen_width, screen_height = self.display_manager.oled.size

        # --- Progress bar + time labels ---
        seek_ms = data.get("seek", 0)
        duration_s = max(1, int(data.get("duration", 1)))
        seek_s = max(0, seek_ms / 1000.0)
        progress = max(0.0, min(seek_s / duration_s, 1.0))

        cur_min, cur_sec = divmod(int(seek_s), 60)
        tot_min, tot_sec = divmod(duration_s, 60)
        current_time = f"{cur_min}:{cur_sec:02d}"
        total_duration = f"{tot_min}:{tot_sec:02d}"

        progress_margin = 2
        progress_width = screen_width - (progress_margin * 2)
        progress_x = progress_margin
        time_y, progress_y = 20, 34

        draw.text((2, time_y), current_time, font=self.font_artist, fill="white")
        dur_w, _ = draw.textsize(total_duration, font=self.font_artist)
        draw.text((screen_width - dur_w - 2, time_y), total_duration, font=self.font_artist, fill="white")

        draw.line([progress_x, progress_y, progress_x + progress_width, progress_y], fill="white", width=1)
        indicator_x = progress_x + int(progress_width * progress)
        draw.line([indicator_x, progress_y - 2, indicator_x, progress_y + 2], fill="white", width=1)

        # --- Horizontal bar VU meters with peak hold ---
        num_cells, cell_w, cell_h, cell_spacing = 64, 2, 5, 7
        left_row_y, right_row_y, row_x0 = 41, 57, 22
        left_cells = int((left / 255.0) * num_cells)
        right_cells = int((right / 255.0) * num_cells)

        now = time.time()

        # Left peak
        if left_cells > self.left_peak_cell or now - self.left_peak_time > (self.peak_hold_ms / 1000):
            self.left_peak_cell, self.left_peak_time = left_cells, now
        elif left_cells < self.left_peak_cell and now - self.left_peak_time > (self.peak_hold_ms / 1000):
            self.left_peak_cell = left_cells

        # Right peak
        if right_cells > self.right_peak_cell or now - self.right_peak_time > (self.peak_hold_ms / 1000):
            self.right_peak_cell, self.right_peak_time = right_cells, now
        elif right_cells < self.right_peak_cell and now - self.right_peak_time > (self.peak_hold_ms / 1000):
            self.right_peak_cell = right_cells

        for i in range(left_cells):
            x = row_x0 + i * cell_spacing
            draw.rectangle([(x, left_row_y), (x + cell_w, left_row_y + cell_h)], fill="white")
        for i in range(right_cells):
            x = row_x0 + i * cell_spacing
            draw.rectangle([(x, right_row_y), (x + cell_w, right_row_y + cell_h)], fill="white")

        if self.left_peak_cell > 0:
            peak_x = row_x0 + (self.left_peak_cell - 1) * cell_spacing
            draw.rectangle([(peak_x, left_row_y), (peak_x + cell_w, left_row_y + cell_h)], fill="white")
        if self.right_peak_cell > 0:
            peak_x = row_x0 + (self.right_peak_cell - 1) * cell_spacing
            draw.rectangle([(peak_x, right_row_y), (peak_x + cell_w, right_row_y + cell_h)], fill="white")

        self.logger.debug("DigitalVUScreen: Horizontal VU bars + peak markers drawn.")

        # --- Artist/title/info lines ---
        # --- Artist/title/info lines ---
        try:
            title = data.get("title", "Unknown Title")
            artist = data.get("artist", "Unknown Artist")
            combined = f"{artist} - {title}"
            if len(combined) > 40:
                combined = combined[:37] + "..."

            # Measure text size
            text_w, text_h = draw.textsize(combined, font=self.font)

            # Draw title (centred, shifted down slightly)
            title_y = -1  # adjust up/down as needed
            draw.text(((screen_width - text_w) // 2, title_y), combined, font=self.font, fill="white")

            # Info line (volume / samplerate / bitdepth), centre it above progress bar
            samplerate = data.get("samplerate", "N/A")
            bitdepth   = data.get("bitdepth", "N/A")
            volume     = data.get("volume", "N/A")
            info_text  = f"Vol: {volume} / {samplerate} / {bitdepth}"
            info_w, info_h = draw.textsize(info_text, font=self.font_artist)

            info_y = progress_y - info_h - 2  # just above progress bar
            draw.text(((screen_width - info_w) // 2, info_y), info_text, font=self.font_artist, fill="white")

            self.logger.debug("DigitalVUScreen: Artist/title and info line drawn.")
        except Exception as e:
            self.logger.error("DigitalVUScreen: Error rendering text: %s", e)


        # --- Push to OLED ---
        try:
            frame = frame.convert(self.display_manager.oled.mode)
            self.display_manager.display_pil(frame)
            self.logger.info("DigitalVUScreen: Frame sent to display.")
        except Exception as e:
            self.logger.error("DigitalVUScreen: Error displaying frame: %s", e)


    def display_playback_info(self):
        """
        If needed, manually refresh the display with the current state.
        """
        state = self.volumio_listener.get_current_state()
        if state:
            self.draw_display(state)
        else:
            self.logger.warning("DigitalVUScreen: No current volumio state available to display.")

    def toggle_play_pause(self):
        """Emit Volumio play/pause toggle if connected."""
        self.logger.info("DigitalVUScreen: Toggling play/pause.")
        if not self.volumio_listener or not self.volumio_listener.is_connected():
            self.logger.warning("DigitalVUScreen: Not connected to Volumio => cannot toggle.")
            return
        try:
            self.volumio_listener.socketIO.emit("toggle", {})
            self.logger.debug("DigitalVUScreen: Emitted 'toggle' event.")
        except Exception as e:
            self.logger.error(f"DigitalVUScreen: toggle_play_pause failed => {e}")
