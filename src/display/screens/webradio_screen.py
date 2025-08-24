import os
import logging
from PIL import Image, ImageDraw, ImageFont
import threading
import time
import requests
from io import BytesIO

class WebRadioScreen:
    """
    A simplified WebRadio screen that displays:
      - Line 1: Title (truncated to 20 characters)
      - Line 2: Artist
      - A solid horizontal separator between the top and bottom sections
      - Line 3: Service (or stream)
      - Line 4: "Vol: {volume} | {quality}"
    Additionally, if album art is available it is pasted in the upper-right corner.
    """

    def __init__(self, display_manager, volumio_listener, mode_manager):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.ERROR)

        self.display_manager = display_manager
        self.volumio_listener = volumio_listener
        self.mode_manager = mode_manager

        # State & screen activity
        self.is_active = False
        self.latest_state = None
        self.current_state = None
        self.state_lock = threading.Lock()
        self.update_event = threading.Event()
        self.stop_event = threading.Event()

        # Fonts (ensure these exist in display_manager.fonts or use fallback)
        self.font_title = display_manager.fonts.get('radio_title', ImageFont.load_default())
        self.font_label = display_manager.fonts.get('radio_bitrate', ImageFont.load_default())
        self.font_small = display_manager.fonts.get('radio_small', ImageFont.load_default())

        # Display update thread
        self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
        self.update_thread.start()
        self.logger.info("WebRadioScreen: Started background update thread.")

        # Connect to Volumio listener
        if self.volumio_listener:
            self.volumio_listener.state_changed.connect(self.on_volumio_state_change)
        self.logger.info("WebRadioScreen initialised.")

    # ------------------------------------------------------------------
    # Volumio State Change
    # ------------------------------------------------------------------
    def on_volumio_state_change(self, sender, state):
        """
        Update display only if the screen is active, in 'webradio' mode,
        and the service is one of the allowed values.
        """
        if not self.is_active:
            self.logger.debug("WebRadioScreen: ignoring state change; screen not active.")
            return

        if self.mode_manager.get_mode() != 'webradio':
            self.logger.debug("WebRadioScreen: ignoring state change; not in webradio mode.")
            return

        if state.get("service") not in ["webradio"]:
            self.logger.debug("WebRadioScreen: ignoring state change; service not allowed.")
            return

        self.logger.debug(f"WebRadioScreen: state changed => {state}")
        with self.state_lock:
            self.latest_state = state
        self.update_event.set()

    # ------------------------------------------------------------------
    # Background Update Loop
    # ------------------------------------------------------------------
    def update_display_loop(self):
        """
        Wait for updates (or timeout periodically) and then refresh the display.
        """
        while not self.stop_event.is_set():
            triggered = self.update_event.wait(timeout=0.1)
            with self.state_lock:
                if triggered and self.latest_state:
                    self.current_state = self.latest_state.copy()
                    self.latest_state = None
                    self.update_event.clear()
            if self.is_active and self.mode_manager.get_mode() == 'webradio' and self.current_state:
                self.draw_display(self.current_state)

    # ------------------------------------------------------------------
    # Start/Stop
    # ------------------------------------------------------------------
    def start_mode(self):
        """
        Called when ModeManager transitions to 'webradio' mode.
        Forces an immediate getState from Volumio.
        """
        if self.mode_manager.get_mode() != 'webradio':
            self.logger.warning("WebRadioScreen: Attempted start, but mode != 'webradio'.")
            return

        self.is_active = True

        try:
            if self.volumio_listener and self.volumio_listener.socketIO:
                self.logger.debug("WebRadioScreen: Forcing getState from Volumio.")
                self.volumio_listener.socketIO.emit("getState", {})
        except Exception as e:
            self.logger.warning(f"WebRadioScreen: Failed to emit 'getState'. Error => {e}")

        if not self.update_thread.is_alive():
            self.stop_event.clear()
            self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
            self.update_thread.start()
            self.logger.debug("WebRadioScreen: display update thread restarted.")

    def stop_mode(self):
        """
        Called when leaving 'webradio' mode.
        """
        if not self.is_active:
            self.logger.debug("WebRadioScreen: stop_mode called but not active.")
            return

        self.is_active = False
        self.stop_event.set()
        self.update_event.set()

        if self.update_thread.is_alive():
            self.update_thread.join(timeout=1)
            self.logger.debug("WebRadioScreen: display update thread stopped.")

        self.display_manager.clear_screen()
        self.logger.info("WebRadioScreen: Stopped mode and cleared screen.")

    # ------------------------------------------------------------------
    # Volume Adjustment
    # ------------------------------------------------------------------
    def adjust_volume(self, volume_change):
        """
        Adjust volume via an external call (e.g. a rotary encoder).
        Emits a volume change to Volumio via the socketIO connection.
        """
        if not self.volumio_listener:
            self.logger.error("WebRadioScreen: no volumio_listener, cannot adjust volume.")
            return

        if self.latest_state is None:
            self.logger.debug("WebRadioScreen: latest_state is None, assuming volume=100.")
            self.latest_state = {"volume": 100}

        with self.state_lock:
            curr_vol = self.latest_state.get("volume", 100)
            new_vol = max(0, min(int(curr_vol) + volume_change, 100))

        self.logger.info(f"WebRadioScreen: Adjusting volume from {curr_vol} to {new_vol}.")
        try:
            if volume_change > 0:
                self.volumio_listener.socketIO.emit("volume", "+")
            elif volume_change < 0:
                self.volumio_listener.socketIO.emit("volume", "-")
            else:
                self.volumio_listener.socketIO.emit("volume", new_vol)
        except Exception as e:
            self.logger.error(f"WebRadioScreen: error adjusting volume => {e}")

    def display_radioplayback_info(self):
        """
        Manually refresh the display with the current state.
        """
        if not self.is_active:
            self.logger.info("WebRadioScreen: display_radioplayback_info called, but mode is not active.")
            return

        state = self.volumio_listener.get_current_state()
        if state:
            self.draw_display(state)
        else:
            self.logger.warning("WebRadioScreen: No current volumio state available to display.")

    # ------------------------------------------------------------------
    # Album Art Helper
    # ------------------------------------------------------------------
    def get_albumart(self, url):
        """
        Download and return an Image object from the given album art URL.
        If no URL is provided or downloading fails, load the default album art
        specified in the display configuration.
        """
        if not url:
            default_path = self.display_manager.config.get("default_album_art")
            if default_path and os.path.exists(default_path):
                try:
                    img = Image.open(default_path)
                    return img.convert("RGB")
                except Exception as e:
                    self.logger.error(f"Failed to load default album art from {default_path}: {e}")
                    return None
            else:
                self.logger.error("No album art URL provided and default album art not found.")
                return None

        try:
            response = requests.get(url, timeout=3)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            return img.convert("RGB")
        except Exception as e:
            self.logger.error(f"Failed to load album art from {url}: {e}")
            default_path = self.display_manager.config.get("default_album_art")
            if default_path and os.path.exists(default_path):
                try:
                    img = Image.open(default_path)
                    return img.convert("RGB")
                except Exception as e:
                    self.logger.error(f"Failed to load default album art from {default_path}: {e}")
                    return None
            return None

    # ------------------------------------------------------------------
    # Drawing the Screen
    # ------------------------------------------------------------------
    def draw_display(self, data):
        """
        Draws the following on the OLED:
        - Line 1: Title (truncated to 20 characters; moved down by 5 pixels if service is "webradio")
        - Line 2: Artist (if available)
        - A solid horizontal separator between the top and bottom sections
        - Line 3: Service (or stream)
        - Line 4: "Vol: {volume} | {quality}"
        Additionally, if album art is available it is pasted in the upper-right corner.
        """
        # Create a blank image with a black background.
        base_image = Image.new("RGB", self.display_manager.oled.size, "black")
        draw = ImageDraw.Draw(base_image)
        margin = 5
        line_height = 12  # Base line height

        # Get display dimensions.
        screen_width, screen_height = self.display_manager.oled.size

        # Get the data values with fallbacks.
        title = data.get("title") or "Radio"
        if len(title) > 20:
            title = title[:20] + "…"
        artist = data.get("artist") or ""
        service = (data.get("service") or data.get("stream") or "WebRadio").strip()

        # If service is "webradio", add an extra offset for the title.
        extra_title_offset = 1 if service.lower() == "webradio" else 0

        # Adjust vertical offsets based on whether artist text is available.
        if artist:
            title_y = margin - 7 + extra_title_offset       # Title vertical position
            artist_y = margin + line_height - 2              # Artist vertical position
            divider_y = margin + 2 * line_height + 5         # Divider positioned after artist
        else:
            # If no artist, draw the title and move the divider up so there’s no blank artist space.
            title_y = margin - 7 + extra_title_offset
            # Skip drawing the artist line.
            divider_y = margin + line_height + 5

        # Service and volume lines remain the same.
        service_y = divider_y + 3          # Offset for Service (or stream)
        info_y = divider_y + line_height + 6  # Offset for Volume/Quality info

        # Draw the Title.
        draw.text((margin, title_y), title, font=self.font_title, fill="white")

        # Draw the Artist only if it's not empty.
        if artist:
            draw.text((margin, artist_y), artist, font=self.font_small, fill="white")

        # Draw a solid horizontal separator.
        album_art_width = 60              # The width of your album art.
        gap_between_line_and_art = 15     # Gap between the end of the line and the album art.
        line_end_x = screen_width - margin - album_art_width - gap_between_line_and_art
        draw.line((margin, divider_y, line_end_x, divider_y), fill="white")

        # Draw the Service (or stream).
        draw.text((margin, service_y), service, font=self.font_small, fill="white")

        # Prepare the Volume and Quality info.
        volume = str(data.get("volume") or "0")
        bitrate = data.get("bitrate")
        quality = bitrate if bitrate else "Live"
        info_line = f"Vol: {volume} | {quality}"
        draw.text((margin, info_y), info_line, font=self.font_label, fill="white")


        # Display album art on the upper-right if available.
        albumart_url = data.get("albumart")
        if albumart_url:
            albumart = self.get_albumart(albumart_url)
            if albumart:
                album_art_size = (album_art_width, album_art_width)
                albumart = albumart.resize(album_art_size, Image.LANCZOS)
                art_x = screen_width - album_art_size[0] - margin
                art_y = margin
                base_image.paste(albumart, (art_x, art_y))

        # Send the composed image to the OLED display.
        self.display_manager.display_pil(base_image)
        self.logger.debug("WebRadioScreen: Display updated with adjusted vertical offsets.")

    def toggle_play_pause(self):
        """
        Toggle play/pause if connected.
        """
        self.logger.info("WebRadioScreen: Toggling play/pause.")
        if not self.volumio_listener or not self.volumio_listener.is_connected():
            self.logger.warning("WebRadioScreen: Not connected to Volumio => cannot toggle.")
            return
        try:
            self.volumio_listener.socketIO.emit("toggle", {})
            self.logger.debug("WebRadioScreen: Emitted 'toggle' event.")
        except Exception as e:
            self.logger.error(f"WebRadioScreen: toggle_play_pause failed => {e}")
