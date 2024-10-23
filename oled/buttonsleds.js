const i2c = require('i2c-bus');
const MCP23017_ADDRESS = 0x20;
const { exec } = require('child_process');

// MCP23017 register definitions
const MCP23017_IODIRA = 0x00;
const MCP23017_IODIRB = 0x01;
const MCP23017_GPIOA = 0x12;
const MCP23017_GPIOB = 0x13;
const MCP23017_GPPUA = 0x0C;
const MCP23017_GPPUB = 0x0D;

const bus = i2c.openSync(1);

function initializeMCP23017() {
    console.log("Configuring MCP23017 I/O expander.");
    bus.writeByteSync(MCP23017_ADDRESS, MCP23017_IODIRB, 0x3C);  // Set GPB2-5 as inputs
    bus.writeByteSync(MCP23017_ADDRESS, MCP23017_GPPUB, 0x3C);   // Enable pull-ups on GPB2-5
    bus.writeByteSync(MCP23017_ADDRESS, MCP23017_IODIRA, 0x00);  // Set GPA0-7 as outputs
    bus.writeByteSync(MCP23017_ADDRESS, MCP23017_GPIOA, 0x00);   // Ensure all LEDs are off initially
}

initializeMCP23017();

const button_map = [[2, 1], [4, 3], [6, 5], [8, 7]]; // Button mappings
let prev_button_state = [[1, 1], [1, 1], [1, 1], [1, 1]];
let led_state = 0;

function control_leds(state) {
    console.log(`Setting LED state to: ${state.toString(2).padStart(8, '0')}`);
    bus.writeByteSync(MCP23017_ADDRESS, MCP23017_GPIOA, state);
    setTimeout(() => {
        const read_back = bus.readByteSync(MCP23017_ADDRESS, MCP23017_GPIOA);
        console.log(`Read back GPIOA state: ${read_back.toString(2).padStart(8, '0')}`);
        if (read_back !== state) {
            console.error(`Failed to set LED state, retrying...`);
            bus.writeByteSync(MCP23017_ADDRESS, MCP23017_GPIOA, state);
            setTimeout(() => {
                const read_back_retry = bus.readByteSync(MCP23017_ADDRESS, MCP23017_GPIOA);
                console.log(`Read back GPIOA state after retry: ${read_back_retry.toString(2).padStart(8, '0')}`);
                if (read_back_retry !== state) {
                    console.error(`Failed to set LED state after retry for state: ${state.toString(2).padStart(8, '0')}`);
                }
            }, 100); // Small delay before retrying
        }
    }, 100); // Small delay before reading back the state
}

function read_button_matrix() {
    const button_matrix_state = [[0, 0], [0, 0], [0, 0], [0, 0]];
    for (let column = 0; column < 2; column++) {
        bus.writeByteSync(MCP23017_ADDRESS, MCP23017_GPIOB, ~(1 << column) & 0x03);
        const row_state = bus.readByteSync(MCP23017_ADDRESS, MCP23017_GPIOB) & 0x3C;
        for (let row = 0; row < 4; row++) {
            button_matrix_state[row][column] = (row_state >> (row + 2)) & 1;
        }
    }
    return button_matrix_state;
}

function executeCommand(command) {
    const cmd = `volumio ${command}`;
    console.log(`Executing: ${cmd}`);
    exec(cmd, (error, stdout, stderr) => {
        if (error) {
            console.error(`Error executing command: ${error.message}`);
            return;
        }
        if (stdout) console.log(stdout);
        if (stderr) console.error(`stderr: ${stderr}`);
    });
}

function restartOLEDService() {
    const cmd = `sudo systemctl restart oled.service`;
    console.log(`Executing: ${cmd}`);
    exec(cmd, (error, stdout, stderr) => {
        if (error) {
            console.error(`Error restarting oled.service: ${error.message}`);
            return;
        }
        if (stdout) console.log(stdout);
        if (stderr) console.error(`stderr: ${stderr}`);
    });
}

function check_buttons_and_update_leds() {
    const button_matrix = read_button_matrix();

    for (let row = 0; row < 4; row++) {
        for (let col = 0; col < 2; col++) {
            const button_id = button_map[row][col];
            const current_button_state = button_matrix[row][col];
            if (current_button_state === 0 && prev_button_state[row][col] !== current_button_state) {
                console.log(`Button ${button_id} pressed`);
                handleButtonPress(button_id);
            }
            prev_button_state[row][col] = current_button_state;
        }
    }

    setTimeout(check_buttons_and_update_leds, 100);
}

function handleButtonPress(button_id) {
    if (button_id === 7) {
        addToFavouritesViaWebSocket();  // Button 7 adds the current track to Favourites
    } else if (button_id === 8) {
        restartOLEDService();  // Button 8 restarts the OLED service
    } else {
        executeCommand(getCommandForButton(button_id));
    }

    // Update LEDs to ensure only the current button's LED is on
    led_state = 1 << (8 - button_id);
    control_leds(led_state);
}


function addToFavouritesViaWebSocket() {
    const socket = require('socket.io-client')('http://volumio.local:3000');  // Adjust the host if needed

    socket.on('connect', function() {
        console.log('Connected to Volumio WebSocket');
        socket.emit('getState');  // Get current state to retrieve track info

        socket.on('pushState', function(data) {
            const trackUri = data.uri;  // Get the currently playing track URI
            if (trackUri) {
                socket.emit('addToFavourites', {
                    service: 'mpd',
                    uri: trackUri
                });
                console.log(`Track added to Favourites: ${trackUri}`);
            } else {
                console.log('No track currently playing');
            }
        });
    });

    socket.on('disconnect', function() {
        console.log('Disconnected from Volumio WebSocket');
    });
}


function getCommandForButton(buttonId) {
    switch (buttonId) {
        case 1: return "play";
        case 2: return "pause";
        case 3: return "previous";
        case 4: return "next";
        case 5: return "repeat";
        case 6: return "random";
        case 7: return "";  // Button 7 is handled separately for playing the Favourites playlist
        case 8: return "";  // Button 8 is handled separately for restarting the OLED service
        default: return "";
    }
}


function updatePlayPauseLEDs() {
    exec("volumio status", (error, stdout, stderr) => {
        if (error) return;

        let currentState = null;
        try {
            currentState = JSON.parse(stdout).status;
        } catch (e) {
            return;
        }

        if (currentState === 'play') {
            led_state = 1 << (1 - 1); // Turn on PLAY_LED, turn off all others
        } else if (currentState === 'pause') {
            led_state = 1 << (2 - 1); // Turn on PAUSE_LED, turn off all others
        }

        control_leds(led_state);
    });
}

function startStatusUpdateLoop() {
    setInterval(updatePlayPauseLEDs, 5000); // Adjust frequency as needed
}

check_buttons_and_update_leds();
startStatusUpdateLoop();
