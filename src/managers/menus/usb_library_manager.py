# usb_library_manager.py

from managers.base_manager import BaseManager
import logging
from PIL import ImageFont
import threading

class USBLibraryManager(BaseManager):
    def __init__(self, display_manager, volumio_listener, mode_manager, window_size=4, y_offset=5, line_spacing=15):
        super().__init__(display_manager, volumio_listener, mode_manager)
        self.mode_name = "usblibrary"
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.info("USBLibraryManager initialized.")

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

        # Register mode change callback
        if hasattr(self.mode_manager, "add_on_mode_change_callback"):
            self.mode_manager.add_on_mode_change_callback(self.handle_mode_change)

    def handle_mode_change(self, current_mode):
        """Handle mode changes."""
        self.logger.info(f"USBLibraryManager handling mode change to: {current_mode}")
        if current_mode == "usblibrary":
            self.logger.info("Entering USB Library mode.")
            self.start_mode()
        elif self.is_active:
            self.logger.info("Exiting USB Library mode.")
            self.stop_mode()

    def start_mode(self):
        if self.is_active:
            self.logger.debug("USBLibraryManager: USB Library mode already active.")
            return

        self.logger.info("USBLibraryManager: Starting USB Library mode.")
        self.is_active = True
        self.current_selection_index = 0
        self.window_start_index = 0

        # Fetch USB navigation
        self.display_loading_screen()
        self.fetch_navigation("music-library/USB")

        # Start timeout timer (e.g. 5 seconds)
        self.timeout_timer = threading.Timer(3.0, self.library_timeout)
        self.timeout_timer.start()

    def library_timeout(self):
        """Called when library navigation has not loaded within the timeout period."""
        if not self.current_menu_items:
            self.logger.warning("LibraryManager: Timeout reached, no navigation data received.")

            def draw(draw_obj):
                draw_obj.text(
                    (10, self.y_offset),
                    "Your library is not loading...",
                    font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                    fill="white"
                )
                draw_obj.text(
                    (10, self.y_offset + self.line_spacing),
                    "Have you enabled it via Volumio?",
                    font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                    fill="white"
                )

            self.display_manager.draw_custom(draw)
            
            # Automatically navigate back to the menu after 5 seconds.
            threading.Timer(5.0, self.mode_manager.to_menu).start()

    def stop_mode(self):
        if not self.is_active:
            self.logger.debug("USBLibraryManager: USB Library mode already inactive.")
            return
        self.is_active = False
        self.display_manager.clear_screen()
        self.logger.info("USBLibraryManager: Stopped USB Library mode and cleared display.")

    def fetch_navigation(self, uri):
        self.logger.info(f"USBLibraryManager: Fetching navigation data for URI: {uri}")
        if self.volumio_listener.is_connected():
            try:
                self.volumio_listener.fetch_browse_library(uri)
                self.logger.debug(f"USBLibraryManager: Emitted 'browseLibrary' for URI: {uri}")
            except Exception as e:
                self.logger.error(f"USBLibraryManager: Failed to emit 'browseLibrary' for {uri}: {e}")
                self.display_error_message("Navigation Error", f"Could not fetch navigation: {e}")
        else:
            self.logger.warning("USBLibraryManager: Cannot fetch navigation - not connected to Volumio.")
            self.display_error_message("Connection Error", "Not connected to Volumio.")

    def handle_navigation(self, sender, navigation, service, uri, **kwargs):
        # Handle only services related to mpd, and make sure it's related to USB
        if service != "mpd" or "USB" not in uri:
            self.logger.warning(f"USBLibraryManager: Ignoring service: {service} with URI: {uri}")
            return  # Ignore navigation data not related to USB storage

        self.logger.info("USBLibraryManager: Received navigation data for USB.")
        self.update_library_menu(navigation)

    def update_library_menu(self, navigation):
        """Update the menu items based on the navigation data."""
        if not navigation:
            self.logger.warning("USBLibraryManager: No navigation data received.")
            self.display_no_items()
            return

        lists = navigation.get("lists", [])
        if not lists or not isinstance(lists, list):
            self.logger.warning("USBLibraryManager: Navigation data has no valid lists.")
            self.display_no_items()
            return

        combined_items = []
        for lst in lists:
            list_items = lst.get("items", [])
            if list_items:
                combined_items.extend(list_items)

        if not combined_items:
            self.logger.info("USBLibraryManager: No items in navigation. Displaying 'No Items Available'.")
            self.display_no_items()
            return

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

        self.logger.info(f"USBLibraryManager: Updated menu with {len(self.current_menu_items)} items.")
        if self.is_active:
            self.display_menu()

    def display_menu(self):
        """Display the current menu."""
        self.logger.info("USBLibraryManager: Displaying current menu.")
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
        self.window_start_index = min(
            self.window_start_index, max(0, len(items) - self.window_size)
        )
        return items[self.window_start_index: self.window_start_index + self.window_size]

    def scroll_selection(self, direction):
        """Scroll the selection."""
        if not self.is_active or not self.current_menu_items:
            self.logger.warning("USBLibraryManager: Scroll attempted with no active items.")
            return

        previous_index = self.current_selection_index
        self.current_selection_index += direction
        self.current_selection_index = max(0, min(self.current_selection_index, len(self.current_menu_items) - 1))

        self.logger.debug(f"USBLibraryManager: Scrolled from {previous_index} to {self.current_selection_index}.")
        self.display_menu()

    def select_item(self):
        """Handle item selection."""
        if not self.is_active or not self.current_menu_items:
            return

        selected_item = self.current_menu_items[self.current_selection_index]
        self.logger.info(f"USBLibraryManager: Selected menu item: {selected_item}")

        name = selected_item.get("title")
        if name == "Back":
            self.back()
            return
        uri = selected_item.get("uri")
        if not uri:
            self.logger.warning("USBLibraryManager: Selected item has no URI.")
            self.display_error_message("Invalid Selection", "Selected item has no URI.")
            return

        # If it's a folder or a valid USB item, navigate into it
        if selected_item.get("type") in ["folder", "remdisk"]:
            self.logger.info(f"USBLibraryManager: Fetching navigation data for URI: {uri}")
            self.fetch_navigation(uri)
        else:
            self.logger.warning(f"USBLibraryManager: Unsupported item type: {selected_item.get('type')}")
            self.display_error_message("Invalid Selection", "Unsupported item type.")

    def display_loading_screen(self):
        """Show a loading screen."""
        self.logger.info("USBLibraryManager: Displaying loading screen.")

        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "Loading USB Library...",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def display_no_items(self):
        """Display a message if no items are available."""
        self.logger.info("USBLibraryManager: No items available.")

        def draw(draw_obj):
            draw_obj.text(
                (10, self.y_offset),
                "No USB Items Available",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def display_error_message(self, title, message):
        """Display an error message on the screen."""
        self.logger.info(f"USBLibraryManager: Displaying error message: {title} - {message}")

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

    def back(self):
        if self.is_active:
            self.stop_mode()
        self.mode_manager.back()
