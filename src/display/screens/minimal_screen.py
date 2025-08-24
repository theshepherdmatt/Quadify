import logging
import os
import threading
import time
from PIL import Image, ImageDraw, ImageFont
from managers.menus.base_manager import BaseManager

class MinimalScreen(BaseManager):
    """
    A minimalist screen style akin to Hegel’s design:
      - Large volume number on the right
      - Service name (e.g. Tidal, Qobuz) on the left
      - Small sample rate & bit depth text below the service
      - Very minimal, white-on-black layout
    """

    def __init__(self, display_manager, volumio_listener, mode_manager):
        super().__init__(display_manager, volumio_listener, mode_manager)

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)

        self.mode_manager     = mode_manager
        self.volumio_listener = volumio_listener

        # Fonts defined in your config:
        #   minimal_volume   => Montserrat-Bold,   size=27
        #   minimal_service  => Montserrat-Regular, size=18
        #   minimal_data     => Montserrat-Regular, size=5
        self.font_volume  = display_manager.fonts.get('minimal_volume', ImageFont.load_default())
        self.font_service = display_manager.fonts.get('minimal_service', ImageFont.load_default())
        self.font_data    = display_manager.fonts.get('minimal_data', ImageFont.load_default())

        # State & threading
        self.latest_state  = None
        self.current_state = None
        self.state_lock    = threading.Lock()
        self.update_event  = threading.Event()
        self.stop_event    = threading.Event()
        self.is_active     = False

        # Initialize a variable to track the last update time for progress simulation
        self.last_update_time = time.time()

        # Display update thread
        self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
        self.update_thread.start()
        self.logger.info("MinimalScreen: Started background update thread.")

        # Connect Volumio state listener
        if self.volumio_listener:
            self.volumio_listener.state_changed.connect(self.on_volumio_state_change)
        self.logger.info("MinimalScreen initialized.")

    # ------------------------------------------------------------------
    #   Volumio State Change
    # ------------------------------------------------------------------
    def on_volumio_state_change(self, sender, state):
        if not self.is_active or self.mode_manager.get_mode() != 'minimal':
            self.logger.debug("MinimalScreen: ignoring state change; not active or mode != 'minimal'.")
            return

        self.logger.debug(f"MinimalScreen: state changed => {state}")
        with self.state_lock:
            if "volume" in state:
                self.current_volume = state["volume"]
            self.latest_state = state
        self.update_event.set()

    # ------------------------------------------------------------------
    #   Background Update Loop
    # ------------------------------------------------------------------
    def update_display_loop(self):
        """
        Background loop for MinimalScreen.
        Waits on update_event or times out,
        and simulates progress updates only while playing.
        """
        while not self.stop_event.is_set():
            triggered = self.update_event.wait(timeout=0.1)

            with self.state_lock:
                if triggered and self.latest_state:
                    self.current_state = self.latest_state.copy()
                    self.latest_state = None
                    self.last_update_time = time.time()
                    self.update_event.clear()

                elif (
                    self.current_state
                    and self.current_state.get("status") == "play"
                    and "seek" in self.current_state
                    and "duration" in self.current_state
                ):
                    # Simulate progress only while actively playing
                    elapsed = time.time() - self.last_update_time
                    self.current_state["seek"] = self.current_state.get("seek", 0) + int(elapsed * 1000)
                    self.last_update_time = time.time()

            if self.is_active and self.mode_manager.get_mode() == "minimal" and self.current_state:
                self.draw_display(self.current_state)


    # ------------------------------------------------------------------
    #   Start / Stop
    # ------------------------------------------------------------------
    def start_mode(self):
        """
        Called when ModeManager transitions to 'minimal' mode.
        """
        if self.mode_manager.get_mode() != 'minimal':
            self.logger.warning("MinimalScreen: Attempted start, but mode != 'minimal'.")
            return

        self.is_active = True
        self.display_manager.clear_screen()

        # Force immediate getState (optional) so we’re not waiting on pushState
        try:
            if self.volumio_listener and self.volumio_listener.socketIO:
                self.logger.debug("MinimalScreen: Forcing getState from Volumio.")
                self.volumio_listener.socketIO.emit("getState", {})
        except Exception as e:
            self.logger.warning(f"MinimalScreen: Failed to emit 'getState'. Error => {e}")

        # If update_thread is dead, restart it
        if not self.update_thread.is_alive():
            self.stop_event.clear()
            self.update_thread = threading.Thread(target=self.update_display_loop, daemon=True)
            self.update_thread.start()
            self.logger.debug("MinimalScreen: display update thread restarted.")

    def stop_mode(self):
        """
        Called when leaving 'minimal' mode in ModeManager.
        """
        if not self.is_active:
            self.logger.debug("MinimalScreen: stop_mode called but not active.")
            return

        self.is_active = False
        self.stop_event.set()
        self.update_event.set()

        if self.update_thread.is_alive():
            self.update_thread.join(timeout=1)
            self.logger.debug("MinimalScreen: display update thread stopped.")

        self.display_manager.clear_screen()
        self.logger.info("MinimalScreen: Stopped mode and cleared screen.")

    # ------------------------------------------------------------------
    #   Helper Method: Draw Anti-Aliased Circle
    # ------------------------------------------------------------------
    @staticmethod
    def draw_anti_aliased_circle(draw, center, radius, arc_width, progress, fill_color="white", bg_color="#303030"):
        """
        Draws an anti-aliased circular progress indicator using supersampling.
        - draw: The ImageDraw.Draw object on the high-res image.
        - center: Tuple (x, y) centre of the circle on the high-res canvas.
        - radius: The circle's radius on the high-res canvas.
        - arc_width: The thickness of the arc on the high-res canvas.
        - progress: A float between 0.0 and 1.0.
        - fill_color: Colour of the progress arc.
        - bg_color: Colour of the background circle.
        """
        cx, cy = center
        bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
        start_angle = -90
        end_angle = start_angle + (progress * 360)
        draw.ellipse(bbox, outline=bg_color, width=arc_width)
        draw.arc(bbox, start=start_angle, end=end_angle, fill=fill_color, width=arc_width)

    # ------------------------------------------------------------------
    #   Drawing
    # ------------------------------------------------------------------
    def draw_display(self, state):
        """
        Minimal UI with an anti-aliased round progress indicator.
        - Left side: service name, sample rate/bit depth, and volume (below sample text).
        - Bottom-right: circular progress indicator with larger duration text.
        """
        # Create base image at target resolution
        base_image = Image.new("RGB", self.display_manager.oled.size, "black")
        draw = ImageDraw.Draw(base_image)
        width, height = self.display_manager.oled.size

        # ------------------------------------------------------------------
        # 1) Extract data from Volumio state
        # ------------------------------------------------------------------
        raw_service = state.get("service", "Network").lower()
        track_type  = state.get("trackType", "").lower()
        if raw_service == "mpd" and track_type in ["tidal", "qobuz", "spotify", "rparadise"]:
            raw_service = track_type

        # Shorten the display name for Radio Paradise
        if raw_service in ["radioparadise", "radio_paradise"]:
            service_display = "RadioP"
        else:
            service_display = raw_service.title()

        samplerate = state.get("samplerate", "44.1")
        bitdepth   = state.get("bitdepth", "16bit")
        volume     = state.get("volume", 0)

        # ------------------------------------------------------------------
        # 2) Draw service and sample text (right-aligned) near the top
        # ------------------------------------------------------------------
        service_right = 110
        service_y = 2  # moved upward
        service_w, service_h = draw.textsize(service_display, font=self.font_service)
        service_x = service_right - service_w
        draw.text((service_x, service_y), service_display, font=self.font_service, fill="white")

        sample_text = f"{samplerate} / {bitdepth}"
        sample_w, sample_h = draw.textsize(sample_text, font=self.font_data)
        sample_x = service_right - sample_w
        sample_y = service_y + service_h
        draw.text((sample_x, sample_y), sample_text, font=self.font_data, fill="white")

        # ------------------------------------------------------------------
        # 3) Draw volume below sample text
        # ------------------------------------------------------------------
        vol_str = "vol " + str(volume)
        vol_w, vol_h = draw.textsize(vol_str, font=self.font_volume)
        vol_x = service_right - vol_w
        vol_y = sample_y + sample_h - 2
        draw.text((vol_x, vol_y), vol_str, font=self.font_volume, fill="white")

        # ------------------------------------------------------------------
        # 4) Draw anti-aliased round progress indicator in bottom-right
        # ------------------------------------------------------------------
        # Retrieve playback position and duration
        seek_ms = state.get("seek", 0)
        duration_s = state.get("duration", 1)  # Avoid division by zero
        seek_s = max(0, seek_ms / 1000)
        progress = max(0.0, min(seek_s / duration_s, 1.0))

        # Set circle properties (smaller than before)
        circle_radius = 25  # slightly smaller than 30
        arc_width = 3
        scale = 4
        hi_res_radius = circle_radius * scale
        hi_res_arc_width = arc_width * scale

        hi_res_size = (hi_res_radius * 2, hi_res_radius * 2)
        hi_res_img = Image.new("RGBA", hi_res_size, (0, 0, 0, 0))
        hi_res_draw = ImageDraw.Draw(hi_res_img)
        hi_res_center = (hi_res_radius, hi_res_radius)

        MinimalScreen.draw_anti_aliased_circle(
            hi_res_draw,
            center=hi_res_center,
            radius=hi_res_radius,
            arc_width=hi_res_arc_width,
            progress=progress,
            fill_color="white",
            bg_color="#303030"
        )

        # Downscale the high-res circle image
        circle_img = hi_res_img.resize((circle_radius * 2, circle_radius * 2), Image.LANCZOS)

        # Place the circle in the bottom-right (further right than before)
        margin = 5
        circle_x = width - circle_radius * 4 - margin
        circle_y = height - circle_radius * 2 - margin - 2
        base_image.paste(circle_img, (circle_x, circle_y), circle_img)

        # ------------------------------------------------------------------
        # 5) Draw duration text inside the circle with a larger font
        # ------------------------------------------------------------------
        cur_min = int(seek_s // 60)
        cur_sec = int(seek_s % 60)
        current_time = f"{cur_min}:{cur_sec:02d}"
        # Attempt to create a larger variant of the duration font.
        try:
            duration_font = self.font_data.font_variant(size=self.font_data.size + 3)
        except Exception:
            duration_font = self.font_data
        text_w, text_h = duration_font.getsize(current_time)
        text_x = circle_x + (circle_radius * 2 - text_w) // 2
        text_y = circle_y + (circle_radius * 2 - text_h) // 2
        draw.text((text_x, text_y), current_time, font=duration_font, fill="white")

        # ------------------------------------------------------------------
        # 6) Display the final image
        # ------------------------------------------------------------------
        self.display_manager.display_pil(base_image)
        self.logger.debug("MinimalScreen: Display updated with minimal UI including updated progress indicator.")

    def display_playback_info(self):
        """
        If needed, manually refresh using the current state from volumio_listener.
        """
        if not self.is_active:
            self.logger.info("MinimalScreen: display_playback_info called, but mode is not active.")
            return

        state = self.volumio_listener.get_current_state()
        if state:
            self.draw_display(state)
        else:
            self.logger.warning("MinimalScreen: No current volumio state available to display.")

    def adjust_volume(self, volume_change):
        """
        Adjust volume from an external call (e.g. rotary).
        This emits a volume +/- to Volumio via self.volumio_listener.
        """
        if not self.volumio_listener:
            self.logger.error("MinimalScreen: no volumio_listener, cannot adjust volume.")
            return

        if self.latest_state is None:
            self.logger.debug("MinimalScreen: latest_state=None => assume volume=100.")
            self.latest_state = {"volume": 100}

        with self.state_lock:
            curr_vol = self.latest_state.get("volume", 100)
            new_vol = max(0, min(int(curr_vol) + volume_change, 100))

        self.logger.info(f"MinimalScreen: Adjusting volume from {curr_vol} to {new_vol}.")
        try:
            if volume_change > 0:
                self.volumio_listener.socketIO.emit("volume", "+")
            elif volume_change < 0:
                self.volumio_listener.socketIO.emit("volume", "-")
            else:
                self.volumio_listener.socketIO.emit("volume", new_vol)
        except Exception as e:
            self.logger.error(f"MinimalScreen: error adjusting volume => {e}")

    def toggle_play_pause(self):
        """Emit Volumio play/pause toggle if connected."""
        self.logger.info("MinimalScreen: Toggling play/pause.")
        if not self.volumio_listener or not self.volumio_listener.is_connected():
            self.logger.warning("MinimalScreen: Not connected to Volumio => cannot toggle.")
            return
        try:
            self.volumio_listener.socketIO.emit("toggle", {})
            self.logger.debug("MinimalScreen: Emitted 'toggle' event.")
        except Exception as e:
            self.logger.error(f"MinimalScreen: toggle_play_pause failed => {e}")