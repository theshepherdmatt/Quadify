from managers.base_manager import BaseManager
import logging
from PIL import ImageFont
import threading

class PlaylistManager(BaseManager):
    def __init__(self, display_manager, volumio_listener, mode_manager, window_size=4, y_offset=5, line_spacing=15):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.mode_name = "playlists"
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.info("PlaylistManager initialized.")

        # Initialize state variables
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

    def handle_mode_change(self, current_mode):
        """Handle mode changes."""
        self.logger.info(f"PlaylistManager handling mode change to: {current_mode}")
        if current_mode == "playlists":
            self.logger.info("Entering Playlist mode.")
            self.start_mode()
        elif self.is_active:
            self.logger.info("Exiting Playlist mode.")
            self.stop_mode()

    def handle_track_change(self, sender, track, **kwargs):
        """Handle track changes from Volumio."""
        if track.get('service') == 'qobuz':
            self.logger.info("QobuzManager: Track changed, updating display.")
            self.update_song_info(track)

    def start_mode(self):
        if self.is_active:
            self.logger.debug("PlaylistManager: Playlist mode already active.")
            return

        self.logger.info("PlaylistManager: Starting Playlist mode.")
        self.is_active = True
        self.current_selection_index = 0
        self.window_start_index = 0

        # Connect signals
        self.volumio_listener.navigation_received.connect(self.handle_navigation)
        self.volumio_listener.toast_message_received.connect(self.handle_toast_message)
        self.logger.debug("PlaylistManager: Connected to 'navigation_received' and 'toast_message_received' signals.")

        self.volumio_listener.state_changed.connect(self.handle_state_change)
        self.volumio_listener.track_changed.connect(self.handle_track_change)

        self.display_loading_screen()
        self.fetch_navigation()  # Fetch root playlists navigation

        # Start a timeout timer (e.g. 5 seconds)
        self.timeout_timer = threading.Timer(5.0, self.playlist_timeout)
        self.timeout_timer.start()

    def stop_mode(self):
        if not self.is_active:
            self.logger.debug("PlaylistManager: Playlist mode already inactive.")
            return
        self.is_active = False
        self.display_manager.clear_screen()
        self.logger.info("PlaylistManager: Stopped Playlist mode and cleared display.")

        # Disconnect signals
        self.volumio_listener.navigation_received.disconnect(self.handle_navigation)
        self.volumio_listener.toast_message_received.disconnect(self.handle_toast_message)
        self.logger.debug("PlaylistManager: Disconnected from 'navigation_received' and 'toast_message_received' signals.")

        self.volumio_listener.state_changed.disconnect(self.handle_state_change)
        self.volumio_listener.track_changed.disconnect(self.handle_track_change)

        # Cancel the timeout timer if it's still running
        if self.timeout_timer:
            self.timeout_timer.cancel()
            self.timeout_timer = None

    def handle_state_change(self, sender, state, **kwargs):
        if state.get('service') == 'playlists':
            self.logger.info("PlaylistManager: State changed, updating display.")
            self.update_song_info(state)

    def fetch_navigation(self, uri="playlists"):
        self.logger.info(f"PlaylistManager: Fetching navigation data for URI: {uri}")
        if self.volumio_listener.is_connected():
            try:
                self.volumio_listener.fetch_browse_library(uri)
                self.logger.debug(f"PlaylistManager: Emitted 'browseLibrary' for URI: {uri}")
            except Exception as e:
                self.logger.error(f"PlaylistManager: Failed to emit 'browseLibrary' for {uri}: {e}")
                self.display_error_message("Navigation Error", f"Could not fetch navigation: {e}")
        else:
            self.logger.warning("PlaylistManager: Cannot fetch navigation - not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def handle_navigation(self, sender, navigation, service, uri, **kwargs):
        if service not in ['mpd', 'volumio', 'playlists']:  # Include 'playlists' as valid service
            return  # Ignore navigation data not related to playlists
        self.logger.info("PlaylistManager: Received navigation data.")
        self.update_playlist_menu(navigation)

    def update_playlist_menu(self, navigation):
        if not navigation:
            self.logger.warning("PlaylistManager: No navigation data received.")
            self.display_no_items()
            return

        lists = navigation.get("lists", [])
        if not lists or not isinstance(lists, list):
            self.logger.warning("PlaylistManager: Navigation data has no valid lists.")
            self.display_no_items()
            return

        # Combine items from all lists
        combined_items = []
        for lst in lists:
            list_items = lst.get("items", [])
            if list_items:
                combined_items.extend(list_items)

        if not combined_items:
            self.logger.info("PlaylistManager: No items in navigation. Displaying 'No Playlists Available'.")
            self.display_no_items()
            return

        # Cancel the timeout timer if valid items are received.
        if self.timeout_timer:
            self.timeout_timer.cancel()
            self.timeout_timer = None

        self.current_menu_items = [
            {
                "title": item.get("title", "Untitled"),
                "uri": item.get("uri", ""),
                "type": item.get("type", ""),
                "service": item.get("service", "")
            }
            for item in combined_items
        ]
        self.current_menu_items.append({"title": "Back", "uri": None, "type": "back"})

        self.logger.info(f"PlaylistManager: Updated menu with {len(self.current_menu_items)} items.")
        if self.is_active:
            self.display_menu()

    def playlist_timeout(self):
        """Called when no valid navigation data is received within the timeout period."""
        if not self.current_menu_items:
            self.logger.warning("PlaylistManager: Timeout reached, no valid navigation data received.")
            def draw(draw_obj):
                draw_obj.text(
                    (10, self.y_offset),
                    "Playlists are not loading...",
                    font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                    fill="white"
                )
                draw_obj.text(
                    (10, self.y_offset + self.line_spacing),
                    "Have you created your playlists on Volumio?",
                    font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                    fill="white"
                )
            self.display_manager.draw_custom(draw)
            # Automatically navigate back to the menu after 5 seconds.
            threading.Timer(3.0, self.mode_manager.to_menu).start()

    def display_loading_screen(self):
        """Show a loading screen."""
        self.logger.info("PlaylistManager: Displaying loading screen.")
        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "Loading Playlists...",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )
        self.display_manager.draw_custom(draw)

    def display_menu(self):
        """Display the current menu."""
        self.logger.info("PlaylistManager: Displaying current menu.")
        visible_items = self.get_visible_window(self.current_menu_items)
        def draw(draw_obj):
            for i, item in enumerate(visible_items):
                actual_index = self.window_start_index + i
                arrow = "-> " if actual_index == self.current_selection_index else "   "
                item_title = item.get("title", "Unknown")
                draw_obj.text(
                    (10, self.y_offset + i * self.line_spacing),
                    f"{arrow}{item_title}",
                    font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                    fill="white" if actual_index == self.current_selection_index else "gray"
                )
        self.display_manager.draw_custom(draw)

    def get_visible_window(self, items):
        """Return the visible window of items."""
        if self.current_selection_index < self.window_start_index:
            self.window_start_index = self.current_selection_index
        elif self.current_selection_index >= self.window_start_index + self.window_size:
            self.window_start_index = self.current_selection_index - self.window_size + 1
        self.window_start_index = max(0, self.window_start_index)
        self.window_start_index = min(self.window_start_index, max(0, len(items) - self.window_size))
        return items[self.window_start_index : self.window_start_index + self.window_size]

    def scroll_selection(self, direction):
        """Scroll the selection."""
        if not self.is_active or not self.current_menu_items:
            self.logger.warning("PlaylistManager: Scroll attempted with no active items.")
            return
        previous_index = self.current_selection_index
        self.current_selection_index += direction
        self.current_selection_index = max(0, min(self.current_selection_index, len(self.current_menu_items) - 1))
        self.logger.debug(f"PlaylistManager: Scrolled from {previous_index} to {self.current_selection_index}.")
        self.display_menu()

    def select_item(self):
        if not self.is_active or not self.current_menu_items:
            self.logger.warning("PlaylistManager: Select attempted while inactive or no items available.")
            return
        selected_item = self.current_menu_items[self.current_selection_index]
        self.logger.info(f"PlaylistManager: Selected item: {selected_item}")
        name = selected_item.get("title")
        if name == "Back":
            self.back()
            return
        if not name:
            self.logger.warning("PlaylistManager: Selected item has no name.")
            self.display_error_message("Invalid Selection", "Selected item has no name.")
            return
        if selected_item.get("type", "").lower() == "playlist":
            self.logger.info(f"PlaylistManager: Playing playlist with name: {name}")
            self.play_playlist(name)
        else:
            self.logger.warning(f"PlaylistManager: Selected item is not a playlist. Type: {selected_item.get('type')}")
            self.display_error_message("Invalid Selection", "Selected item is not a playlist.")

    def play_playlist(self, name):
        self.logger.info(f"PlaylistManager: Sending playPlaylist command for playlist name: {name}")
        if self.volumio_listener.is_connected():
            try:
                self.mode_manager.suppress_state_change()
                self.volumio_listener.socketIO.emit('playPlaylist', {'name': name})
                self.logger.info(f"PlaylistManager: Sent playPlaylist command for playlist name: {name}")
                threading.Timer(1.0, self.mode_manager.allow_state_change).start()
            except Exception as e:
                self.logger.error(f"PlaylistManager: Failed to play playlist '{name}': {e}")
                self.display_error_message("Playback Error", f"Could not play playlist: {e}")
        else:
            self.logger.warning("PlaylistManager: Cannot play playlist - not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def display_no_items(self):
        """Display a message if no items are available."""
        self.logger.info("PlaylistManager: No items available.")
        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "No Playlists Available",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )
        self.display_manager.draw_custom(draw)

    def handle_toast_message(self, sender, message):
        """Handle toast messages from Volumio, especially errors."""
        message_type = message.get("type", "")
        title = message.get("title", "")
        body = message.get("message", "")
        if message_type == "error":
            self.logger.error(f"PlaylistManager: Error received - {title}: {body}")
            self.display_error_message(title, body)
        elif message_type == "success":
            self.logger.info(f"PlaylistManager: Success - {title}: {body}")
        else:
            self.logger.info(f"PlaylistManager: Received toast message - {title}: {body}")

    def display_error_message(self, title, message):
        """Display an error message on the screen."""
        self.logger.info(f"PlaylistManager: Displaying error message: {title} - {message}")
        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                f"Error: {title}",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="red"
            )
            draw_obj.text(
                (10, self.y_offset + self.line_spacing),
                message,
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )
        self.display_manager.draw_custom(draw)

    def update_song_info(self, state):
        """Update the playback metrics display based on the current state."""
        self.logger.info("PlaylistManager: Updating playback metrics display.")
        sample_rate = state.get("samplerate", "Unknown Sample Rate")
        bitdepth = state.get("bitdepth", "Unknown Bit Depth")
        volume = state.get("volume", "Unknown Volume")
        self.logger.info(f"Sample Rate: {sample_rate}, Bit Depth: {bitdepth}, Volume: {volume}")

    def back(self):
        if self.is_active:
            self.stop_mode()
        self.mode_manager.back()
