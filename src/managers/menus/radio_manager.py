# src/managers/radio_manager.py

from managers.base_manager import BaseManager
from utils.menu_renderer import render_list_menu
import logging
from PIL import ImageFont
import threading
import time


class RadioManager(BaseManager):
    def __init__(self, display_manager, volumio_listener, mode_manager, window_size=4, y_offset=2, line_spacing=15):
        super().__init__(display_manager, volumio_listener, mode_manager)

        self.mode_name = "webradio"

        self.display_manager = display_manager
        self.volumio_listener = volumio_listener
        self.mode_manager = mode_manager

        # Initialize logger
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)  # Set to DEBUG for detailed logs

        # Radio categories list
        self.categories = []
        self.category_items = []  # Initialize category_items
        self.stations = []
        self.current_selection_index = 0
        self.current_menu = "categories"  # Start in the categories menu
        self.font_key = 'menu_font'
        self.font = self.display_manager.fonts.get(self.font_key, ImageFont.load_default())
        self.menu_stack = []  # Stack for back navigation
        self.is_active = False
        self.window_start_index = 0  # Initialize window_start_index

        # Window settings
        self.window_size = window_size
        self.y_offset = y_offset
        self.line_spacing = line_spacing

        # Tracking the last requested URI
        self.last_requested_uri = None

        # Debounce handling
        self.last_action_time = 0
        self.debounce_interval = 0.3  # in seconds

        # Signals connected flag
        self._signals_connected = False

    def connect_signals(self):
        """Connect signals if not already connected."""
        if not self._signals_connected:
            try:
                self.volumio_listener.navigation_received.connect(self.handle_navigation)
                self.volumio_listener.toast_message_received.connect(self.handle_toast_message)
                self._signals_connected = True
                self.logger.debug("RadioManager: Connected to signals.")
            except Exception as e:
                self.logger.error(f"RadioManager: Failed to connect signals - {e}")

    def disconnect_signals(self):
        """Disconnect signals if connected."""
        if self._signals_connected:
            try:
                self.volumio_listener.navigation_received.disconnect(self.handle_navigation)
                self.volumio_listener.toast_message_received.disconnect(self.handle_toast_message)
                self._signals_connected = False
                self.logger.debug("RadioManager: Disconnected from signals.")
            except Exception as e:
                self.logger.error(f"RadioManager: Failed to disconnect signals - {e}")

    def start_mode(self):
        """Activate Radio mode."""
        if self.is_active:
            self.logger.debug("RadioManager: Radio mode already active.")
            return

        self.logger.info("RadioManager: Starting Radio mode.")
        self.is_active = True
        self.current_selection_index = 0
        self.window_start_index = 0  # Reset window_start_index when starting mode
        self.current_menu = "categories"
        self.menu_stack.clear()
        self.stations.clear()

        # Connect signals
        self.connect_signals()

        # Fetch categories dynamically
        self.fetch_radio_categories()

    def stop_mode(self):
        """Deactivate Radio mode."""
        self.logger.info("RadioManager: Stopping Radio mode.")
        if not self.is_active:
            self.logger.warning("RadioManager: Mode is already inactive.")
            return
        self.is_active = False
        self.display_manager.clear_screen()

        # Disconnect signals
        self.disconnect_signals()

    def display_categories(self):
        """Display radio categories."""
        self.logger.info("RadioManager: Displaying categories.")

        if not self.categories:
            self.display_no_categories_message()
            return

        def draw(draw_obj):
            visible_categories = self.get_visible_window(self.categories)
            y_offset = self.y_offset
            x_offset_arrow = 5

            for i, category in enumerate(visible_categories):
                actual_index = self.window_start_index + i
                arrow = "-> " if actual_index == self.current_selection_index else "   "
                fill_color = "white" if actual_index == self.current_selection_index else "gray"
                draw_obj.text(
                    (x_offset_arrow, y_offset + i * self.line_spacing),
                    f"{arrow}{category}",
                    font=self.font,
                    fill=fill_color
                )

        self.display_manager.draw_custom(draw)
        self.logger.debug("RadioManager: Categories displayed within the visible window.")

    def display_radio_stations(self):
        """Display the current list of radio stations."""
        self.logger.info("RadioManager: Displaying radio stations.")

        if not self.stations:
            self.display_no_stations_message()
            return

        def draw(draw_obj):
            visible_stations = self.get_visible_window([station['title'] for station in self.stations])
            y_offset = self.y_offset
            x_offset_arrow = 5

            for i, station_title in enumerate(visible_stations):
                actual_index = self.window_start_index + i
                arrow = "-> " if actual_index == self.current_selection_index else "   "
                fill_color = "white" if actual_index == self.current_selection_index else "gray"
                draw_obj.text(
                    (x_offset_arrow, y_offset + i * self.line_spacing),
                    f"{arrow}{station_title}",
                    font=self.font,
                    fill=fill_color
                )

        self.display_manager.draw_custom(draw)
        self.logger.debug("RadioManager: Stations displayed within the visible window.")

    def handle_navigation(self, sender, navigation, **kwargs):
        try:
            self.logger.debug(f"RadioManager: handle_navigation called with navigation={navigation}")

            if not navigation or not isinstance(navigation, dict):
                self.logger.error("RadioManager: Received invalid navigation data.")
                return

            # Check if we're fetching categories
            if self.last_requested_uri == "radio":
                self.update_radio_categories(navigation)
                self.last_requested_uri = None
            # Check if we're fetching stations
            elif self.last_requested_uri and self.current_menu == "stations":
                self.logger.info("RadioManager: Processing navigation data for Web Radio.")
                self.update_radio_stations(navigation)
                self.last_requested_uri = None
            else:
                self.logger.warning(f"RadioManager: Ignoring navigation for last_requested_uri: {self.last_requested_uri}")
        except Exception as e:
            self.logger.exception(f"RadioManager: Exception in handle_navigation - {e}")

    def update_radio_categories(self, navigation):
        """Update the list of categories when data is received."""
        try:
            self.logger.info("RadioManager: Updating radio categories.")
            lists = navigation.get("lists", [])  # Corrected access
            if not lists or not isinstance(lists, list):
                self.logger.warning("RadioManager: No valid lists received for categories.")
                self.display_no_categories_message()
                return

            items = []
            for lst in lists:
                lst_items = lst.get("items", [])
                if lst_items:
                    items.extend(lst_items)

            if not items:
                self.logger.info("RadioManager: No categories in navigation. Displaying 'No Categories Available'.")
                self.display_no_categories_message()
                return

            self.category_items = items  # Assign items to self.category_items

            self.categories = [
                item.get("title", item.get("name", "Untitled"))
                for item in items
            ]
            self.categories.append("Back")
            self.logger.info(f"RadioManager: Updated categories list with {len(self.categories)} items.")
            self.current_selection_index = 0
            self.window_start_index = 0
            self.display_categories()
        except Exception as e:
            self.logger.exception(f"RadioManager: Exception in update_radio_categories - {e}")
            self.display_error_message("Error", "Failed to update categories.")

    def update_radio_stations(self, navigation):
        """Update the list of stations when data is received."""
        try:
            self.logger.info("RadioManager: Updating radio stations.")
            lists = navigation.get("lists", [])  # Corrected access
            if not lists or not isinstance(lists, list):
                self.logger.warning("RadioManager: No valid lists received for stations.")
                self.display_no_stations_message()
                return

            items = []
            for lst in lists:
                lst_items = lst.get("items", [])
                if lst_items:
                    items.extend(lst_items)

            if not items:
                self.logger.info("RadioManager: No stations in navigation. Displaying 'No Stations Available'.")
                self.display_no_stations_message()
                return

            self.stations = [
                {
                    "title": item.get("title", item.get("name", "Untitled")),
                    "uri": item.get("uri", item.get("link", "")),
                    "albumart": item.get("albumart", ""),  # Include albumart
                }
                for item in items
            ]
            self.stations.append({"title": "Back", "uri": None})
            self.logger.info(f"RadioManager: Updated stations list with {len(self.stations)} items.")
            self.current_selection_index = 0
            self.window_start_index = 0
            self.display_radio_stations()
        except Exception as e:
            self.logger.exception(f"RadioManager: Exception in update_radio_stations - {e}")
            self.display_error_message("Error", "Failed to update stations.")

    def display_no_categories_message(self):
        """Display a message when no categories are available."""
        self.logger.info("RadioManager: Displaying 'No Categories Available' message.")

        def draw(draw_obj):
            text = "No Categories Available."
            font = self.font
            # Calculate text size
            width, height = draw_obj.textsize(text, font=font)
            # Get image size from draw_obj
            image_width, image_height = draw_obj.im.size
            # Center the text
            x = (image_width - width) // 2
            y = (image_height - height) // 2
            draw_obj.text((x, y), text, font=font, fill="white")

        self.display_manager.draw_custom(draw)
        self.logger.debug("RadioManager: 'No Categories Available' message displayed.")

    def display_no_stations_message(self):
        """Display a message when no stations are available."""
        self.logger.info("RadioManager: Displaying 'No Stations Available' message.")

        def draw(draw_obj):
            text = "No Stations Available."
            font = self.font
            # Calculate text size
            width, height = draw_obj.textsize(text, font=font)
            # Get image size from draw_obj
            image_width, image_height = draw_obj.im.size
            # Center the text
            x = (image_width - width) // 2
            y = (image_height - height) // 2
            draw_obj.text((x, y), text, font=font, fill="white")

        self.display_manager.draw_custom(draw)
        self.logger.debug("RadioManager: 'No Stations Available' message displayed.")

    def scroll_selection(self, direction):
        """Scroll through the current menu, keeping selection centered."""
        if not self.is_active:
            self.logger.warning("RadioManager: Scroll attempted while inactive.")
            return

        current_time = time.time()
        if current_time - self.last_action_time < self.debounce_interval:
            self.logger.debug("RadioManager: Scroll action ignored due to debounce.")
            return
        self.last_action_time = current_time

        if self.current_menu == "categories":
            options = self.categories
        elif self.current_menu == "stations":
            options = [station['title'] for station in self.stations]
        else:
            self.logger.warning("RadioManager: Unknown menu state.")
            return

        if not options:
            self.logger.warning("RadioManager: No options available to scroll.")
            return

        previous_index = self.current_selection_index

        # Ensure direction is an integer and handle scroll up/down correctly
        if isinstance(direction, int) and direction > 0:  # Scroll down
            if self.current_selection_index < len(options) - 1:
                self.current_selection_index += 1
        elif isinstance(direction, int) and direction < 0:  # Scroll up
            if self.current_selection_index > 0:
                self.current_selection_index -= 1
        else:
            self.logger.warning("RadioManager: Invalid scroll direction provided.")
            return

        # Update the window based on the new selection
        if previous_index != self.current_selection_index:
            self.logger.debug(f"RadioManager: Scrolled to index: {self.current_selection_index}")
            if self.current_menu == "categories":
                self.display_categories()
            elif self.current_menu == "stations":
                self.display_radio_stations()
        else:
            self.logger.debug("RadioManager: Reached the end/start of the list. Scroll input ignored.")

    def select_item(self):
        """Handle the selection of the currently highlighted item."""
        if not self.is_active:
            self.logger.warning("RadioManager: Select attempted while inactive.")
            return

        current_time = time.time()
        if current_time - self.last_action_time < self.debounce_interval:
            self.logger.debug("RadioManager: Select action ignored due to debounce.")
            return
        self.last_action_time = current_time

        if self.current_menu == "categories":
            selected_category = self.categories[self.current_selection_index]
            self.logger.info(f"RadioManager: Selected radio category: {selected_category}")

            if selected_category == "Back":
                self.navigate_back()
                return

            # Fetch the URI for the selected category
            selected_item = self.get_category_item_by_title(selected_category)
            uri = selected_item.get("uri") if selected_item else None

            if uri:
                self.logger.info(f"RadioManager: Fetching radio stations for category '{selected_category}' with URI '{uri}'")
                self.fetch_radio_stations(uri)
                # Push current menu to stack for back navigation
                self.menu_stack.append("categories")
                self.current_menu = "stations"
                self.current_selection_index = 0
                self.window_start_index = 0
            else:
                self.logger.error(f"RadioManager: No URI found for category '{selected_category}'")
                self.display_error_message("Error", f"No URI found for category '{selected_category}'")
        elif self.current_menu == "stations":
            if not self.stations:
                self.logger.error("RadioManager: No stations available to select.")
                return

            selected_station = self.stations[self.current_selection_index]
            station_title = selected_station['title'].strip()

            if station_title == "Back":
                self.navigate_back()
                return
            uri = selected_station['uri']
            albumart_url = selected_station.get('albumart', '')

            self.logger.info(f"RadioManager: Attempting to play station: {station_title} with URI: {uri}")

            # Play the station, passing the albumart_url
            self.play_station(station_title, uri, albumart_url=albumart_url)
        else:
            self.logger.warning("RadioManager: Unknown menu state.")

    def navigate_back(self):
        """Navigate back to the previous menu."""
        if not self.is_active:
            self.logger.warning("RadioManager: Back navigation attempted while inactive.")
            return

        current_time = time.time()
        if current_time - self.last_action_time < self.debounce_interval:
            self.logger.debug("RadioManager: Back action ignored due to debounce.")
            return
        self.last_action_time = current_time

        if not self.menu_stack:
            self.logger.info("RadioManager: No previous menu to navigate back to. Exiting Radio mode.")
            self.stop_mode()
            return

        self.current_menu = self.menu_stack.pop()
        self.current_selection_index = 0
        self.window_start_index = 0
        if self.current_menu == "categories":
            self.display_categories()
        elif self.current_menu == "stations":
            self.display_radio_stations()

    def back(self):
        if self.menu_stack:
            self.navigate_back()
        else:
            if self.is_active:
                self.stop_mode()
            self.mode_manager.back()

    def get_visible_window(self, items):
        """Returns a subset of items to display based on the current selection, keeping it centered."""
        total_items = len(items)
        half_window = self.window_size // 2

        # Calculate tentative window_start_index to center the selection
        tentative_start = self.current_selection_index - half_window

        # Adjust window_start_index to stay within bounds
        if tentative_start < 0:
            self.window_start_index = 0
        elif tentative_start + self.window_size > total_items:
            self.window_start_index = max(total_items - self.window_size, 0)
        else:
            self.window_start_index = tentative_start

        # Fetch the visible items based on the updated window_start_index
        visible_items = items[self.window_start_index:self.window_start_index + self.window_size]

        self.logger.debug(
            f"RadioManager: Visible window indices {self.window_start_index} to "
            f"{self.window_start_index + self.window_size -1}"
        )
        return visible_items

    def fetch_radio_categories(self):
        """Fetch the radio categories from Volumio."""
        self.logger.info("RadioManager: Fetching radio categories.")
        if self.volumio_listener.is_connected():
            try:
                self.last_requested_uri = "radio"
                self.volumio_listener.fetch_browse_library("radio")
                self.logger.info("RadioManager: Emitted 'browseLibrary' for 'radio' URI.")
            except Exception as e:
                self.logger.error(f"RadioManager: Failed to fetch radio categories - {e}")
                self.display_error_message("Navigation Error", f"Could not fetch radio categories: {e}")
        else:
            self.logger.warning("RadioManager: Cannot fetch radio categories - not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def fetch_radio_stations(self, uri):
        """Fetch the radio stations from Volumio based on the given URI."""
        self.logger.info(f"RadioManager: Fetching radio stations for URI: {uri}")
        if self.volumio_listener.is_connected():
            try:
                self.last_requested_uri = uri  # Track the last requested URI
                self.volumio_listener.fetch_browse_library(uri)
                self.logger.info(f"RadioManager: Emitted 'browseLibrary' for URI: {uri}")
            except Exception as e:
                self.logger.error(f"RadioManager: Failed to emit 'browseLibrary' for {uri}: {e}")
                self.display_error_message("Navigation Error", f"Could not fetch radio stations: {e}")
        else:
            self.logger.warning("RadioManager: Cannot fetch radio stations - not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def get_category_item_by_title(self, title):
        """Retrieve the category item by its title."""
        for item in self.category_items:
            if item.get("title", "") == title:
                return item
        return None

    def play_station(self, title, uri, albumart_url=None):
        """Play the selected radio station."""
        try:
            self.logger.info(f"RadioManager: Attempting to play Web Radio: {title}")
            self.logger.debug(f"RadioManager: Stream URI: {uri}")

            if self.volumio_listener.is_connected():
                try:
                    # Suppress state changes temporarily
                    self.mode_manager.suppress_state_change()
                    self.logger.debug("RadioManager: Suppressed state changes.")

                    # Include albumart URL if available
                    payload = {
                        'title': title,
                        'service': 'webradio',
                        'uri': uri,
                        'type': 'webradio',
                        'albumart': albumart_url if albumart_url else '',
                        'icon': 'fa fa-music',  # Optional
                    }
                    self.logger.debug(f"RadioManager: Payload to send: {payload}")

                    # Send the replaceAndPlay command
                    self.volumio_listener.socketIO.emit('replaceAndPlay', payload)
                    self.logger.info(f"RadioManager: Sent replaceAndPlay command with URI: {uri}")

                    # Allow state changes after a short delay
                    threading.Timer(1.0, self.mode_manager.allow_state_change).start()
                    self.logger.debug("RadioManager: Allowed state changes after delay.")
                except Exception as e:
                    self.logger.error(f"RadioManager: Failed to emit replaceAndPlay - {e}")
                    self.display_error_message("Playback Error", f"Could not emit play command: {e}")
            else:
                self.logger.warning("RadioManager: Cannot play station - not connected to Volumio.")
                self.display_error_message("Connection Error", "Not connected to Volumio.")
        except Exception as e:
            self.logger.exception(f"RadioManager: Unexpected error in play_station - {e}")
            self.display_error_message("Unexpected Error", f"An unexpected error occurred: {e}")

    def display_error_message(self, title, message):
        """Display an error message on the screen."""
        self.logger.error(f"{title}: {message}")

        def draw(draw_obj):
            text = f"{title}\n{message}"
            font = self.font
            y_offset = 10
            for line in text.split('\n'):
                draw_obj.text((10, y_offset), line, font=font, fill="white")
                y_offset += self.line_spacing

        self.display_manager.draw_custom(draw)
        self.logger.debug(f"RadioManager: Displayed error message '{title}: {message}' on OLED.")

    def handle_toast_message(self, sender, message):
        """Handle toast messages from Volumio, especially errors."""
        try:
            message_type = message.get("type", "").lower()
            title = message.get("title", "Message")
            body = message.get("message", "")

            if message_type == "error":
                self.logger.error(f"RadioManager: Error received - {title}: {body}")
                if body.lower() == "no results" and self.current_menu == "stations":
                    self.logger.info("RadioManager: No results for stations. Displaying message.")
                    self.display_no_stations_message()
                else:
                    self.display_error_message("Error", body)
            elif message_type == "success":
                self.logger.info(f"RadioManager: Success - {title}: {body}")
                # Optionally handle success messages
            else:
                self.logger.info(f"RadioManager: Received toast message - {title}: {body}")
        except Exception as e:
            self.logger.exception(f"RadioManager: Exception in handle_toast_message - {e}")
            

    def update_song_info(self, state):
        """Update the playback metrics display based on the current state."""
        self.logger.info("PlaybackManager: Updating playback metrics display.")

        # Extract relevant playback information
        sample_rate = state.get("samplerate", "Unknown Sample Rate")
        bitdepth = state.get("bitdepth", "Unknown Bit Depth")
        volume = state.get("volume", "Unknown Volume")

        # Forward the information to the PlaybackManager to handle without drawing directly here
        self.mode_manager.playback_manager.update_playback_metrics(state)