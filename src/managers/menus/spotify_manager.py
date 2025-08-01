# src/managers/spotify_manager.py
from managers.base_manager import BaseManager
from utils.menu_renderer import render_list_menu
import logging
from PIL import ImageFont
import threading

class SpotifyManager(BaseManager):
    def __init__(self, display_manager, volumio_listener, mode_manager, window_size=4, y_offset=5, line_spacing=15):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.mode_name = "spotify"
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.info("SpotifyManager initialized.")

        # Initialize state variables
        self.menu_stack = []
        self.current_menu_items = []
        self.current_selection_index = 0
        self.window_start_index = 0
        self.is_active = False

        # Display settings
        self.window_size = window_size
        self.y_offset = y_offset
        self.line_spacing = line_spacing
        self.font_key = 'menu_font'

        # Timeout timer attribute
        self.timeout_timer = None

        # Register mode change callback
        if hasattr(self.mode_manager, "add_on_mode_change_callback"):
            self.mode_manager.add_on_mode_change_callback(self.handle_mode_change)

    def start_mode(self):
        if self.is_active:
            self.logger.debug("SpotifyManager: Spotify mode already active.")
            return

        self.logger.info("SpotifyManager: Starting Spotify mode.")
        self.is_active = True
        self.current_selection_index = 0
        self.window_start_index = 0

        # Connect signals
        self.volumio_listener.navigation_received.connect(self.handle_navigation)
        self.volumio_listener.toast_message_received.connect(self.handle_toast_message)
        self.volumio_listener.state_changed.connect(self.handle_state_change)
        self.volumio_listener.track_changed.connect(self.handle_track_change)

        self.logger.debug("SpotifyManager: Connected to Volumio signals.")

        self.display_loading_screen()
        self.fetch_spotify_navigation()  # Fetch Spotify root navigation

        # Start a timeout timer (e.g. 5 seconds)
        self.timeout_timer = threading.Timer(5.0, self.spotify_timeout)
        self.timeout_timer.start()

    def spotify_timeout(self):
        """Called when Spotify navigation has not produced any menu items within the timeout period."""
        if not self.current_menu_items:
            self.logger.warning("SpotifyManager: Timeout reached, no valid navigation data received.")
            def draw(draw_obj):
                draw_obj.text(
                    (10, self.y_offset),
                    "Spotify is not loading...",
                    font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                    fill="white"
                )
                draw_obj.text(
                    (10, self.y_offset + self.line_spacing),
                    "Have you logged in via Volumio?",
                    font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                    fill="white"
                )
            self.display_manager.draw_custom(draw)
            # Automatically navigate back to the menu after 5 seconds.
            threading.Timer(5.0, self.mode_manager.to_menu).start()

    def stop_mode(self):
        if not self.is_active:
            self.logger.debug("SpotifyManager: Spotify mode already inactive.")
            return
        self.is_active = False
        self.display_manager.clear_screen()
        self.logger.info("SpotifyManager: Stopped Spotify mode and cleared display.")

        # Disconnect signals
        self.volumio_listener.navigation_received.disconnect(self.handle_navigation)
        self.volumio_listener.toast_message_received.disconnect(self.handle_toast_message)
        self.volumio_listener.state_changed.disconnect(self.handle_state_change)
        self.volumio_listener.track_changed.disconnect(self.handle_track_change)
        self.logger.debug("SpotifyManager: Disconnected from Volumio signals.")

        # Cancel timeout timer if still running
        if self.timeout_timer:
            self.timeout_timer.cancel()
            self.timeout_timer = None

    def handle_navigation(self, sender, navigation, service, uri, **kwargs):
        if service not in ['spop', 'spotify']:  # Ensure service is 'spop' or 'spotify' for Spotify
            return  # Ignore navigation data not related to Spotify
        self.logger.info("SpotifyManager: Received navigation data.")
        self.update_spotify_menu(sender, navigation)

    def fetch_spotify_navigation(self, uri="spotify"):
        self.logger.info(f"SpotifyManager: Fetching navigation data for URI: {uri}")
        if self.volumio_listener.is_connected():
            try:
                self.volumio_listener.fetch_browse_library(uri)
                self.logger.debug(f"SpotifyManager: Emitted 'browseLibrary' for URI: {uri}")
            except Exception as e:
                self.logger.error(f"SpotifyManager: Failed to emit 'browseLibrary' for {uri}: {e}")
                self.display_error_message("Navigation Error", f"Could not fetch navigation: {e}")
        else:
            self.logger.warning("SpotifyManager: Cannot fetch navigation - not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def get_visible_window(self, items):
        """Returns a subset of items to display based on the current selection."""
        if self.current_selection_index < self.window_start_index:
            self.window_start_index = self.current_selection_index
        elif self.current_selection_index >= self.window_start_index + self.window_size:
            self.window_start_index = self.current_selection_index - self.window_size + 1

        self.window_start_index = max(0, self.window_start_index)
        self.window_start_index = min(self.window_start_index, max(0, len(items) - self.window_size))

        visible_items = items[self.window_start_index:self.window_start_index + self.window_size]
        self.logger.debug(f"SpotifyManager: Visible window indices {self.window_start_index} to {self.window_start_index + self.window_size -1}")
        return visible_items

    def handle_mode_change(self, current_mode):
        """Handle mode changes between Spotify and other modes."""
        self.logger.info(f"SpotifyManager handling mode change to: {current_mode}")
        if current_mode == "spotify":
            self.logger.info("SpotifyManager: Entering Spotify mode...")
            self.start_mode()
        elif self.is_active:
            self.logger.info("SpotifyManager: Exiting Spotify mode...")
            self.stop_mode()

    def handle_state_change(self, sender, state, **kwargs):
        if state.get('service') == 'spop':
            self.logger.info("SpotifyManager: State changed, updating display.")
            self.update_song_info(state)
    
    def handle_track_change(self, sender, track, **kwargs):
        """Handle track changes from Volumio."""
        if track.get('service') == 'spop':
            self.logger.info("SpotifyManager: Track changed, updating display.")
            self.update_song_info(track)

    def display_loading_screen(self):
        """Display a loading screen."""
        self.logger.info("SpotifyManager: Displaying loading screen.")

        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "Loading Spotify...",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def update_spotify_menu(self, sender, navigation, **kwargs):
        if not navigation:
            self.logger.warning("SpotifyManager: No navigation data received.")
            self.display_no_items()
            return

        lists = navigation.get("lists", [])

        if not lists or not isinstance(lists, list):
            self.logger.warning("SpotifyManager: Navigation data has no valid lists.")
            self.display_no_items()
            return

        # Combine items from all lists
        combined_items = []
        for lst in lists:
            list_items = lst.get("items", [])
            if list_items:
                combined_items.extend(list_items)

        self.logger.debug("SpotifyManager: Displaying combined menu items from all lists.")

        if not combined_items:
            self.logger.info("SpotifyManager: No items in navigation. Displaying 'No Results'.")
            self.display_no_items()
            return

        # Cancel the timeout timer if valid navigation data is received.
        if self.timeout_timer:
            self.timeout_timer.cancel()
            self.timeout_timer = None

        self.current_menu_items = [
            {
                "title": item.get("title", "Untitled"),
                "uri": item.get("uri", ""),
                "type": item.get("type", "")
            }
            for item in combined_items
        ]
        self.current_menu_items.append({"title": "Back", "uri": None, "type": "back"})

        self.logger.info(f"SpotifyManager: Updated menu with {len(self.current_menu_items)} items.")

        if self.is_active:
            self.display_menu()

    def display_no_items(self):
        """Display a message if no items are available."""
        self.logger.info("SpotifyManager: No items available.")

        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "No Spotify Items Available",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def display_menu(self):
        """Display the current menu."""
        self.logger.info("SpotifyManager: Displaying menu.")
        self.window_start_index = render_list_menu(
            display_manager=self.display_manager,
            title=self.mode_name.capitalize() if hasattr(self, "mode_name") else "Spotify",
            items=self.current_menu_items,
            current_selection_index=self.current_selection_index,
            window_start_index=self.window_start_index,
            window_size=self.window_size,
            y_offset=self.y_offset,
            line_spacing=self.line_spacing,
            font_key=self.font_key,
        )

    def scroll_selection(self, direction):
        """Scroll through the menu items."""
        if not self.is_active:
            self.logger.debug("SpotifyManager: Scroll attempted while not active.")
            return

        previous_index = self.current_selection_index
        self.current_selection_index += direction
        self.current_selection_index = max(0, min(self.current_selection_index, len(self.current_menu_items) - 1))
        self.logger.debug(f"SpotifyManager: Scrolled from {previous_index} to {self.current_selection_index}.")
        self.display_menu()

    def select_item(self):
        if not self.is_active or not self.current_menu_items:
            self.logger.warning("SpotifyManager: Select attempted while inactive or no items available.")
            return

        selected_item = self.current_menu_items[self.current_selection_index]
        self.logger.info(f"SpotifyManager: Selected item: {selected_item}")

        if selected_item.get("title") == "Back":
            self.back()
            return

        uri = selected_item.get("uri")
        if not uri:
            self.logger.warning("SpotifyManager: Selected item has no URI.")
            self.display_error_message("Invalid Selection", "Selected item has no URI.")
            return

        # Determine if the item is playable
        if selected_item.get("type", "").lower() in ["song", "playlist", "album"]:
            self.logger.info(f"SpotifyManager: Playing item with URI: {uri}")
            self.play_item(uri)
        else:
            self.logger.info(f"SpotifyManager: Navigating into category with URI: {uri}")
            self.navigate_to(uri)

    def play_item(self, uri):
        """Emit commands to Volumio to play the selected item."""
        self.logger.info(f"SpotifyManager: Sending replaceAndPlay command for URI: {uri}")
        if self.volumio_listener.is_connected():
            try:
                self.mode_manager.suppress_state_change()
                self.volumio_listener.socketIO.emit('replaceAndPlay', {
                    "service": "spop",
                    "uri": uri
                })
                threading.Timer(1.0, self.mode_manager.allow_state_change).start()
            except Exception as e:
                self.logger.error(f"SpotifyManager: Failed to play item {uri}: {e}")
                self.display_error_message("Playback Error", f"Could not play item: {e}")
        else:
            self.logger.warning("SpotifyManager: Cannot play item - not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def navigate_to(self, uri):
        """Navigate into a submenu or playlist."""
        # Push current menu context to stack for back functionality
        self.menu_stack.append({
            "menu_items": self.current_menu_items.copy(),
            "selection_index": self.current_selection_index,
            "window_start_index": self.window_start_index
        })
        self.logger.debug("SpotifyManager: Pushed current menu context to stack.")

        # Fetch navigation data for the new URI
        self.logger.info(f"SpotifyManager: Fetching navigation data for URI: {uri}")
        self.display_loading_screen()
        self.fetch_spotify_navigation(uri)

    def go_back(self):
        """Navigate back to the previous menu context."""
        if not self.menu_stack:
            self.logger.info("SpotifyManager: No previous menu to return to.")
            self.stop_mode()
            return

        # Restore previous menu context
        previous_context = self.menu_stack.pop()
        self.current_menu_items = previous_context["menu_items"]
        self.current_selection_index = previous_context["selection_index"]
        self.window_start_index = previous_context["window_start_index"]
        self.logger.debug("SpotifyManager: Restored previous menu context from stack.")
        self.display_menu()

    def back(self):
        if self.menu_stack:
            self.go_back()
        else:
            if self.is_active:
                self.stop_mode()
            self.mode_manager.back()

    def handle_toast_message(self, sender, message):
        """Handle toast messages from Volumio, especially errors."""
        message_type = message.get("type", "")
        title = message.get("title", "")
        body = message.get("message", "")

        if message_type == "error":
            self.logger.error(f"SpotifyManager: Error received - {title}: {body}")
            self.display_error_message(title, body)
        elif message_type == "success":
            self.logger.info(f"SpotifyManager: Success - {title}: {body}")
            # Optionally handle success messages (e.g., confirmations)
        else:
            self.logger.info(f"SpotifyManager: Received toast message - {title}: {body}")

    def display_error_message(self, title, message):
        """Display an error message on the screen."""
        self.logger.info(f"SpotifyManager: Displaying error message: {title} - {message}")

        def draw(draw_obj):
            # Display title
            draw_obj.text(
                (10, self.y_offset),
                f"Error: {title}",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="red"
            )
            # Display message
            draw_obj.text(
                (10, self.y_offset + self.line_spacing),
                message,
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def update_song_info(self, state):
        """Update the playback metrics display based on the current state."""
        self.logger.info("SpotifyManager: Updating playback metrics display.")

        # Extract relevant playback information
        sample_rate = state.get("samplerate", "Unknown Sample Rate")
        bitdepth = state.get("bitdepth", "Unknown Bit Depth")
        volume = state.get("volume", "Unknown Volume")

        # Log or display the extracted information
        self.logger.info(f"Sample Rate: {sample_rate}, Bit Depth: {bitdepth}, Volume: {volume}")
