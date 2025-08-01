from managers.base_manager import BaseManager
from utils.menu_renderer import render_list_menu
import logging
from PIL import ImageFont
import threading
import time

class MotherEarthManager(BaseManager):
    def __init__(self, display_manager, volumio_listener, mode_manager,
                 window_size=4, y_offset=2, line_spacing=15):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.mode_name = "motherearthradio"
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)  # Detailed logging for troubleshooting
        self.logger.info("MotherEarthManager initialized (stations-only mode).")
        self.logger.debug(f"Configuration: window_size={window_size}, y_offset={y_offset}, line_spacing={line_spacing}")

        # List of stations (Mother Earth returns a single list)
        self.stations = []
        self.current_menu_items = []  # This will hold the station items for the menu
        self.current_selection_index = 0
        # In this manager we only have one menu (stations)
        self.current_menu = "stations"
        self.window_start_index = 0

        # Window settings for scrolling lists
        self.window_size = window_size
        self.y_offset = y_offset
        self.line_spacing = line_spacing

        # Font settings (keys defined in your config)
        self.font_key = 'menu_font'
        self.bold_font_key = 'menu_font_bold'
        self.font = self.display_manager.fonts.get(self.font_key, ImageFont.load_default())
        self.font_bold = self.display_manager.fonts.get(self.bold_font_key, ImageFont.load_default())

        # Tracking the last requested URI (for browseLibrary calls)
        self.last_requested_uri = None

        # Debounce handling for menu actions
        self.last_action_time = 0
        self.debounce_interval = 0.3  # seconds

        self.is_active = False

        # Timeout timer attribute for station loading
        self.timeout_timer = None

        # New: Refresh timer to periodically try to update the display/connection
        self.refresh_timer = None

    def display_loading_screen(self):
        """Display a loading message for Mother Earth."""
        self.logger.info("MotherEarthManager: Displaying loading screen.")
        def draw_callback(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "Loading Mother Earth...",
                font=self.font,
                fill="white"
            )
        self.display_manager.draw_custom(draw_callback)

    def start_mode(self):
        """Activate Mother Earth mode and fetch the station list."""
        if self.is_active:
            self.logger.debug("MotherEarthManager: Mode already active.")
            return
        self.logger.info("MotherEarthManager: Starting Mother Earth mode.")
        self.is_active = True
        self.current_selection_index = 0
        self.window_start_index = 0
        self.current_menu = "stations"
        self.stations.clear()
        self.current_menu_items = []  # Ensure this list is empty before fetching

        self.logger.debug("MotherEarthManager: Connecting navigation_received signal.")
        # Connect the navigation signal so that handle_navigation() is called
        self.volumio_listener.navigation_received.connect(self.handle_navigation)
        self.logger.info("MotherEarthManager: Connected to navigation_received signal.")

        # Display a loading screen before fetching stations
        self.display_loading_screen()

        self.fetch_stations()

        # Start a periodic refresh timer (e.g. every 30 seconds)
        self.refresh_timer = threading.Timer(30.0, self.periodic_refresh)
        self.refresh_timer.start()

        # Start timeout timer (e.g. 5 seconds) to check if station data has been received
        self.timeout_timer = threading.Timer(5.0, self.mother_earth_timeout)
        self.timeout_timer.start()

    def mother_earth_timeout(self):
        """Called when station data hasn't loaded within the timeout period."""
        if not self.current_menu_items:
            self.logger.warning("MotherEarthManager: Timeout reached, no station data received.")
            def draw_callback(draw_obj):
                draw_obj.text(
                    (10, self.y_offset),
                    "Mother Earth is not loading...",
                    font=self.font,
                    fill="white"
                )
                draw_obj.text(
                    (10, self.y_offset + self.line_spacing),
                    "Have you logged in via Volumio?",
                    font=self.font,
                    fill="white"
                )
            self.display_manager.draw_custom(draw_callback)

            # Automatically navigate back to the menu after 5 seconds.
            threading.Timer(3.0, self.mode_manager.to_menu).start()

    def periodic_refresh(self):
        """
        Periodically try to refresh the connection or update the display.
        This method re-fetches station data or re-displays the current menu.
        """
        self.logger.info("MotherEarthManager: Performing periodic refresh.")
        if self.volumio_listener.is_connected():
            # Option 1: Re-fetch station data.
            self.logger.info("MotherEarthManager: Re-fetching stations as part of refresh.")
            self.fetch_stations()
            # Option 2: Alternatively, if you only need to re-display the menu, you could call:
            # self.display_menu()
        else:
            self.logger.warning("MotherEarthManager: Volumio is not connected during refresh attempt.")
        # Restart the timer for the next refresh
        self.refresh_timer = threading.Timer(30.0, self.periodic_refresh)
        self.refresh_timer.start()

    def stop_mode(self):
        """Deactivate Mother Earth mode and clear the display."""
        self.logger.info("MotherEarthManager: Stopping Mother Earth mode.")
        self.is_active = False
        self.display_manager.clear_screen()
        try:
            self.volumio_listener.navigation_received.disconnect(self.handle_navigation)
            self.logger.debug("MotherEarthManager: Disconnected navigation_received signal.")
        except Exception as e:
            self.logger.debug(f"MotherEarthManager: Exception while disconnecting navigation signal: {e}")
        # Cancel the timeout timer if it's still running
        if self.timeout_timer:
            self.timeout_timer.cancel()
        # Cancel the refresh timer if it's still running
        if self.refresh_timer:
            self.refresh_timer.cancel()

    def fetch_stations(self):
        """
        Request radio stations for Mother Earth.
        Use the URI "mer" as defined in your navigation JSON.
        """
        self.logger.info("MotherEarthManager: Fetching Mother Earth stations.")
        if self.volumio_listener.is_connected():
            self.last_requested_uri = "mer"
            self.logger.debug("MotherEarthManager: Volumio is connected. Emitting fetch_browse_library with URI 'mer'.")
            self.volumio_listener.fetch_browse_library("mer")
            self.logger.info("MotherEarthManager: Emitted browseLibrary for 'mer'.")
        else:
            self.logger.error("MotherEarthManager: Not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def handle_navigation(self, sender, navigation, **kwargs):
        """
        Handle navigation data received from Volumio.
        Since Mother Earth returns a single list, process the stations directly.
        """
        self.logger.debug(f"MotherEarthManager: Received navigation data: {navigation}")
        try:
            if not navigation or not isinstance(navigation, dict):
                self.logger.error("MotherEarthManager: Invalid navigation data received.")
                return

            if self.last_requested_uri == "mer":
                self.logger.debug("MotherEarthManager: last_requested_uri matches 'mer'. Updating stations.")
                self.update_stations(navigation)
                self.last_requested_uri = None
            else:
                self.logger.warning(f"MotherEarthManager: Ignoring navigation for URI {self.last_requested_uri}")
        except Exception as e:
            self.logger.exception(f"MotherEarthManager: Exception in handle_navigation - {e}")

    def update_stations(self, navigation):
        """Parse navigation data and update the list of stations."""
        try:
            self.logger.info("MotherEarthManager: Updating stations.")
            lists = navigation.get("lists", [])
            self.logger.debug(f"MotherEarthManager: Found {len(lists)} list(s) in navigation.")
            if not lists or not isinstance(lists, list):
                self.logger.warning("MotherEarthManager: No valid lists for stations.")
                self.display_no_stations_message()
                return

            items = []
            for lst in lists:
                lst_items = lst.get("items", [])
                self.logger.debug(f"MotherEarthManager: Found {len(lst_items)} items in a list.")
                if lst_items:
                    items.extend(lst_items)

            self.logger.debug(f"MotherEarthManager: Total items found: {len(items)}")
            if not items:
                self.logger.info("MotherEarthManager: No stations found.")
                self.display_no_stations_message()
                return

            self.stations = [
                {
                    "title": item.get("title", item.get("name", "Untitled")),
                    "uri": item.get("uri", item.get("link", "")),
                    "albumart": item.get("albumart", "")
                }
                for item in items
            ]
            self.logger.info(f"MotherEarthManager: Updated stations with {len(self.stations)} items.")
            self.current_selection_index = 0
            self.window_start_index = 0
            self.current_menu_items = self.stations.copy()
            self.logger.debug("MotherEarthManager: Displaying menu with updated stations.")
            self.display_menu()
            if self.timeout_timer:
                self.timeout_timer.cancel()
        except Exception as e:
            self.logger.exception(f"MotherEarthManager: Exception in update_stations - {e}")
            self.display_error_message("Error", "Failed to update stations.")

    def get_visible_window(self, items):
        """Return a subset of items to display based on the current selection."""
        total_items = len(items)
        half_window = self.window_size // 2
        tentative_start = self.current_selection_index - half_window
        self.logger.debug(f"MotherEarthManager: Calculating visible window: tentative_start={tentative_start}, total_items={total_items}")
        if tentative_start < 0:
            self.window_start_index = 0
        elif tentative_start + self.window_size > total_items:
            self.window_start_index = max(total_items - self.window_size, 0)
        else:
            self.window_start_index = tentative_start
        self.logger.debug(f"MotherEarthManager: Visible window starts at index {self.window_start_index}")
        return items[self.window_start_index:self.window_start_index + self.window_size]

    def display_menu(self):
        """Display the current station menu on the OLED."""
        self.logger.info("MotherEarthManager: Displaying station menu.")
        self.window_start_index = render_list_menu(
            display_manager=self.display_manager,
            title=self.mode_name.capitalize() if hasattr(self, "mode_name") else "MotherEarth",
            items=self.current_menu_items,
            current_selection_index=self.current_selection_index,
            window_start_index=self.window_start_index,
            window_size=self.window_size,
            y_offset=self.y_offset,
            line_spacing=self.line_spacing,
            font_key=self.font_key,
        )

    def display_no_stations_message(self):
        """Display a message when no stations are available."""
        self.logger.info("MotherEarthManager: Displaying 'No Stations Available'.")
        def draw_callback(draw_obj):
            text = "No Stations Available."
            w, h = draw_obj.textsize(text, font=self.font)
            x = (self.display_manager.oled.width - w) // 2
            y = (self.display_manager.oled.height - h) // 2
            draw_obj.text((x, y), text, font=self.font, fill="white")
        self.display_manager.draw_custom(draw_callback)

    def display_error_message(self, title, message):
        """Display an error message on the OLED."""
        self.logger.error(f"MotherEarthManager: {title}: {message}")
        def draw_callback(draw_obj):
            text = f"{title}\n{message}"
            y = 10
            for line in text.split('\n'):
                draw_obj.text((10, y), line, font=self.font, fill="white")
                y += self.line_spacing
        self.display_manager.draw_custom(draw_callback)

    def scroll_selection(self, direction):
        """Scroll through the station list and update the visible window."""
        if not self.is_active:
            self.logger.debug("MotherEarthManager: scroll_selection called but mode is not active.")
            return
        previous_index = self.current_selection_index
        self.current_selection_index += direction
        total_items = len(self.current_menu_items)
        self.current_selection_index = max(0, min(self.current_selection_index, total_items - 1))
        self.logger.info(f"MotherEarthManager: Scrolled from {previous_index} to {self.current_selection_index}")
        self.logger.debug(f"MotherEarthManager: Total menu items: {total_items}")
        self.display_menu()

    def select_item(self):
        """
        Handle the selection of the highlighted station.
        When a station is selected, send a playback command and display a toast.
        """
        if not self.is_active:
            self.logger.debug("MotherEarthManager: select_item called but mode is not active.")
            return
        if not self.current_menu_items:
            self.logger.error("MotherEarthManager: No stations available to select.")
            return
        selected_item = self.current_menu_items[self.current_selection_index]
        station_title = selected_item.get("title", "Untitled").strip()
        uri = selected_item.get("uri", "")
        albumart_url = selected_item.get("albumart", "")
        self.logger.info(f"MotherEarthManager: Playing station: {station_title} with URI: {uri}")
        self.logger.debug(f"MotherEarthManager: Selected item details: {selected_item}")
        self.play_station(station_title, uri, albumart_url=albumart_url)
        # Display the toast overlay after station selection.
        self.show_station_selected_toast()

    def show_station_selected_toast(self):
        """Display a two-line toast overlay, centered horizontally and shifted downward."""
        self.logger.info("MotherEarthManager: Displaying toast overlay.")
        toast_message = "Station selected:\nDisplay will update after the next song"
        lines = toast_message.split('\n')
        # Calculate total height of the text block
        line_heights = [self.font.getsize(line)[1] for line in lines]
        total_height = sum(line_heights) + (len(lines) - 1) * 2  # 2 pixels spacing between lines
        # Center vertically then shift down by 20 pixels
        y_start = (self.display_manager.oled.height - total_height) // 2

        def draw_callback(draw_obj):
            current_y = y_start
            for line in lines:
                text_width, text_height = draw_obj.textsize(line, font=self.font)
                x = (self.display_manager.oled.width - text_width) // 2
                draw_obj.text((x, current_y), line, font=self.font, fill="white")
                current_y += text_height + 2
        self.display_manager.draw_custom(draw_callback)
        # After 3 seconds, refresh the station menu (thus clearing the toast overlay).
        import threading
        threading.Timer(3.0, self.display_menu).start()

    def play_station(self, title, uri, albumart_url=None):
        """Send a command to play the selected Mother Earth station."""
        try:
            self.logger.info(f"MotherEarthManager: Attempting to play station: {title}")
            payload = {
                'title': title,
                'service': 'motherearthradio',
                'uri': uri,
                'type': 'mywebradio',
                'albumart': albumart_url or '',
                'icon': 'fa fa-music'
            }
            self.logger.debug(f"MotherEarthManager: Payload prepared: {payload}")
            self.volumio_listener.socketIO.emit('replaceAndPlay', payload)
            self.logger.info("MotherEarthManager: Sent replaceAndPlay command.")
            self.logger.debug("MotherEarthManager: Playback command emitted successfully.")
        except Exception as e:
            self.logger.exception(f"MotherEarthManager: Failed to play station - {e}")
            self.display_error_message("Playback Error", f"Could not play station: {e}")
