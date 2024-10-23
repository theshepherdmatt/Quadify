const { checkVolumioStatus } = require('./volumiostatus');
const { runButtonsLedsScript, runRotaryScript } = require('./utils'); // Add runRotaryScript import
const APOled = require('./oledcontroller');

const TIME_BEFORE_CLOCK = 6000; // in ms
const TIME_BEFORE_SCREENSAVER = 600000; // in ms
const TIME_BEFORE_DEEPSLEEP = 600000; // in ms
const LOGO_DURATION = 5000; // in ms
const CONTRAST = 254; // range 1-254

const opts = {
    width: 256,
    height: 64,
    dcPin: 24,
    rstPin: 25,
    contrast: CONTRAST,
    device: "/dev/spidev0.0",
    divisor: 0xf1,
    main_rate: 40
};

var DRIVER;
var extn_exit_sleep_mode = false;
this.currentMode = 'clock'; // Define as a property of the class

const OLED = new APOled(opts, TIME_BEFORE_CLOCK, TIME_BEFORE_SCREENSAVER, TIME_BEFORE_DEEPSLEEP);

// Run both buttonsleds.js and rotary.js on startup
console.log("Starting scripts...");
runButtonsLedsScript(); // Start buttons and LEDs script
runRotaryScript(OLED); // Start rotary script


var logo_start_display_time = 0;

OLED.driver.begin(() => {
    DRIVER = OLED;
    OLED.driver.load_and_display_logo((displaylogo) => {
        console.log("logo loaded");
        if (displaylogo) logo_start_display_time = new Date();
    });
    OLED.driver.load_hex_font("unifont.hex", start_app);
});

function start_app() {
    checkVolumioStatus(() => {
        let time_remaining = 0;
        if (logo_start_display_time) {
            time_remaining = LOGO_DURATION - (new Date().getTime() - logo_start_display_time.getTime());
            time_remaining = (time_remaining <= 0) ? 0 : time_remaining;
        }
        setTimeout(() => {
            OLED.driver.fullRAMclear(() => {
                if (OLED.currentMode === 'clock') {
                    OLED.clock_mode();
                }
                if (OLED.currentMode !== 'playlist') {
                    // Only start listening to Volumio if not in playlist mode
                    OLED.listen_to("volumio", 1000);
                }
            });
        }, time_remaining);
    });
}


function exitcatcher(options) {
    if (options.cleanup) OLED.driver.turnOffDisplay();
    if (options.exit) process.exit();
}

process.on('exit', exitcatcher.bind(null, { cleanup: true }));
process.on('SIGINT', exitcatcher.bind(null, { exit: true }));
process.on('SIGUSR1', exitcatcher.bind(null, { exit: true }));
process.on('SIGUSR2', exitcatcher.bind(null, { exit: true }));
