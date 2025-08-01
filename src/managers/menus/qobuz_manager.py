# src/managers/qobuz_manager.py
from managers.base_manager import BaseManager
from utils.menu_renderer import render_list_menu
import logging
from PIL import ImageFont
import threading
import time

class QobuzManager(BaseManager):
    def __init__(self, display_manager, volumio_listener, mode_manager, window_size=4, y_offset=5, line_spacing=15):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.mode_name = "qobuz"
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.info("QobuzManager initialized.")

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
            self.logger.debug("QobuzManager: Qobuz mode already active.")
            return

        self.logger.info("QobuzManager: Starting Qobuz mode.")
        self.is_active = True
        self.current_selection_index = 0
        self.window_start_index = 0

        # Connect signals
        self.volumio_listener.navigation_received.connect(self.handle_navigation)
        self.volumio_listener.toast_message_received.connect(self.handle_toast_message)
        self.logger.debug("QobuzManager: Connected to 'navigation_received' and 'toast_message_received' signals.")

        self.volumio_listener.state_changed.connect(self.handle_state_change)
        self.volumio_listener.track_changed.connect(self.handle_track_change)

        self.display_loading_screen()
        self.fetch_qobuz_navigation()  # Fetch Qobuz root navigation

        # Start a timeout timer (e.g. 5 seconds)
        self.timeout_timer = threading.Timer(5.0, self.qobuz_timeout)
        self.timeout_timer.start()

    def qobuz_timeout(self):
        """Called when Qobuz navigation has not produced any menu items within the timeout period."""
        if not self.current_menu_items:
            self.logger.warning("QobuzManager: Timeout reached, no valid navigation data received.")
            def draw(draw_obj):
                draw_obj.text(
                    (10, self.y_offset),
                    "Qobuz is not loading...",
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
            self.logger.debug("QobuzManager: Qobuz mode already inactive.")
            return
        self.is_active = False
        self.display_manager.clear_screen()
        self.logger.info("QobuzManager: Stopped Qobuz mode and cleared display.")

        # Disconnect signals
        self.volumio_listener.navigation_received.disconnect(self.handle_navigation)
        self.volumio_listener.toast_message_received.disconnect(self.handle_toast_message)
        self.logger.debug("QobuzManager: Disconnected from 'navigation_received' and 'toast_message_received' signals.")

        self.volumio_listener.state_changed.disconnect(self.handle_state_change)
        self.volumio_listener.track_changed.disconnect(self.handle_track_change)

        # Cancel the timeout timer if it's still running
        if self.timeout_timer:
            self.timeout_timer.cancel()
            self.timeout_timer = None

    def handle_navigation(self, sender, navigation, service, uri, **kwargs):
        if service != 'qobuz':
            return  # Ignore navigation data not related to Qobuz
        self.logger.info("QobuzManager: Received navigation data.")
        self.update_qobuz_menu(sender, navigation)

    def fetch_qobuz_navigation(self, uri="qobuz://"):
        self.logger.info(f"QobuzManager: Fetching navigation data for URI: {uri}")
        if self.volumio_listener.is_connected():
            try:
                self.volumio_listener.fetch_browse_library(uri)
                self.logger.debug(f"QobuzManager: Emitted 'browseLibrary' for URI: {uri}")
            except Exception as e:
                self.logger.error(f"QobuzManager: Failed to emit 'browseLibrary' for {uri}: {e}")
                self.display_error_message("Navigation Error", f"Could not fetch navigation: {e}")
        else:
            self.logger.warning("QobuzManager: Cannot fetch navigation - not connected to Volumio.")
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
        self.logger.debug(f"QobuzManager: Visible window indices {self.window_start_index} to {self.window_start_index + self.window_size - 1}")
        return visible_items

    def handle_mode_change(self, current_mode):
        """Handle mode changes between Qobuz and other modes."""
        self.logger.info(f"QobuzManager handling mode change to: {current_mode}")
        if current_mode == "qobuz":
            self.logger.info("QobuzManager: Entering Qobuz mode...")
            self.start_mode()
        elif self.is_active:
            self.logger.info("QobuzManager: Exiting Qobuz mode...")
            self.stop_mode()

    def handle_state_change(self, sender, state, **kwargs):
        if state.get('service') == 'qobuz':
            self.logger.info("QobuzManager: State changed, updating display.")
            self.update_song_info(state)
    
    def handle_track_change(self, sender, track, **kwargs):
        """Handle track changes from Volumio."""
        if track.get('service') == 'qobuz':
            self.logger.info("QobuzManager: Track changed, updating display.")
            self.update_song_info(track)

    def display_loading_screen(self):
        """Display a loading screen."""
        self.logger.info("QobuzManager: Displaying loading screen.")

        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "Loading Qobuz...",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def update_qobuz_menu(self, sender, navigation, **kwargs):
        # Check if the navigation data is valid (contains non-empty lists)
        if navigation and isinstance(navigation, dict) and navigation.get("lists"):
            lists = navigation.get("lists", [])
            combined_items = []
            for lst in lists:
                list_items = lst.get("items", [])
                if list_items:
                    combined_items.extend(list_items)

            if combined_items:
                # We received valid data; cancel the timeout timer if it's still running.
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
                self.logger.info(f"QobuzManager: Updated menu with {len(self.current_menu_items)} items.")
                if self.is_active:
                    self.display_menu()
                return
            else:
                self.logger.warning("QobuzManager: Navigation data received but no items found.")
        else:
            self.logger.warning("QobuzManager: No navigation data received.")

        # If we reach here, either navigation was empty or no valid items were found.
        # Do not cancel the timer so that qobuz_timeout will eventually be called.
        self.display_no_items()

    def display_no_items(self):
        """Display a message if no items are available."""
        self.logger.info("QobuzManager: No items available.")

        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "No Qobuz Items Available",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def display_menu(self):
        """Display the current menu."""
        self.logger.info("QobuzManager: Displaying menu.")
        self.window_start_index = render_list_menu(
            display_manager=self.display_manager,
            title=self.mode_name.capitalize(),
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
            self.logger.debug("QobuzManager: Scroll attempted while not active.")
            return

        previous_index = self.current_selection_index
        self.current_selection_index += direction
        self.current_selection_index = max(0, min(self.current_selection_index, len(self.current_menu_items) - 1))
        self.logger.debug(f"QobuzManager: Scrolled from {previous_index} to {self.current_selection_index}.")
        self.display_menu()

    def select_item(self):
        if not self.is_active or not self.current_menu_items:
            self.logger.warning("QobuzManager: Select attempted while inactive or no items available.")
            return

        selected_item = self.current_menu_items[self.current_selection_index]
        self.logger.info(f"QobuzManager: Selected item: {selected_item}")

        if selected_item.get("title") == "Back":
            self.back()
            return

        uri = selected_item.get("uri")
        if not uri:
            self.logger.warning("QobuzManager: Selected item has no URI.")
            self.display_error_message("Invalid Selection", "Selected item has no URI.")
            return

        # Determine if the item is a song by checking the URI prefix
        if uri.startswith("qobuz://song/") or selected_item.get("type", "").lower() == "song":
            self.logger.info(f"QobuzManager: Playing song with URI: {uri}")
            self.play_song(uri)
            return

        # If not a song, treat it as a category or folder and navigate into it
        self.logger.info(f"QobuzManager: Navigating into category with URI: {uri}")
        self.navigate_to(uri)

    def play_song(self, uri):
        """Emit commands to Volumio to play the selected song directly."""
        self.logger.info(f"QobuzManager: Sending replaceAndPlay command for URI: {uri}")
        if self.volumio_listener.is_connected():
            try:
                # Suppress state changes
                self.mode_manager.suppress_state_change()

                # Use replaceAndPlay to directly play the song
                selected_item = self.current_menu_items[self.current_selection_index]
                song_title = selected_item.get("title", "Untitled")
                self.volumio_listener.socketIO.emit('replaceAndPlay', {
                    "service": "qobuz",
                    "uri": uri,
                    "title": song_title
                })
                self.logger.info(f"QobuzManager: Sent replaceAndPlay command for '{song_title}' to Volumio.")

                # Allow state changes after a short delay
                threading.Timer(1.0, self.mode_manager.allow_state_change).start()
            except Exception as e:
                self.logger.error(f"QobuzManager: Failed to play track {uri}: {e}")
                self.display_error_message("Playback Error", f"Could not play track: {e}")
        else:
            self.logger.warning("QobuzManager: Cannot play song - not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def navigate_to(self, uri):
        """Navigate into a submenu or playlist."""
        # Push current menu context to stack for back functionality
        self.menu_stack.append({
            "menu_items": self.current_menu_items.copy(),
            "selection_index": self.current_selection_index,
            "window_start_index": self.window_start_index
        })
        self.logger.debug("QobuzManager: Pushed current menu context to stack.")

        # Fetch navigation data for the new URI
        self.logger.info(f"QobuzManager: Fetching navigation data for URI: {uri}")
        self.display_loading_screen()
        self.fetch_qobuz_navigation(uri)

    def go_back(self):
        """Navigate back to the previous menu context."""
        if not self.menu_stack:
            self.logger.info("QobuzManager: No previous menu to return to.")
            self.stop_mode()
            return

        # Restore previous menu context
        previous_context = self.menu_stack.pop()
        self.current_menu_items = previous_context["menu_items"]
        self.current_selection_index = previous_context["selection_index"]
        self.window_start_index = previous_context["window_start_index"]
        self.logger.debug("QobuzManager: Restored previous menu context from stack.")
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
            self.logger.error(f"QobuzManager: Error received - {title}: {body}")
            self.display_error_message(title, body)
        elif message_type == "success":
            self.logger.info(f"QobuzManager: Success - {title}: {body}")
            # Optionally handle success messages (e.g., confirmations)
        else:
            self.logger.info(f"QobuzManager: Received toast message - {title}: {body}")

    def display_error_message(self, title, message):
        """Display an error message on the screen."""
        self.logger.info(f"QobuzManager: Displaying error message: {title} - {message}")

        def draw(draw_obj):
            # Draw error title in white (matching the loading screen style)
            draw_obj.text(
                (10, self.y_offset),
                f"Error: {title}",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )
            # Draw error message in white
            draw_obj.text(
                (10, self.y_offset + self.line_spacing),
                message,
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def update_song_info(self, state):
        """Update the playback metrics display based on the current state."""
        self.logger.info("QobuzManager: Updating playback metrics display.")

        # Extract relevant playback information
        sample_rate = state.get("samplerate", "Unknown Sample Rate")
        bitdepth = state.get("bitdepth", "Unknown Bit Depth")
        volume = state.get("volume", "Unknown Volume")

        self.logger.info(f"Sample Rate: {sample_rate}, Bit Depth: {bitdepth}, Volume: {volume}")
        # Optionally update the display with this information
