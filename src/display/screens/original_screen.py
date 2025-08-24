# src/display/screens/original_screen.py

import logging
import re
import threading
import time

from PIL import Image, ImageDraw, ImageFont, ImageSequence
from managers.menus.base_manager import BaseManager  # Or whichever base class your project uses

class OriginalScreen(BaseManager):
    """
    A screen class for 'Original' playback mode. It uses VolumioListener
    for state changes and updates an 'original'-style display (e.g. a
    classic FM4-like screen).
    """

    def __init__(self, display_manager, volumio_listener, mode_manager):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)

        self.mode_manager = mode_manager
        self.volumio_listener = volumio_listener

        self.previous_service = None

        # Thread-safe state handling
        self.latest_state = None
        self.state_lock = threading.Lock()
        self.update_event = threading.Event()
        self.stop_event = threading.Event()
        self.is_active = False

        # Background update thread
        self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
        self.update_thread.start()
        self.logger.info("OriginalScreen: Started background update thread.")

        # Register a callback for Volumio state changes
        if self.volumio_listener:
            self.volumio_listener.state_changed.connect(self.on_volumio_state_change)
        self.logger.info("OriginalScreen initialized.")

    # ------------------------------------------------------------------
    #   Volumio State Change Handler
    # ------------------------------------------------------------------
    def on_volumio_state_change(self, sender, state):
        """
        Callback for volumio_listener.state_changed.
        Only process if:
          - This OriginalScreen is active AND
          - The ModeManager's current mode == 'original'.
        """
        if not self.is_active or self.mode_manager.get_mode() != 'original':
            self.logger.debug(
                "OriginalScreen: Ignoring state change "
                "since not active or mode != 'original'."
            )
            return

        # If service is webradio, skip updating 'original' screen
        service = state.get('service', '').lower()
        if service == "webradio":
            self.logger.debug("OriginalScreen: ignoring webradio service for 'original' screen.")
            return

        # If ModeManager is suppressing state changes, skip
        if self.mode_manager.is_state_change_suppressed():
            self.logger.debug("OriginalScreen: State change suppressed, no display update.")
            return

        self.logger.debug(f"OriginalScreen: Received volumio state => {state}")
        with self.state_lock:
            self.latest_state = state
        self.update_event.set()

    # ------------------------------------------------------------------
    #   Background Update Thread
    # ------------------------------------------------------------------
    def update_display_loop(self):
        """
        Background loop for OriginalScreen.
        Waits for state updates or times out,
        and simulates seek only while playing.
        """
        last_update_time = time.time()
        while not self.stop_event.is_set():
            triggered = self.update_event.wait(timeout=0.1)

            with self.state_lock:
                if triggered and self.latest_state:
                    state_to_process = self.latest_state.copy()
                    self.latest_state = None
                    self.update_event.clear()
                    last_update_time = time.time()
                elif self.is_active and self.current_state:
                    state_to_process = self.current_state.copy()
                    status = (state_to_process.get("status") or "").lower()
                    duration_val = state_to_process.get("duration")

                    try:
                        duration_ok = int(duration_val) > 0
                    except Exception:
                        duration_ok = False

                    if status == "play" and duration_ok:
                        elapsed = time.time() - last_update_time
                        state_to_process["seek"] = int(state_to_process.get("seek") or 0) + int(elapsed * 1000)

                    last_update_time = time.time()
                else:
                    state_to_process = None

            if self.is_active and self.mode_manager.get_mode() == "original" and state_to_process:
                if not self.mode_manager.is_state_change_suppressed():
                    self.current_state = state_to_process
                    self.draw_display(state_to_process)


    # ------------------------------------------------------------------
    #   Start/Stop Mode
    # ------------------------------------------------------------------
    def start_mode(self):
        """
        Called by ModeManager (enter_original) when switching to 'original' mode.
        """
        # Check if the current mode is indeed 'original'
        if self.mode_manager.get_mode() != 'original':
            self.logger.warning(
                "OriginalScreen: Attempted to start, but current mode != 'original'."
            )
            return

        self.is_active = True
        self.logger.info("OriginalScreen: Activated 'original' screen mode.")

        # 1) Force an immediate getState from Volumio
        try:
            if self.volumio_listener and self.volumio_listener.socketIO:
                self.logger.debug("OriginalScreen: Forcing getState from Volumio.")
                self.volumio_listener.socketIO.emit("getState", {})
        except Exception as e:
            self.logger.warning(f"OriginalScreen: Failed to emit 'getState'. => {e}")

        # 2) Display current Volumio state if available
        current_state = self.volumio_listener.get_current_state()
        if current_state:
            self.draw_display(current_state)
        else:
            self.logger.warning("OriginalScreen: No current Volumio state to display.")


    def stop_mode(self):
        """
        Deactivate the OriginalScreen.
        Called by ModeManager when leaving 'original' mode.
        """
        if not self.is_active:
            self.logger.debug("OriginalScreen: stop_mode called, but not active.")
            return

        self.is_active = False
        self.stop_event.set()
        self.update_event.set()  # Unblock the thread if it's waiting

        try:
            if self.update_thread.is_alive():
                self.update_thread.join(timeout=1)
                if self.update_thread.is_alive():
                    self.logger.warning("OriginalScreen: Timed out stopping update thread.")
        except Exception as e:
            self.logger.error(f"OriginalScreen: Error stopping update thread => {e}")

        self.display_manager.clear_screen()
        self.logger.info("OriginalScreen: Stopped and cleared display.")

    # ------------------------------------------------------------------
    #   Drawing / Display Logic
    # ------------------------------------------------------------------
    def draw_display(self, data):
        """
        Main method to draw the 'original' style display:
          - Volume bars
          - Sample rate
          - Bit depth
          - Possibly service icon
        """
        self.logger.debug(f"OriginalScreen: draw_display with data => {data}")

        # Basic service & status checks
        service = data.get("service", "").lower()
        track_type = data.get("trackType", "").lower()
        status = data.get("status", "").lower()

        # Override service if it's mpd but trackType is tidal, qobuz, etc.
        if service == "mpd" and track_type in ["tidal", "qobuz", "spotify"]:
            service = track_type

        # If paused/stopped, maintain previous service if we have one
        if status in ["pause", "stop"] and not service:
            service = self.previous_service or "default"
        else:
            if service and service != self.previous_service:
                self.display_manager.clear_screen()
                self.logger.info(f"OriginalScreen: Service changed => {service}, screen cleared.")
            self.previous_service = service or self.previous_service or "default"

        # Create new image & draw object
        base_image = Image.new("RGB", self.display_manager.oled.size, "black")
        draw = ImageDraw.Draw(base_image)

        # Volume bars
        volume = max(0, min(int(data.get("volume", 0)), 100))
        filled_squares = round((volume / 100) * 6)
        square_size = 3
        row_spacing = 5
        padding_bottom = 6
        columns = [10, 26]
        for x in columns:
            for row in range(filled_squares):
                y = self.display_manager.oled.height - padding_bottom - ((row + 1) * (square_size + row_spacing))
                draw.rectangle([x, y, x + square_size, y + square_size], fill="white")
        self.logger.debug(f"OriginalScreen: Drew volume => {filled_squares} squares for volume={volume}.")

        # Additional info (sample rate, bit depth, service icon)
        self._draw_more_info(draw, base_image, data, service)

        # Finally update display
        self.display_manager.display_pil(base_image)
        self.logger.info("OriginalScreen: Display updated.")

    def _draw_more_info(self, draw, base_image, data, service):
        """
        Helper to draw sample rate, bit depth, and possibly a service icon.
        """
        samplerate = data.get("samplerate", "")
        bitdepth   = data.get("bitdepth", "N/A")

        # Sample rate parsing
        try:
            import re
            match = re.match(r"([\d\.]+)\s*(\w+)", samplerate)
            if match:
                sample_val = float(match.group(1))
                sample_unit = match.group(2).lower()
                sample_val = int(sample_val)  # e.g. 44
            else:
                sample_val = "N/A"
                sample_unit = ""
        except (ValueError, TypeError):
            sample_val = "N/A"
            sample_unit = ""

        # Normalize the unit
        if sample_unit in ["khz", "hz"]:
            sample_unit = sample_unit.upper()
        elif sample_unit == "kbps":
            sample_unit = "kbps"
        else:
            sample_unit = "kHz"  # fallback if we can't parse

        # Load any fonts
        sample_val_font  = self.display_manager.fonts.get('sample_rate', ImageFont.load_default())
        sample_unit_font = self.display_manager.fonts.get('sample_rate_khz', ImageFont.load_default())
        font_info        = self.display_manager.fonts.get('radio_bitrate', ImageFont.load_default())

        # Define X position for sample rate
        sample_right_x = self.display_manager.oled.width - 70

        # Positions for numeric sample rate vs. unit text
        sample_val_y  = 10    # Move this up or down to place the number
        sample_unit_y = sample_val_y + 33  # Move the unit further down (change 24 as you like)

        val_str = str(sample_val)
        val_w, val_h = draw.textsize(val_str, font=sample_val_font)
        unit_w, unit_h = draw.textsize(sample_unit, font=sample_unit_font)

        # Place the numeric value
        val_x = sample_right_x - unit_w - val_w - 4
        draw.text((val_x, sample_val_y), val_str, font=sample_val_font, fill="white")

        # Place the unit (kHz, kbps, etc.)
        unit_x = val_x + val_w + 1
        draw.text((unit_x, sample_unit_y), sample_unit, font=sample_unit_font, fill="white")

        self.logger.debug("OriginalScreen: Drew sample rate => %s %s", val_str, sample_unit)

        # Draw bit depth
        padding = 15
        x_position = self.display_manager.oled.width - padding
        y_position = 50
        draw.text((x_position, y_position), bitdepth, font=font_info, fill="white", anchor="rm")
        self.logger.debug(f"OriginalScreen: Drew bit depth => {bitdepth}")

        # Draw service icon if we have one
        icon = self.display_manager.icons.get(service)
        if icon:
            # Flatten alpha if needed
            if icon.mode == "RGBA":
                bg = Image.new("RGB", icon.size, (0, 0, 0))
                bg.paste(icon, mask=icon.split()[3])
                icon = bg
            icon_padding_right = 12
            icon_padding_top   = 6
            icon_x = self.display_manager.oled.width - icon.width - icon_padding_right
            icon_y = icon_padding_top
            base_image.paste(icon, (icon_x, icon_y))
            self.logger.debug(f"OriginalScreen: Pasted service icon '{service}' at ({icon_x}, {icon_y}).")
        else:
            # Fallback to default icon if available
            icon = self.display_manager.default_icon
            if icon:
                if icon.mode == "RGBA":
                    bg = Image.new("RGB", icon.size, (0,0,0))
                    bg.paste(icon, mask=icon.split()[3])
                    icon = bg
                icon_x = self.display_manager.oled.width - icon.width - 20
                icon_y = 5
                base_image.paste(icon, (icon_x, icon_y))
                self.logger.debug(f"OriginalScreen: Pasted default icon at ({icon_x}, {icon_y}).")
            else:
                self.logger.warning("OriginalScreen: No icon or default icon available.")


    # ------------------------------------------------------------------
    #   Volume Control / Toggling
    # ------------------------------------------------------------------
    def adjust_volume(self, volume_change):
        """
        Called externally to adjust volume from the rotary or another source.
        """
        if not self.volumio_listener:
            self.logger.error("OriginalScreen: No volumio_listener to adjust volume.")
            return

        # If we haven't had a state yet, assume volume=100
        if self.latest_state is None:
            self.logger.debug("OriginalScreen: latest_state=None => assume volume=100.")
            self.latest_state = {"volume": 100}

        with self.state_lock:
            current_vol = int(self.latest_state.get("volume", 100))
            new_vol = max(0, min(current_vol + volume_change, 100))

        self.logger.info(f"OriginalScreen: Adjust volume from {current_vol} to {new_vol}.")
        try:
            # Volumio can accept direct integer or +/- for volume
            if volume_change > 5:
                self.volumio_listener.socketIO.emit("volume", "+")
            elif volume_change < 5:
                self.volumio_listener.socketIO.emit("volume", "-")
            else:
                self.volumio_listener.socketIO.emit("volume", new_vol)
        except Exception as e:
            self.logger.error(f"OriginalScreen: Volume emit failed => {e}")

    def toggle_play_pause(self):
        """
        Toggle playback via Volumio.
        """
        self.logger.info("OriginalScreen: Toggling play/pause.")
        if not self.volumio_listener or not self.volumio_listener.is_connected():
            self.logger.warning("OriginalScreen: Not connected to Volumio => cannot toggle.")
            return
        try:
            self.volumio_listener.socketIO.emit("toggle", {})
            self.logger.debug("OriginalScreen: Emitted 'toggle' event for play/pause.")
        except Exception as e:
            self.logger.error(f"OriginalScreen: toggle_play_pause failed => {e}")

    # ------------------------------------------------------------------
    #   Utility
    # ------------------------------------------------------------------
    def display_error_message(self, title, message):
        """
        Show a brief error message on the screen.
        """
        with self.display_manager.lock:
            img = Image.new("RGB", self.display_manager.oled.size, "black")
            draw = ImageDraw.Draw(img)
            from PIL import ImageFont
            font = self.display_manager.fonts.get('error_font', ImageFont.load_default())

            title_w, _ = draw.textsize(title, font=font)
            title_x = (self.display_manager.oled.width - title_w) // 2
            title_y = 10
            draw.text((title_x, title_y), title, font=font, fill="red")

            msg_w, _ = draw.textsize(message, font=font)
            msg_x = (self.display_manager.oled.width - msg_w) // 2
            msg_y = title_y + 20
            draw.text((msg_x, msg_y), message, font=font, fill="white")

            final_img = img.convert(self.display_manager.oled.mode)
            self.display_manager.oled.display(final_img)
            self.logger.info(f"Displayed error => {title}: {message}")
            time.sleep(2)
            # Optionally redraw the normal display or just leave it cleared.
