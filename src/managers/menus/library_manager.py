
# src/managers/library_manager.py

import os
import logging
import requests
import threading
from threading import Thread, Event
from requests.adapters import HTTPAdapter
from urllib.parse import quote
from urllib3.util.retry import Retry
from PIL import Image, ImageDraw, ImageFont
from managers.base_manager import BaseManager  # Adjust import based on your project structure
from utils.menu_renderer import render_list_menu

class LibraryManager(BaseManager):
    def __init__(self, display_manager, volumio_config, mode_manager, window_size=3, y_offset=0, line_spacing=16):
        super().__init__(display_manager, volumio_config, mode_manager)

        # REST API setup
        self.volumio_host = volumio_config.get('host', 'localhost')
        self.volumio_port = volumio_config.get('port', 3000)
        self.base_url = f"http://{self.volumio_host}:{self.volumio_port}"

        # Initialize session with retry logic
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

        self.mode_name = "library"
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.info("LibraryManager initialized.")

        # Thread-safety lock
        self.selection_lock = threading.Lock()

        # Initialize state variables
        self.current_menu_items = []
        self.current_selection_index = 0
        self.window_start_index = 0
        self.is_active = False

        # Display settings
        self.window_size = window_size  # Number of menu items to display
        self.y_offset = y_offset
        self.line_spacing = line_spacing
        self.font_key = 'menu_font'

        # Initialize menu stack for navigation
        self.menu_stack = []

        # Current path context
        self.default_start_uri = "music-library"  # Default starting URI
        self.current_path = self.default_start_uri  # Starting at the root

        # Event to synchronize playback commands
        self.playback_event = Event()

        # Load configuration from config.yaml (assuming BaseManager has a method or attribute for this)
        self.config = self.display_manager.config  # Adjust based on actual implementation

        # Extract display settings
        display_config = self.config.get('display', {})
        self.icon_dir = display_config.get('icon_dir', '/home/volumio/Quadify/src/assets/images')

        # Register mode change callback
        if hasattr(self.mode_manager, "add_on_mode_change_callback"):
            self.mode_manager.add_on_mode_change_callback(self.handle_mode_change)


    def handle_mode_change(self, current_mode):
        """Handle mode changes."""
        self.logger.info(f"LibraryManager handling mode change to: {current_mode}")
        if current_mode == "library":
            self.logger.info("Entering Library mode.")
            self.start_mode(start_uri="music-library/NAS/Music")  # Start directly in "Music" folder
        elif current_mode == "usblibrary":
            self.logger.info("Entering USB Library mode.")
            self.start_mode(start_uri="music-library/USB")
        elif self.is_active:
            self.logger.info("Exiting Library mode.")
            self.stop_mode()

    def start_mode(self, start_uri=None):
        if self.is_active:
            self.logger.debug("LibraryManager: Library mode already active.")
            return

        self.logger.info("LibraryManager: Starting Library mode.")
        self.is_active = True

        # Reset selection indices
        self.current_selection_index = 0
        self.window_start_index = 0

        # Clear the menu stack to prevent residual states
        self.menu_stack = []

        # Use the provided start_uri or default to "music-library"
        self.current_path = start_uri if start_uri else self.default_start_uri
        self.logger.info(f"LibraryManager: Starting navigation at URI: {self.current_path}")

        self.display_loading_screen()
        self.fetch_navigation(self.current_path)

        # Log the reset state
        self.logger.debug(f"LibraryManager: Mode active: {self.is_active}, Selection Index: {self.current_selection_index}, Window Start Index: {self.window_start_index}")

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
            import threading
            threading.Timer(5.0, self.mode_manager.to_menu).start()


    def stop_mode(self):
        if not self.is_active:
            self.logger.debug("LibraryManager: Library mode already inactive.")
            return
        self.is_active = False
        self.display_manager.clear_screen()
        self.logger.info("LibraryManager: Stopped Library mode and cleared display.")

    def fetch_navigation(self, uri):
        """Fetch navigation data dynamically for any folder in the music library."""
        self.logger.info(f"LibraryManager: Fetching navigation data for URI: {uri}")
        try:
            # API request to fetch navigation data
            response = self.session.get(f"{self.base_url}/api/v1/browse?uri={quote(uri)}")
            self.logger.debug(f"LibraryManager: Received Status Code: {response.status_code}")
            self.logger.debug(f"LibraryManager: Received Response: {response.text}")

            # Handle non-200 status codes
            if response.status_code != 200:
                self.logger.error(f"LibraryManager: Failed to fetch data. Status Code: {response.status_code}")
                self.display_error_message("Fetch Error", f"Failed to fetch data: {response.status_code}")
                return

            # Parse the response JSON
            data = response.json()
            navigation = data.get("navigation", {})
            lists = navigation.get("lists", [])

            if not lists:
                self.logger.warning("LibraryManager: No lists available in the navigation data.")
                self.display_no_items()
                return

            # Process the first list (typically the relevant one)
            items = lists[0].get("items", [])
            if not items:
                self.logger.info("LibraryManager: No items in the current folder.")
                self.display_no_items()
                return

            # Update current menu items
            self.current_menu_items = [
                {
                    "title": item.get("title", "Untitled"),
                    "uri": item.get("uri", ""),
                    "type": item.get("type", "").lower(),
                    "service": item.get("service", "").lower(),
                    "albumart": item.get("albumart", None)
                }
                for item in items
            ]
            self.current_menu_items.append({"title": "Back", "uri": None, "type": "back"})

            self.logger.info(f"LibraryManager: Fetched {len(self.current_menu_items)} items for URI: {uri}")
            if self.is_active:
                self.display_menu()

        except ValueError as ve:
            self.logger.error(f"LibraryManager: JSON decoding failed: {ve}")
            self.display_error_message("Fetch Error", f"Invalid response format: {ve}")
        except Exception as e:
            self.logger.error(f"LibraryManager: Exception occurred while fetching navigation: {str(e)}")
            self.display_error_message("Fetch Error", f"An error occurred: {str(e)}")

    def select_item(self):
        """Handle the selection of the current menu item."""
        if not self.is_active or not self.current_menu_items:
            self.logger.warning("LibraryManager: Select attempted while inactive or no items available.")
            return

        selected_item = self.current_menu_items[self.current_selection_index]
        self.logger.info(f"LibraryManager: Selected item: {selected_item}")

        if selected_item.get("title") == "Back":
            self.back()
            return

        if 'action' in selected_item:
            # Handle submenu actions
            action = selected_item.get('action')
            data = selected_item.get('data')
            self.perform_action(action, data)
        else:
            item_type = selected_item.get("type", "").lower()

            if item_type in ["folder", "streaming-category", "streaming-folder", "remdisk"]:
                # Check if the selected item is an album
                if self.is_album_folder(selected_item):
                    # Display album options (submenu)
                    self.logger.info(f"LibraryManager: Displaying options for album: {selected_item.get('title')}")
                    self.display_folder_or_album_options(selected_item)
                else:
                    # Navigate into the folder
                    self.logger.info(f"LibraryManager: Navigating into: {selected_item.get('title')}")
                    self.menu_stack.append(self.current_path)  # Save the current path
                    self.current_path = selected_item.get("uri")
                    self.display_loading_screen()
                    self.fetch_navigation(self.current_path)

            elif item_type == "song":
                # Play the selected song
                self.logger.info(f"LibraryManager: Playing song: {selected_item.get('title')}")
                self.replace_and_play(selected_item)

            elif item_type == "webradio":
                # Handle web radio streams if necessary
                self.logger.info(f"LibraryManager: Playing web radio: {selected_item.get('title')}")
                self.replace_and_play(selected_item)

            else:
                self.logger.warning(f"LibraryManager: Unknown item type '{item_type}'.")
                self.display_error_message("Invalid Selection", "Selected item is not recognized.")

    def is_album_folder(self, item):
        """Determine if the folder represents an album."""
        # Adjust the logic based on your folder structure
        # For example, if albums are folders that contain only songs, we can check that
        folder_uri = item.get("uri")
        if not folder_uri:
            return False

        try:
            # Fetch the contents of the folder
            response = self.session.get(f"{self.base_url}/api/v1/browse?uri={quote(folder_uri)}")
            if response.status_code != 200:
                self.logger.warning(f"LibraryManager: Failed to fetch contents for album check: {folder_uri}")
                return False

            folder_data = response.json()
            items = folder_data.get("navigation", {}).get("lists", [{}])[0].get("items", [])

            # If all items are songs, or there are no subfolders, consider it an album
            has_songs = any(item.get("type", "").lower() == "song" for item in items)
            has_subfolders = any(item.get("type", "").lower() == "folder" for item in items)

            is_album = has_songs and not has_subfolders
            return is_album

        except Exception as e:
            self.logger.error(f"LibraryManager: Exception during album check: {e}")
            return False

    def display_folder_or_album_options(self, folder_item):
        """Display options for a selected album as a new menu."""
        self.logger.info(f"LibraryManager: Displaying options for album: {folder_item.get('title')}")

        # Define the submenu with icons
        options = [
            {"title": "Play Album", "action": "play_album", "data": folder_item, "icon": "play"},
            {"title": "Select Songs", "action": "select_songs", "data": folder_item, "icon": "songs"},
            {"title": "Back", "action": "back", "icon": "back"}
        ]

        # Push the options menu onto the stack
        self.push_menu(options, menu_title=f"Album: {folder_item.get('title')}")

    def perform_action(self, action, data):
        """Perform an action based on the menu selection."""
        if action == "play_album":
            self.logger.info(f"LibraryManager: Playing entire album: {data.get('title')}")
            self.play_album_or_folder(data)
        elif action == "select_songs":
            self.logger.info(f"LibraryManager: Fetching songs for album: {data.get('title')}")
            self.menu_stack.append(self.current_path)  # Save current path
            self.current_path = data.get("uri")
            self.display_loading_screen()
            self.fetch_navigation(self.current_path)
        elif action == "back":
            self.logger.info("LibraryManager: Going back to the previous menu.")
            self.pop_menu()
        else:
            self.logger.warning(f"LibraryManager: Unknown action '{action}'.")
            self.display_error_message("Invalid Action", "This action is not recognized.")

    def play_album_or_folder(self, folder_item):
        """Play all songs in a folder or album."""
        folder_uri = folder_item.get("uri")
        if not folder_uri:
            self.logger.error("LibraryManager: Selected folder does not have a valid URI.")
            self.display_error_message("Playback Error", "Selected folder cannot be played.")
            return

        self.logger.info(f"LibraryManager: Playing all songs from folder: {folder_item.get('title')}")
        Thread(target=self._play_album_or_folder_thread, args=(folder_uri, folder_item.get('title')), daemon=True).start()

    def _play_album_or_folder_thread(self, folder_uri, album_title):
        """Thread to handle playing all songs in a folder."""
        try:
            # Step 1: Replace current queue with album's tracks and start playback
            replace_and_play_url = f"{self.base_url}/api/v1/replaceAndPlay"
            data = {
                "name": album_title,
                "service": "mpd",
                "uri": folder_uri
            }
            replace_response = self.session.post(replace_and_play_url, json=data)

            if replace_response.status_code == 200:
                self.logger.info(f"LibraryManager: Playback started successfully for the album: {album_title}")
                self.display_success_message("Playback Started", f"Playing album: {album_title}")
            else:
                self.logger.error(f"LibraryManager: Failed to start playback for album: {album_title}. Status Code: {replace_response.status_code}, Response: {replace_response.text}")
                self.display_error_message("Playback Error", f"Failed to start playback: {replace_response.status_code}")

        except Exception as e:
            self.logger.error(f"LibraryManager: Failed to play album: {str(e)}")
            self.display_error_message("Playback Error", f"Could not play album: {str(e)}")

    def replace_and_play(self, item):
        """Replace current queue and play the selected item."""
        song_uri = item.get("uri")
        if not song_uri:
            self.logger.error("LibraryManager: Selected item does not have a valid URI.")
            self.display_error_message("Playback Error", "Selected item cannot be played.")
            return

        self.logger.info(f"LibraryManager: Replacing and playing item: {item.get('title')}")
        try:
            replace_and_play_url = f"{self.base_url}/api/v1/replaceAndPlay"
            data = {
                "name": item.get("title", "Untitled"),
                "service": item.get("service", "mpd"),
                "uri": song_uri
            }
            response = self.session.post(replace_and_play_url, json=data)

            if response.status_code == 200:
                self.logger.info(f"LibraryManager: Playback started successfully for: {item.get('title')}")
                self.display_success_message("Playback Started", f"Playing: {item.get('title')}")
            else:
                self.logger.error(f"LibraryManager: Failed to start playback. Status Code: {response.status_code}, Response: {response.text}")
                self.display_error_message("Playback Error", f"Failed to start playback: {response.status_code}")

        except Exception as e:
            self.logger.error(f"LibraryManager: Exception occurred while trying to play item: {str(e)}")
            self.display_error_message("Playback Error", f"Could not play item: {str(e)}")

    def display_loading_screen(self):
        """Show a loading screen."""
        self.logger.info("LibraryManager: Displaying loading screen.")

        def draw(draw_obj):
            # Display loading text
            draw_obj.text(
                (0, self.y_offset),
                "Loading...",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def display_menu(self):
        """Display the current menu."""
        # Determine the menu title based on current path
        menu_title = self.current_path.split("/")[-1] if "/" in self.current_path else self.current_path

        # If a submenu is active, the top of the stack contains the submenu title
        is_submenu = bool(self.menu_stack and isinstance(self.menu_stack[-1], dict) and "menu_title" in self.menu_stack[-1])
        if is_submenu:
            menu_title = self.menu_stack[-1].get("menu_title", menu_title)

        self.logger.info(f"LibraryManager: Displaying menu: {menu_title}")
        self.window_start_index = render_list_menu(
            display_manager=self.display_manager,
            title=menu_title,
            items=self.current_menu_items,
            current_selection_index=self.current_selection_index,
            window_start_index=self.window_start_index,
            window_size=self.window_size,
            y_offset=self.y_offset,
            line_spacing=self.line_spacing,
            font_key=self.font_key,
        )

    def push_menu(self, menu_items, menu_title=""):
        """Push a new menu onto the stack and display it."""
        # Save the current menu state
        self.menu_stack.append({
            "menu_items": self.current_menu_items.copy(),
            "selection_index": self.current_selection_index,
            "window_start_index": self.window_start_index,
            "menu_title": menu_title if menu_title else "Options"
        })

        # Update to the new submenu
        self.current_menu_items = menu_items
        self.current_selection_index = 0
        self.window_start_index = 0

        # Display the submenu
        self.display_menu()

    def pop_menu(self):
        """Pop the top menu from the stack and display the previous menu."""
        if not self.menu_stack:
            self.logger.warning("LibraryManager: Menu stack is empty, cannot pop.")
            return

        previous_menu = self.menu_stack.pop()
        self.current_menu_items = previous_menu["menu_items"]
        self.current_selection_index = previous_menu["selection_index"]
        self.window_start_index = previous_menu["window_start_index"]
        menu_title = previous_menu["menu_title"]

        self.logger.info(f"LibraryManager: Returning to menu: {menu_title}")

        # Display the previous menu
        self.display_menu()

    def get_visible_window(self, items):
        """Return the visible window of items based on the current selection and window size."""
        if self.current_selection_index < self.window_start_index:
            self.window_start_index = self.current_selection_index
        elif self.current_selection_index >= self.window_start_index + self.window_size:
            self.window_start_index = self.current_selection_index - self.window_size + 1

        self.window_start_index = max(0, self.window_start_index)
        self.window_start_index = min(
            self.window_start_index, max(0, len(items) - self.window_size)
        )
        return items[self.window_start_index : self.window_start_index + self.window_size]

    def scroll_selection(self, direction):
        """Scroll the selection up or down."""
        if not self.is_active or not self.current_menu_items:
            self.logger.warning("LibraryManager: Scroll attempted with no active items.")
            return

        previous_index = self.current_selection_index
        self.current_selection_index += direction
        self.current_selection_index = max(
            0, min(self.current_selection_index, len(self.current_menu_items) - 1)
        )

        self.logger.debug(f"LibraryManager: Scrolled from {previous_index} to {self.current_selection_index}.")
        self.display_menu()

    def display_no_items(self):
        """Display a message if no items are available."""
        self.logger.info("LibraryManager: No items available.")

        def draw(draw_obj):
            draw_obj.text(
                (0, self.y_offset),
                "No Items Available",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def display_error_message(self, title, message):
        """Display an error message on the screen."""
        self.logger.info(f"LibraryManager: Displaying error message: {title} - {message}")

        def draw(draw_obj):
            # Display title
            draw_obj.text(
                (0, self.y_offset),
                f"Error: {title}",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="red"
            )
            # Display message
            draw_obj.text(
                (0, self.y_offset + self.line_spacing),
                message[:20],  # Truncate to fit
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def display_success_message(self, title, message):
        """Display a success message on the screen."""
        self.logger.info(f"LibraryManager: Displaying success message: {title} - {message}")

        def draw(draw_obj):
            # Display title
            draw_obj.text(
                (0, self.y_offset),
                f"{title}",
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="green"
            )
            # Display message
            draw_obj.text(
                (0, self.y_offset + self.line_spacing),
                message[:20],  # Truncate to fit
                font=self.display_manager.fonts.get(self.font_key, ImageFont.load_default()),
                fill="white"
            )

        self.display_manager.draw_custom(draw)

    def go_back(self):
        """Handle going back to the previous navigation level."""
        if self.menu_stack:
            # Check if we're in a submenu
            if isinstance(self.menu_stack[-1], dict) and "menu_title" in self.menu_stack[-1]:
                self.pop_menu()
            else:
                self.current_path = self.menu_stack.pop()
                self.display_loading_screen()
                self.fetch_navigation(self.current_path)
        else:
            self.logger.info("LibraryManager: Already at root level, cannot go back.")
            self.stop_mode()  # Optionally exit the mode if at root
            

    def update_song_info(self, state):
        """Update the playback metrics display based on the current state."""
        self.logger.info("LibraryManager: Updating playback metrics display.")

        # Extract relevant playback information
        sample_rate = state.get("samplerate", "Unknown Sample Rate")
        bitdepth = state.get("bitdepth", "Unknown Bit Depth")
        volume = state.get("volume", "Unknown Volume")

        # Log or display the extracted information
        self.logger.info(f"Sample Rate: {sample_rate}, Bit Depth: {bitdepth}, Volume: {volume}")

    def back(self):
        if self.menu_stack:
            self.pop_menu()
        else:
            if self.is_active:
                self.stop_mode()
            self.mode_manager.back()

        # Optional: Update the screen with this information if needed
        # You can call methods on `self.display_manager` or another appropriate object
