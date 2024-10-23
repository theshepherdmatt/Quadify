const APOled = require('./oled');
const fonts = require('./fonts');

const REFRESH_TRACK = 20;
let api_state_waiting = false;
let extn_exit_sleep_mode = false;

class APOledController {
    constructor(opts, timeBeforeClock, timeBeforeScreensaver, timeBeforeDeepSleep) {
        this.opts = opts;
        this.TIME_BEFORE_CLOCK = timeBeforeClock;
        this.TIME_BEFORE_SCREENSAVER = timeBeforeScreensaver;
        this.TIME_BEFORE_DEEPSLEEP = timeBeforeDeepSleep;
        this.scroller_x = 0;
        this.streamerData = {};
        this.ip = null;
        this.height = opts.height;
        this.width = opts.width;
        this.page = null;
        this.data = {
            title: null,
            artist: null,
            album: null,
            volume: null,
            samplerate: null,
            bitdepth: null,
            bitrate: null,
            seek: null,
            duration: null
        };
        this.raw_seek_value = 0;
        this.footertext = "";
        this.update_interval = null;
        this.refresh_track = REFRESH_TRACK;
        this.refresh_action = null;
        this.driver = new APOled(opts);
        this.dimmed = false;
        this.pause_to_clock_timeout = null;
        this.currentMode = 'clock'; // Define currentMode as a property of the class
    }

    // Import methods for different modes
    clock_mode = require('./modes/clock');
    playback_mode = require('./modes/playback');
    screensaver_mode = require('./modes/screensaver');

    volumio_seek_format(seek, duration) {
        let ratiobar = 0;
        try {
            if (duration) ratiobar = (seek / (duration * 1000) * (this.width - 6));
        } catch (e) { ratiobar = 0; }

        let seek_string = "00:00 / 00:00";
        try { duration = new Date(duration * 1000).toISOString().substr(14, 5); } catch (e) { duration = "00:00"; }
        try { seek = new Date(seek).toISOString().substr(14, 5); } catch (e) { seek = "00:00"; }

        seek_string = seek + " / " + duration;
        return { seek_string, ratiobar };
    }

    listen_to(api, frequency) {
        frequency = frequency || 1000;

        console.log(`Listening to ${api} with frequency ${frequency}ms`);

        if (api === "volumio") {
            const io = require('socket.io-client');
            const socket = io.connect('http://localhost:3000');

            setInterval(() => {
                if (api_state_waiting) return;
                api_state_waiting = true;
                socket.emit("getState");
            }, frequency);
            let first = true;

            socket.emit("getState"); // Initial state request
            socket.on("pushState", (data) => {
                let exit_sleep = false;
                if (extn_exit_sleep_mode) {
                    extn_exit_sleep_mode = false;
                    exit_sleep = true;
                }
                if (first) {
                    first = false;
                    socket.emit("getState");
                    return;
                }
                api_state_waiting = false;

                if (data.status === "play" && this.currentMode !== "playback") {
                    this.playback_mode(); // Switch to playback mode when playback starts
                    this.currentMode = "playback";
                } else if (data.status !== "play" && this.currentMode !== "clock" && this.currentMode !== "playlist") {
                    this.currentMode = "clock";
                    if (this.page !== "clock") {
                        // Delay before switching to clock mode
                        if (!this.pause_to_clock_timeout) {
                            this.pause_to_clock_timeout = setTimeout(() => {
                                if (this.data.status !== "play" && this.currentMode !== "playlist") {
                                    this.clock_mode(); // Switch to clock mode
                                    this.currentMode = "clock";
                                    this.pause_to_clock_timeout = null;
                                }
                            }, 60000); // Delay for 1 minute
                        }
                    }
                }

                if (this.data.title !== data.title ||
                    this.data.artist !== data.artist ||
                    this.data.album !== data.album) {
                    this.text_to_display = data.title + (data.artist ? " - " + data.artist : "");
                    this.driver.CacheGlyphsData(this.text_to_display);
                    this.text_width = this.driver.getStringWidthUnifont(this.text_to_display + " - ");
                    this.scroller_x = 0;
                    this.refresh_track = REFRESH_TRACK;
                    this.footertext = "";
                    exit_sleep = true;
                }

                if (this.data.volume !== data.volume) {
                    exit_sleep = true;
                }

                let seek_data = this.volumio_seek_format(data.seek, data.duration);

                if (data.status !== "play" && this.raw_seek_value !== data.seek) {
                    exit_sleep = true;
                }
                this.raw_seek_value = data.seek;

                if (data.status === "play") {
                    exit_sleep = true;
                }

                this.footertext = "";
                if (!data.samplerate && !data.bitdepth && !data.bitrate) {
                    socket.emit("getQueue");
                } else {
                    if (data.samplerate) this.footertext += data.samplerate.toString().replace(/\s/gi, "") + " ";
                    if (data.bitdepth) this.footertext += data.bitdepth.toString().replace(/\s/gi, "") + " ";
                    if (data.bitrate) this.footertext += data.bitrate.toString().replace(/\s/gi, "") + " ";
                }

                this.data = data; // Updating internal state
                this.data.seek_string = seek_data.seek_string;
                this.data.ratiobar = seek_data.ratiobar;

                this.handle_sleep(exit_sleep);
            });

            socket.on("pushQueue", (resdata) => {
                let data = resdata[0];
                if (!this.footertext && data) {
                    if (data.samplerate) this.footertext += data.samplerate.toString().replace(/\s/gi, "") + " ";
                    if (data.bitdepth) this.footertext += data.bitdepth.toString().replace(/\s/gi, "") + " ";
                    if (data.bitrate) this.footertext += data.bitrate.toString().replace(/\s/gi, "") + " ";
                }
            });
        }
    }

    forceMode(newMode) {
        console.log(`Forcing mode change to: ${newMode}`);
        
        // Clear any active interval to stop ongoing display updates
        if (this.update_interval) {
            clearInterval(this.update_interval);
            this.update_interval = null;
        }
    
        // Update the current mode and execute the relevant actions
        this.currentMode = newMode;
    
        switch (newMode) {
            case "playlist":
                if (this.playlistManager) {
                    this.playlistManager.startPlaylistMode();
                } else {
                    console.error("PlaylistManager not defined.");
                }
                break;
            case "clock":
                this.clock_mode();
                break;
            case "playback":
                this.playback_mode();
                break;
            default:
                console.log("Unknown mode set.");
        }
    }   
    
    
    handle_sleep(exit_sleep) {
        if (this.currentMode === "playlist") {
            // Never sleep during playlist mode
            return;
        }
    
        if (!exit_sleep) {
            if (!this.iddle_timeout) {
                let _deepsleep_ = () => { this.deep_sleep(); }
                let _screensaver_ = () => {
                    if (this.currentMode !== "playlist") { // Don't activate screensaver if in Playlist Mode
                        this.screensaver_mode();
                        this.iddle_timeout = setTimeout(_deepsleep_, this.TIME_BEFORE_DEEPSLEEP);
                    }
                }
                let _clock_ = () => {
                    if (this.currentMode !== "playlist" && this.currentMode !== "playback") { // Don't switch to clock if in Playlist or Playback Mode
                        this.clock_mode();
                    }
                    this.iddle_timeout = setTimeout(_screensaver_, this.TIME_BEFORE_SCREENSAVER);
                }
                this.iddle_timeout = setTimeout(_clock_, this.TIME_BEFORE_CLOCK);
            }
        } else {
            if (this.status_off) {
                this.status_off = null;
                this.driver.turnOnDisplay();
            }
    
            if (this.page !== "playback" && this.currentMode === "playback") {
                this.playback_mode();
            }
    
            if (this.iddle_timeout) {
                clearTimeout(this.iddle_timeout);
                this.iddle_timeout = null;
            }
    
            if (this.data.status === "pause" && this.currentMode !== "playlist") {
                // Set a timeout to switch to clock mode after a minute if still paused
                if (!this.pause_to_clock_timeout) {
                    this.pause_to_clock_timeout = setTimeout(() => {
                        if (this.data.status === "pause" && this.currentMode !== "playlist") {
                            this.clock_mode();
                            this.currentMode = "clock";
                        }
                        this.pause_to_clock_timeout = null;
                    }, 60000); // 1 minute
                }
            } else if (this.data.status === "play" || this.data.status === "stop") {
                // Clear the pause to clock timeout if the status changes
                if (this.pause_to_clock_timeout) {
                    clearTimeout(this.pause_to_clock_timeout);
                    this.pause_to_clock_timeout = null;
                }
            }
        }
    }      
}

module.exports = APOledController;
