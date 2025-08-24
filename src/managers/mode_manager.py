import logging
import os
import json
import threading
import time
import subprocess
from transitions import Machine
from .menus.streaming_manager import StreamingManager


class ModeManager:
    """
    A unified ModeManager for Quadify that includes:
      - Display-mode persistence (original/modern)
      - Screensaver & idle logic
      - Additional states for Tidal/Qobuz/Radio/Playlists
      - Possibly a 'boot' or 'systeminfo' state if desired
    """

    states = [
        {'name': 'boot',            'on_enter': 'enter_boot'},
        {'name': 'clock',           'on_enter': 'enter_clock'},
        {'name': 'screensaver',     'on_enter': 'enter_screensaver'},
        {'name': 'screensavermenu', 'on_enter': 'enter_screensavermenu'},
        {'name': 'displaymenu',     'on_enter': 'enter_displaymenu'},
        {'name': 'clockmenu',       'on_enter': 'enter_clockmenu'},
        {'name': 'original',        'on_enter': 'enter_original'},
        {'name': 'modern',          'on_enter': 'enter_modern'},
        {'name': 'minimal',         'on_enter': 'enter_minimal'},
        {'name': 'vuscreen',        'on_enter': 'enter_vuscreen'},
        {'name': 'digitalvuscreen', 'on_enter': 'enter_digitalvuscreen'},
        {'name': 'configmenu',      'on_enter': 'enter_configmenu'},
        {'name': 'systemupdate',    'on_enter': 'enter_systemupdate'},
        {'name': 'menu',            'on_enter': 'enter_menu', 'on_exit': 'cancel_menu_inactivity_timer'},
        {'name': 'remotemenu',      'on_enter': 'enter_remotemenu'},
        {'name': 'airplay',          'on_enter': 'enter_airplay'},


        {'name': 'streaming',       'on_enter': 'enter_streaming'},
        {'name': 'playlists',       'on_enter': 'enter_playlists'},
        {'name': 'webradio',        'on_enter': 'enter_webradio'},
        {'name': 'motherearthradio', 'on_enter': 'enter_motherearthradio'},
        {'name': 'radioparadise',   'on_enter': 'enter_radioparadise'},
        {'name': 'radio',           'on_enter': 'enter_radio'},

        {'name': 'library',         'on_enter': 'enter_library'},
        {'name': 'artists',          'on_enter': 'enter_artists'},
        {'name': 'albums',          'on_enter': 'enter_albums'},
        {'name': 'genres',          'on_enter': 'enter_genres'},
        {'name': 'favourites',      'on_enter': 'enter_favourites'},
        {'name': 'last100',         'on_enter': 'enter_last100'},
        {'name': 'mediaservers',    'on_enter': 'enter_mediaservers'},
    ]

    def __init__(self, display_manager, clock, volumio_listener,
                 preference_file_path="../preference.json", config=None):
        """
        :param display_manager:   Manages the OLED display
        :param clock:             Clock instance
        :param volumio_listener:  Object that fires state_changed signals from Volumio
        :param preference_file_path: JSON file to store user preferences
        :param config:            Combined config loaded from YAML, etc.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)
        self.logger.debug("ModeManager: Initializing...")

        self.display_manager = display_manager
        self.clock = clock
        self.volumio_listener = volumio_listener
        self.config = config or {}

        # Navigation history stack
        self.mode_stack = []

        self.last_mode_change_time = 0.0
        self.min_mode_switch_interval = 0.5

        # Preferences
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.preference_file_path = os.path.join(script_dir, preference_file_path)
        preferences = self._load_preferences()
        for key in (
            "display_mode", "clock_font_key", "show_seconds", "show_date",
            "screensaver_enabled", "screensaver_type", "screensaver_timeout",
            "oled_brightness", "cava_enabled", "modern_spectrum_mode", "ignore_airplay"
        ):
            self.config[key] = preferences[key]

        # References to other managers/screens (set via ManagerFactory or manually)
        self.menu_manager = None
        self.config_menu = None
        self.library_manager = None
        self.streaming_manager = None
        self.original_screen = None
        self.modern_screen = None
        self.minimal_screen = None
        self.webradio_screen = None
        self.airplay_screen = None
        self.vu_screen = None
        self.digitalvu_screen = None
        self.screensaver = None
        self.screensaver_menu = None
        self.clock_menu = None
        self.system_update_menu = None
        self.radio_manager = None

        # Idle/Screensaver logic
        self.idle_timer = None
        self.idle_timeout = self.config.get("screensaver_timeout", 60)

        self.suppress_state_changes = False
        self.is_track_changing = False
        self.track_change_in_progress = False
        self.current_status = None
        self.previous_status = None
        self.pause_stop_timer = None
        self.pause_stop_delay = 1.5

        self.first_state_handoff = True  # New flag

        self.logger.debug(f"ModeManager: idle_timeout={self.idle_timeout}, display_mode={self.config.get('display_mode')}")

        # Set up the state machine
        self.machine = Machine(
            model=self,
            states=ModeManager.states,
            initial='clock',
            send_event=True
        )
        self._define_transitions()

        if self.volumio_listener is not None:
            self.volumio_listener.state_changed.connect(self.process_state_change)
            self.logger.debug("ModeManager: Connected to volumio_listener.state_changed signal.")
        else:
            self.logger.warning("ModeManager: volumio_listener is None, no state_changed signal linked.")

        self.lock = threading.Lock()
        
        self.menu_inactivity_timer = None
        self.menu_inactivity_timeout = 15  # seconds; change as needed
        self.menu_modes = {"menu"}


    # --- Callback to push the current state before a transition ---
    def push_current_state(self, event):
        if event.event.name != "back" and self.state is not None:
            self.mode_stack.append(self.state)
            self.logger.debug("ModeManager: Pushed '%s' onto stack. Stack now: %s", self.state, self.mode_stack)

    # --- Preferences methods ---
    def _load_screen_preference(self):
        if os.path.exists(self.preference_file_path):
            try:
                with open(self.preference_file_path, "r") as f:
                    data = json.load(f)
                    mode = data.get("display_mode", "original")
                    self.logger.info(f"Loaded display mode preference: {mode}")
                    return mode
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(f"Failed to load preference; defaulting to 'original'. Error: {e}")
        else:
            self.logger.info(f"No preference file at {self.preference_file_path}, using 'original'.")
        return "original"

    def save_preferences(self):
        if not self.preference_file_path:
            return
        if os.path.exists(self.preference_file_path):
            with open(self.preference_file_path, "r") as f:
                try:
                    data = json.load(f)
                except (json.JSONDecodeError, IOError):
                    data = {}
        else:
            data = {}
        for key in (
            "display_mode", "clock_font_key", "show_seconds", "show_date",
            "screensaver_enabled", "screensaver_type", "screensaver_timeout",
            "oled_brightness", "cava_enabled", "modern_spectrum_mode"
        ):
            if key in self.config:
                data[key] = self.config[key]
        try:
            with open(self.preference_file_path, "w") as f:
                json.dump(data, f, indent=2)
            self.logger.info(f"ModeManager: Preferences saved to {self.preference_file_path}.")
        except IOError as e:
            self.logger.warning(f"ModeManager: Could not write to {self.preference_file_path}. Error: {e}")

    def set_display_mode(self, mode_name):
        if mode_name in ("original", "modern", "minimal", "vuscreen", "digitalvuscreen"):
            self.config["display_mode"] = mode_name
            self.logger.info(f"ModeManager: Display mode set to '{mode_name}'.")
            self.save_preferences()
        else:
            self.logger.warning(f"Unknown display mode '{mode_name}'.")

    def _load_preferences(self):
        default_preferences = {
            "display_mode": "original",
            "modern_spectrum_mode": "bars",
            "clock_font_key": "default",
            "show_seconds": True,
            "show_date": True,
            "screensaver_enabled": False,
            "screensaver_type": "none",
            "screensaver_timeout": 120,
            "oled_brightness": 100,
            "cava_enabled": False,
            "ignore_airplay": True,
        }
        if os.path.exists(self.preference_file_path):
            try:
                with open(self.preference_file_path, "r") as f:
                    file_preferences = json.load(f)
                    default_preferences.update(file_preferences)
                    self.logger.info(f"Loaded preferences: {default_preferences}")
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(f"Failed to load preferences. Using defaults. Error: {e}")
        else:
            self.logger.info(f"No preference file found at {self.preference_file_path}. Using defaults.")
        return default_preferences
    

    # --- Set References for Other Managers/Screen Objects ---
    def set_menu_manager(self, menu_manager):
        self.menu_manager = menu_manager

    def set_config_menu(self, config_menu):
        self.config_menu = config_menu

    def set_library_manager(self, library_manager):
        self.library_manager = library_manager

    def set_streaming_manager(self, streaming_manager):
        self.streaming_manager = streaming_manager

    def set_radio_manager(self, radio_manager):
        self.radio_manager = radio_manager

    def set_original_screen(self, original_screen):
        self.original_screen = original_screen

    def set_modern_screen(self, modern_screen):
        self.modern_screen = modern_screen

    def set_minimal_screen(self, minimal_screen):
        self.minimal_screen = minimal_screen

    def set_vu_screen(self, vu_screen):
        self.vu_screen = vu_screen

    def set_digitalvu_screen(self, digitalvu_screen):
        self.digitalvu_screen = digitalvu_screen

    def set_webradio_screen(self, webradio_screen):
        self.webradio_screen = webradio_screen

    def set_airplay_screen(self, airplay_screen):
        self.airplay_screen = airplay_screen

    def set_clock_menu(self, clock_menu):
        self.clock_menu = clock_menu

    def set_screensaver(self, screensaver):
        self.screensaver = screensaver

    def set_screensaver_menu(self, screensaver_menu):
        self.screensaver_menu = screensaver_menu

    def set_system_update_menu(self, system_update_menu):
        self.system_update_menu = system_update_menu

    # --- State-Suppression Logic ---
    def suppress_state_change(self):
        with self.lock:
            self.suppress_state_changes = True
            self.logger.debug("ModeManager: State changes suppressed.")

    def allow_state_change(self):
        with self.lock:
            self.suppress_state_changes = False
            self.logger.debug("ModeManager: State changes allowed.")

    def is_state_change_suppressed(self):
        return self.suppress_state_changes

    # --- Idle / Screensaver Methods ---
    def reset_idle_timer(self):
        self.idle_timeout = self.config.get("screensaver_timeout", 360)
        if not self.config.get("screensaver_enabled", True):
            self._cancel_idle_timer()
            return
        self._cancel_idle_timer()
        self._start_idle_timer()

    def _start_idle_timer(self):
        if self.idle_timeout <= 0:
            return
        self.idle_timer = threading.Timer(self.idle_timeout, self._idle_timeout_reached)
        self.idle_timer.start()
        self.logger.debug(f"ModeManager: Idle timer started for {self.idle_timeout}s.")

    def _cancel_idle_timer(self):
        if self.idle_timer:
            self.idle_timer.cancel()
            self.idle_timer = None
            self.logger.debug("ModeManager: Idle timer canceled.")

    def _idle_timeout_reached(self):
        with self.lock:
            current_mode = self.get_mode()
            if current_mode == "clock":
                self.logger.debug("ModeManager: Idle timeout => to_screensaver.")
                self.to_screensaver()
            else:
                self.logger.debug(f"ModeManager: Idle in '{current_mode}', not going to screensaver.")

    # --- Transitions Definition ---
    def _define_transitions(self):
        # Each transition gets before='push_current_state'
        self.machine.add_transition('to_boot',         source='*', dest='boot', before='push_current_state')
        self.machine.add_transition('to_clock',        source='*', dest='clock', before='push_current_state')
        self.machine.add_transition('to_screensaver',  source='*', dest='screensaver', before='push_current_state')
        self.machine.add_transition('to_screensavermenu', source='*', dest='screensavermenu', before='push_current_state')
        self.machine.add_transition('to_displaymenu',  source='*', dest='displaymenu', before='push_current_state')
        self.machine.add_transition('to_clockmenu',    source='*', dest='clockmenu', before='push_current_state')
        self.machine.add_transition('to_remotemenu',    source='*', dest='remotemenu', before='push_current_state')
        self.machine.add_transition('to_configmenu',   source='*', dest='configmenu', before='push_current_state')
        self.machine.add_transition('to_original',     source='*', dest='original', before='push_current_state')
        self.machine.add_transition('to_modern',       source='*', dest='modern', before='push_current_state')
        self.machine.add_transition('to_minimal',      source='*', dest='minimal', before='push_current_state')
        self.machine.add_transition('to_vuscreen',     source='*', dest='vuscreen', before='push_current_state')
        self.machine.add_transition('to_systemupdate', source='*', dest='systemupdate', before='push_current_state')
        self.machine.add_transition('to_radio',        source='*', dest='radio', before='push_current_state')
        self.machine.add_transition('to_menu',         source='*', dest='menu', before='push_current_state')
        self.machine.add_transition('to_airplay',     source='*', dest='airplay', before='push_current_state')

        self.machine.add_transition('to_streaming',    source='*', dest='streaming', before='push_current_state')
        self.machine.add_transition('to_webradio',     source='*', dest='webradio', before='push_current_state')
        self.machine.add_transition('to_motherearthradio',  source='*', dest='motherearthradio', before='push_current_state')
        self.machine.add_transition('to_radioparadise', source='*', dest='radioparadise', before='push_current_state')  

        self.machine.add_transition('to_library',      source='*', dest='library', before='push_current_state')
        self.machine.add_transition('to_albums',        source='*', dest='albums', before='push_current_state')
        self.machine.add_transition('to_artists',       source='*', dest='artists', before='push_current_state')
        self.machine.add_transition('to_genres',        source='*', dest='genres', before='push_current_state')
        self.machine.add_transition('to_favourites',    source='*', dest='favourites', before='push_current_state')
        self.machine.add_transition('to_last100',       source='*', dest='last100', before='push_current_state')
        self.machine.add_transition('to_mediaservers',  source='*', dest='mediaservers', before='push_current_state')
        self.machine.add_transition('to_playlists',    source='*', dest='playlists', before='push_current_state')

    # --- Custom trigger() Method ---
    def trigger(self, event_name, **kwargs):
        # For events other than "back", push current state onto the stack.
        if event_name != "back" and self.state is not None:
            self.mode_stack.append(self.state)
            self.logger.debug("ModeManager: Pushed '%s' onto stack. Stack now: %s", self.state, self.mode_stack)
        # Look up the auto-generated event method on self.
        event_method = getattr(self, event_name, None)
        if callable(event_method):
            event_method(**kwargs)
        else:
            self.logger.error("ModeManager: No event method for '%s' found.", event_name)

    # --- Helpers ---
    def get_mode(self):
        return self.state

    def stop_all_screens(self):
        self.logger.debug("ModeManager: stop_all_screens called.")
        if self.clock:
            self.clock.stop()
        if self.screensaver:
            self.screensaver.stop_screensaver()
        if self.screensaver_menu and self.screensaver_menu.is_active:
            self.screensaver_menu.stop_mode()
        if self.menu_manager and self.menu_manager.is_active:
            self.menu_manager.stop_mode()
        if self.config_menu and self.config_menu.is_active:
            self.config_menu.stop_mode()
        if self.clock_menu and self.clock_menu.is_active:
            self.clock_menu.stop_mode()
        if self.library_manager and self.library_manager.is_active:
            self.library_manager.stop_mode()
        if self.streaming_manager and self.streaming_manager.is_active:
            self.streaming_manager.stop_mode()
        if self.radio_manager and self.radio_manager.is_active:
            self.radio_manager.stop_mode()

        if self.original_screen and self.original_screen.is_active:
            self.original_screen.stop_mode()
        if self.modern_screen and self.modern_screen.is_active:
            self.modern_screen.stop_mode()
        if self.minimal_screen and self.minimal_screen.is_active:
            self.minimal_screen.stop_mode()
        if self.vu_screen and self.vu_screen.is_active:
            self.vu_screen.stop_mode()
        if self.digitalvu_screen and self.digitalvu_screen.is_active:
            self.digitalvu_screen.stop_mode()
        if self.webradio_screen and self.webradio_screen.is_active:
            self.webradio_screen.stop_mode()
        if self.airplay_screen and self.airplay_screen.is_active:
            self.airplay_screen.stop_mode()
        if self.system_update_menu and self.system_update_menu.is_active:
            self.system_update_menu.stop_mode()
            
    def start_menu_inactivity_timer(self):
        if self.get_mode() in ["library", "tidal", "qobuz", "spotify"]:
            self.logger.debug("ModeManager: Inactivity timer skipped for '%s' mode.", self.get_mode())
            return

        self.cancel_menu_inactivity_timer()
        self.menu_inactivity_timer = threading.Timer(
            self.menu_inactivity_timeout, self.exit_menu_to_clock)
        self.menu_inactivity_timer.start()
        self.logger.debug(
            f"ModeManager: Started menu inactivity timer for {self.menu_inactivity_timeout} seconds.")

    def reset_menu_inactivity_timer(self):
        if self.get_mode() == "menu":
            self.start_menu_inactivity_timer()

    def cancel_menu_inactivity_timer(self, *args, **kwargs):
        if self.menu_inactivity_timer:
            self.menu_inactivity_timer.cancel()
            self.menu_inactivity_timer = None

    def exit_menu_to_clock(self):
        if self.get_mode() == "menu":
            self.logger.info("ModeManager: Menu inactivity timeout reached. Returning to clock.")
            self.to_clock()

    # --- State Entry Methods ---

    def enter_boot(self, event):
        self.logger.info("ModeManager: Entering 'boot' state.")
        self.stop_all_screens()

    def enter_clock(self, event):
        self.logger.info("ModeManager: Entering 'clock' mode.")
        self.stop_all_screens()
        if self.clock:
            self.clock.config = self.config
            self.clock.start()
            self.logger.info("ModeManager: Clock started.")
        else:
            self.logger.warning("ModeManager: No Clock instance.")
        self.reset_idle_timer()
        self.update_current_mode()
        self.cancel_menu_inactivity_timer()  # No timeout on clock
        
    # --- Screens ---

    def enter_modern(self, event):
        self.logger.info("ModeManager: Entering 'modern' playback mode.")
        self.stop_all_screens()
        if self.modern_screen:
            self.modern_screen.start_mode()
            self.logger.info("ModeManager: Modern screen started.")
        else:
            self.logger.warning("ModeManager: No modern_screen set.")
        self.update_current_mode()
        self.cancel_menu_inactivity_timer()  # No timeout on clock

    def enter_minimal(self, event):
        self.logger.info("ModeManager: Entering 'minimal' playback mode.")
        self.stop_all_screens()
        if self.minimal_screen:
            self.minimal_screen.start_mode()
            self.logger.info("ModeManager: Minimal screen started.")
        else:
            self.logger.warning("ModeManager: No minimal_screen set.")
        self.update_current_mode()
        self.cancel_menu_inactivity_timer()  # No timeout on clock
        
    def enter_original(self, event):
        self.logger.info("ModeManager: Entering 'original' playback mode.")
        self.stop_all_screens()
        if self.original_screen:
            self.original_screen.start_mode()
            self.logger.info("ModeManager: Original screen started.")
        else:
            self.logger.warning("ModeManager: No original_screen set.")
        self.update_current_mode()
        self.cancel_menu_inactivity_timer()  # No timeout on clock

    def enter_vuscreen(self, event):
        self.logger.info("ModeManager: Entering 'vuscreen' playback mode.")
        self.stop_all_screens()
        if self.vu_screen:
            self.vu_screen.start_mode()
            self.logger.info("ModeManager: VU screen started.")
        else:
            self.logger.warning("ModeManager: No vu_screen set.")
        self.update_current_mode()
        self.cancel_menu_inactivity_timer()  # No timeout on clock

    def enter_digitalvuscreen(self, event):
        self.logger.info("ModeManager: Entering 'digitalvuscreen' playback mode.")
        self.stop_all_screens()
        if self.digitalvu_screen:
            self.digitalvu_screen.start_mode()
            self.logger.info("ModeManager: DigitalVU screen started.")
        else:
            self.logger.warning("ModeManager: No digitalvu_screen set.")
        self.update_current_mode()
        self.cancel_menu_inactivity_timer()  # No timeout on clock
    
    # --- Menu Managers ---

    def enter_configmenu(self, event):
        self.logger.info("ModeManager: Entering 'displaymenu'.")
        self.stop_all_screens()
        if self.config_menu:
            self.config_menu.start_mode()
            self.logger.info("ModeManager: display menu started.")
        else:
            self.logger.warning("ModeManager: No displaymenu set.")
        self.reset_idle_timer()
        #self.start_menu_inactivity_timer()
        self.update_current_mode()

    def exit_screensaver(self):
        self.logger.info("ModeManager: Exiting screensaver mode.")
        if self.screensaver:
            self.screensaver.stop_screensaver()
        self.to_clock()

    def enter_screensaver(self, event):
        self.logger.info("ModeManager: Entering 'screensaver' state.")
        self.stop_all_screens()
        if self.screensaver:
            self.screensaver.start_screensaver()
            self.logger.info("ModeManager: Screensaver started.")
        else:
            self.logger.warning("ModeManager: screensaver is None.")
        self.update_current_mode()
        self.cancel_menu_inactivity_timer()  # No timeout on clock

    def enter_screensavermenu(self, event):
        self.logger.info("ModeManager: Entering 'screensavermenu' state.")
        self.stop_all_screens()
        if self.screensaver_menu:
            self.screensaver_menu.start_mode()
            self.logger.info("ModeManager: Screensaver menu started.")
        else:
            self.logger.warning("ModeManager: No screensaver_menu set.")
        self.reset_idle_timer()
        self.start_menu_inactivity_timer()
        self.update_current_mode()

    def enter_clockmenu(self, event):
        self.logger.info("ModeManager: Entering 'clockmenu' state.")
        self.stop_all_screens()
        if self.clock_menu:
            self.clock_menu.start_mode()
            self.logger.info("ModeManager: Clock menu started.")
        else:
            self.logger.warning("ModeManager: No clock_menu set.")
        self.reset_idle_timer()
        self.start_menu_inactivity_timer()
        self.update_current_mode()

    def enter_systemupdate(self, event):
        self.logger.info("ModeManager: Entering 'systemupdate' mode.")
        self.stop_all_screens()
        if self.system_update_menu:
            self.system_update_menu.start_mode()
            self.logger.info("ModeManager: SystemUpdateMenu started.")
        else:
            self.logger.warning("ModeManager: No system_update_menu set.")
        self.reset_idle_timer()
        self.start_menu_inactivity_timer()
        self.update_current_mode()

    def enter_menu(self, event):
        self.logger.info("ModeManager: Entering 'menu' state.")
        self.stop_all_screens()
        if self.menu_manager:
            self.menu_manager.start_mode()
            self.logger.info("ModeManager: MenuManager started.")
        else:
            self.logger.warning("ModeManager: No menu_manager set.")
        self.reset_idle_timer()
        self.start_menu_inactivity_timer()
        self.update_current_mode()

    # --- Other Managers ---

    def enter_streaming(self, event):
        self.logger.info("ModeManager: Entering 'streaming' state.")
        self.stop_all_screens()

        # Log and normalise inputs
        self.logger.debug(f"enter_streaming kwargs: {getattr(event, 'kwargs', {})}")
        service_name = (event.kwargs.get('service_name') or 'streaming').lower()
        start_uri    = event.kwargs.get('start_uri') or f"{service_name}://"

        # If we’re re-entering streaming, clean up the old instance
        try:
            if getattr(self, "streaming_manager", None):
                self.streaming_manager.stop_mode()
        except Exception:
            self.logger.exception("Stopping previous StreamingManager failed (safe to ignore)")

        # Spin up the manager
        self.streaming_manager = StreamingManager(
            self.display_manager,
            self.volumio_listener,
            self,
            service_name=service_name,
            root_uri=start_uri
        )

        self.streaming_manager.start_mode()
        self.logger.info(f"ModeManager: StreamingManager started for {service_name} (uri={start_uri}).")

        self.reset_idle_timer()
        self.update_current_mode()


    def enter_library(self, event):
        self.logger.info("ModeManager: Entering 'library' state.")
        self.stop_all_screens()
        if self.library_manager:
            self.library_manager.start_mode()
            self.logger.info("ModeManager: LibraryManager started.")
        else:
            self.logger.warning("ModeManager: No library_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_radio(self, event):
        self.logger.info("ModeManager: Entering 'radio' state.")
        self.stop_all_screens()
        if self.radio_manager:
            self.radio_manager.start_mode()
            self.logger.info("ModeManager: RadioManager started.")
        else:
            self.logger.warning("ModeManager: No radio_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_webradio(self, event):
        self.logger.info("ModeManager: Entering 'webradio' state.")
        self.stop_all_screens()
        if self.webradio_screen:
            self.webradio_screen.start_mode()
            self.logger.info("ModeManager: WebRadioScreen started.")
        else:
            self.logger.warning("ModeManager: No webradio_screen set.")
        self.update_current_mode()
        self.cancel_menu_inactivity_timer()  # No timeout on clock

    def enter_playlists(self, event):
        self.logger.info("ModeManager: Entering 'playlist' state.")
        self.stop_all_screens()
        if self.library_manager:
            self.library_manager.start_mode(start_uri="playlists")
            self.logger.info("ModeManager: LibraryManager started for Playlists.")
        else:
            self.logger.warning("ModeManager: No library_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_albums(self, event):
        self.logger.info("ModeManager: Entering 'albums' state.")
        self.stop_all_screens()
        if self.library_manager:
            self.library_manager.start_mode(start_uri="albums://")
            self.logger.info("ModeManager: LibraryManager started for Albums.")
        else:
            self.logger.warning("ModeManager: No library_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_genres(self, event):
        self.logger.info("ModeManager: Entering 'genres' state.")
        self.stop_all_screens()
        if self.library_manager:
            self.library_manager.start_mode(start_uri="genres://")
            self.logger.info("ModeManager: LibraryManager started for Genres.")
        else:
            self.logger.warning("ModeManager: No library_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_artists(self, event):
        self.logger.info("ModeManager: Entering 'artists' state.")
        self.stop_all_screens()
        if self.library_manager:
            self.library_manager.start_mode(start_uri="artists://")
            self.logger.info("ModeManager: LibraryManager started for Artist.")
        else:
            self.logger.warning("ModeManager: No library_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_favourites(self, event):
        self.logger.info("ModeManager: Entering 'favourites' state.")
        self.stop_all_screens()
        if self.library_manager:
            self.library_manager.start_mode(start_uri="favourites")
            self.logger.info("ModeManager: LibraryManager started for favourites.")
        else:
            self.logger.warning("ModeManager: No library_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_last100(self, event):
        self.logger.info("ModeManager: Entering 'last100' state.")
        self.stop_all_screens()
        if self.library_manager:
            self.library_manager.start_mode(start_uri="Last_100")
            self.logger.info("ModeManager: LibraryManager started for Last 100.")
        else:
            self.logger.warning("ModeManager: No library_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_mediaservers(self, event):
        self.logger.info("ModeManager: Entering 'media servers' state.")
        self.stop_all_screens()
        if self.library_manager:
            self.library_manager.start_mode(start_uri="upnp")
            self.logger.info("ModeManager: LibraryManager started for Media Servers.")
        else:
            self.logger.warning("ModeManager: No library_manager set.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_radioparadise(self, event):
        self.logger.info("ModeManager: Entering 'radioparadise' state.")
        self.stop_all_screens()
        self.streaming_manager = StreamingManager(
            self.display_manager,
            self.volumio_listener,
            self,
            service_name='radioparadise',
            root_uri='rparadise',
            loading_timeout_s=15  # RP can be slow
        )
        self.streaming_manager.start_mode()
        self.logger.info("ModeManager: StreamingManager started for Radio Paradise.")
        self.reset_idle_timer()
        self.update_current_mode()

    def enter_motherearthradio(self, event):
        self.logger.info("ModeManager: Entering 'motherearthradio' state.")
        self.stop_all_screens()

        # Clean up any previous streaming manager
        try:
            if getattr(self, "streaming_manager", None):
                self.streaming_manager.stop_mode()
        except Exception:
            self.logger.exception("Stopping previous StreamingManager failed (safe to ignore)")

        # Mother Earth Radio root is 'mer'
        self.streaming_manager = StreamingManager(
            self.display_manager,
            self.volumio_listener,
            self,
            service_name="motherearthradio",
            root_uri="mer",
        )
        self.streaming_manager.start_mode()
        self.logger.info("ModeManager: StreamingManager started for Mother Earth Radio (uri=mer).")

        self.reset_idle_timer()
        self.update_current_mode()

    def to_airplay(self, *args, **kwargs):
        if self.config.get("ignore_airplay", True):
            self.logger.info("AirPlay transitions are disabled (ignore_airplay=True) — staying on clock.")
            if self.get_mode() != "clock":
                self.to_clock()
            return
        self.logger.info("ModeManager: Switching to AirPlay mode.")
        self.machine.set_state("airplay")
        self.current_screen = self.airplay_screen
        if self.airplay_screen:
            self.airplay_screen.start_mode()

    # --- Playback / Volumio State Handling ---
    def process_state_change(self, sender, state, **kwargs):
        with self.lock:
            if self.suppress_state_changes:
                self.logger.debug("ModeManager: State changes suppressed.")
                return
            self.logger.debug(f"ModeManager: process_state_change => {state}")
            status = state.get('status', '').lower()
            service = state.get('service', '').lower()
            self.previous_status = self.current_status
            self.current_status = status

            # Only run _handle_track_change for genuine track changes
            if self.previous_status == "play" and self.current_status == "stop":
                self._handle_track_change()

            # On first state handoff, skip pause/stop timer logic
            if getattr(self, "first_state_handoff", False):
                self.logger.debug("ModeManager: Skipping pause/stop timer after initial handoff.")
                self.first_state_handoff = False
                # Still update screen/mode as normal
                self._handle_playback_states(status, service, state, skip_pause_stop_timer=True)
            else:
                self._handle_playback_states(status, service, state)

            self.logger.debug("ModeManager: Completed process_state_change.")



    def _handle_track_change(self):
        self.is_track_changing = True
        self.track_change_in_progress = True
        if not self.pause_stop_timer:
            self.pause_stop_timer = threading.Timer(
                self.pause_stop_delay,
                self.switch_to_clock_if_still_stopped_or_paused
            )
            self.pause_stop_timer.start()
            self.logger.debug("ModeManager: Started stop verification timer.")

    def _handle_playback_states(self, status, service, state_data, skip_pause_stop_timer=False):
        now = time.time()
        desired_mode = self.config.get("display_mode", "original")

        # Skip rapid mode switches
        if (now - self.last_mode_change_time) < self.min_mode_switch_interval:
            self.logger.debug("ModeManager: Skipping a rapid mode switch due to cooldown.")
            return

        # For AirPlay, simply ignore state changes so we remain in clock mode.
        if service in ["airplay", "airplay_emulation"]:
            self.logger.debug("AirPlay service detected; ignoring state update and remaining in clock mode.")
            return

        # Normal handling for non-AirPlay services:
        if status == "play":
            current_mode = self.get_mode()
            if service in ["webradio"]:
                if current_mode != "webradio":
                    self.to_webradio()
                    self.last_mode_change_time = now
                else:
                    self.logger.debug("Already in 'webradio' mode; no transition needed.")
            else:
                # Only one display mode should be activated
                if desired_mode == "modern":
                    if current_mode != "modern":
                        self.to_modern()
                        self.last_mode_change_time = now
                    else:
                        self.logger.debug("Already in 'modern' mode; no transition needed.")
                elif desired_mode == "minimal":
                    if current_mode != "minimal":
                        self.to_minimal()
                        self.last_mode_change_time = now
                    else:
                        self.logger.debug("Already in 'minimal' mode; no transition needed.")
                elif desired_mode == "vuscreen":
                    if current_mode != "vuscreen":
                        self.to_vuscreen()
                        self.last_mode_change_time = now
                    else:
                        self.logger.debug("Already in 'vuscreen' mode; no transition needed.")
                elif desired_mode == "digitalvuscreen":
                    if current_mode != "digitalvuscreen":
                        self.to_digitalvuscreen()
                        self.last_mode_change_time = now
                    else:
                        self.logger.debug("Already in 'digitalvuscreen' mode; no transition needed.")
                else:
                    # Default to original
                    if current_mode != "original":
                        self.to_original()
                        self.last_mode_change_time = now
                    else:
                        self.logger.debug("Already in 'original' mode; no transition needed.")

            self.reset_idle_timer()
        elif status == "pause":
            if not skip_pause_stop_timer:
                self._start_pause_timer()


    def _start_pause_timer(self):
        if not self.pause_stop_timer:
            self.pause_stop_timer = threading.Timer(
                self.pause_stop_delay,
                self.switch_to_clock_if_still_stopped_or_paused
            )
            self.pause_stop_timer.start()
            self.logger.debug("ModeManager: Started pause/stop timer.")
        else:
            self.logger.debug("ModeManager: Pause/stop timer already running.")

    def _cancel_pause_timer(self):
        if self.pause_stop_timer:
            self.pause_stop_timer.cancel()
            self.pause_stop_timer = None
            self.logger.debug("ModeManager: Canceled pause/stop timer.")

    def switch_to_clock_if_still_stopped_or_paused(self):
        with self.lock:
            if self.current_status in ["pause", "stop"]:
                self.to_clock()
                self.logger.debug("ModeManager: Reverted to clock after pause/stop timer.")
            else:
                self.logger.debug("Playback resumed or changed; staying in current mode.")
            self.pause_stop_timer = None

    def update_current_mode(self):
        try:
            with open("/tmp/quadify_mode", "w") as f:
                f.write(self.get_mode())
        except Exception as e:
            self.logger.error(f"Failed to update mode file: {e}")

    def toggle_play_pause(self):
        current_mode = self.get_mode()
        self.logger.debug("toggle_play_pause: Current mode before toggling: %s", current_mode)
        if current_mode in ['clock', 'original', 'modern', 'minimal', 'webradio', 'airplay', 'vuscreen', 'digitalvuscreen']:
            if current_mode == 'clock':
                # Now that Clock implements toggle_play_pause, use it directly.
                if hasattr(self.clock, "toggle_play_pause"):
                    self.clock.toggle_play_pause()
                else:
                    self.logger.warning("Clock mode does not support toggling play/pause.")
            elif current_mode == 'original' and self.original_screen:
                self.original_screen.toggle_play_pause()
            elif current_mode == 'modern' and self.modern_screen:
                self.modern_screen.toggle_play_pause()
            elif current_mode == 'minimal' and self.minimal_screen:
                self.minimal_screen.toggle_play_pause()
            elif current_mode == 'vuscreen' and self.vu_screen:
                self.vu_screen.toggle_play_pause()
            elif current_mode == 'digitalvuscreen' and self.digitalvu_screen:
                self.digitalvu_screen.toggle_play_pause()
            elif current_mode == 'webradio' and self.webradio_screen:
                self.webradio_screen.toggle_play_pause()
            elif current_mode == 'airplay' and self.webradio_screen:
                self.airplay_screen.toggle_play_pause()
            else:
                self.logger.warning(f"No screen available to toggle play/pause in mode: {current_mode}")
        else:
            self.logger.info("Toggle play/pause is not applicable in the current mode.")
        self.logger.debug("toggle_play_pause: Current mode after toggling: %s", self.get_mode())

    def back(self):
        current_mode = self.get_mode()

        if current_mode in ["library", "configmenu", "playlists", "webradio",
                            "motherearthradio", "radioparadise", "albums",
                            "artists", "genres", "favourites", "last100", "mediaservers", "streaming"]:
            # Any sub-menu -> go to main menu
            self.to_menu()

        elif current_mode == "menu":
            # In main menu -> go to clock
            self.to_clock()

        elif current_mode == "clock":
            # Already at clock -> do nothing (or log)
            self.logger.info("Back pressed in clock mode; staying on clock.")

        else:
            # Fallback: always go to menu
            self.to_menu()

    def get_mode(self):
        return self.state
        
        
