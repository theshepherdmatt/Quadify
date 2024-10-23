// rotary.js

const { Gpio } = require('onoff');
const { exec } = require('child_process');
const queue = require('async/queue');
const io = require('socket.io-client');
const PlaylistManager = require('./playlistManager');

module.exports = function(oled) {
    console.log('Rotary script initialized with OLED instance.');

    // Initialize PlaylistManager with the OLED instance
    const playlistManager = new PlaylistManager(oled);

    // GPIO setup
    const clk = new Gpio(13, 'in', 'both');
    const dt = new Gpio(5, 'in', 'both');
    const sw = new Gpio(6, 'in', 'falling', { debounceTimeout: 100 }); // Increased debounceTimeout to 100 ms

    let clkLastState = clk.readSync();
    const stepsPerAction = 1; // Adjust based on desired sensitivity

    // Command execution queue
    const execQueue = queue((task, completed) => {
        exec(task.command, (error, stdout, stderr) => {
            if (error) console.error(`exec error: ${error}`);
            if (stdout) console.log(`stdout: ${stdout}`);
            if (stderr) console.error(`stderr: ${stderr}`);
            completed();
        });
    }, 1);

    // State variables
    let isInPlaylistMode = false;
    let isPlaying = false;

    // Connect to Volumio's WebSocket API
    const socket = io.connect('http://localhost:3000');

    // Monitor playback status
    socket.on('connect', () => {
        console.log('Connected to Volumio WebSocket API.');
        socket.emit('getState');
    });

    socket.on('pushState', (data) => {
        isPlaying = (data.status === 'play');
        console.log(`Playback status: ${data.status}`);
    });

    socket.on('disconnect', () => {
        console.log('Disconnected from Volumio WebSocket API.');
    });

    // Function to handle rotation events
    const handleRotation = () => {
        const clkState = clk.readSync();
        const dtState = dt.readSync();

        if (clkState !== clkLastState) {
            const direction = clkState !== dtState ? 'Clockwise' : 'Counter-Clockwise';

            if (isInPlaylistMode) {
                console.log(`Scrolling playlists: ${direction}`);
                playlistManager.scrollPlaylists(direction);
            } else if (isPlaying) {
                const command = direction === 'Clockwise' ? 'volumio volume plus' : 'volumio volume minus';
                console.log(`${direction}: Adjusting volume`);
                execQueue.push({ command });
            } else {
                console.log(`${direction}: No action taken`);
            }
        }
        clkLastState = clkState;
    };

    // Function to handle button press events
    const handleButtonPress = () => {
        console.log('Button Pressed');
        if (!isInPlaylistMode) {
            if (!isPlaying) {
                isInPlaylistMode = true;
                console.log('Entering Playlist Mode...');
                playlistManager.startPlaylistMode().then(() => {
                    oled.forceMode("playlist"); // Explicitly set the OLED mode to playlist
                    console.log('Playlist Mode active.');
                }).catch((error) => {
                    console.error('Failed to enter Playlist Mode:', error);
                    isInPlaylistMode = false;
                });
            } else {
                console.log('Button press ignored while music is playing.');
            }
        } else {
            console.log('Selecting and playing the chosen playlist...');
            playlistManager.playSelectedPlaylist(); // Use the correct function name
            isInPlaylistMode = false;
            playlistManager.exitPlaylistMode(); // Now this function actually exists to handle cleanup
        }
    };   
    

    // Event watchers setup
    console.log('Setting up GPIO event listeners.');

    clk.watch((err) => {
        if (err) {
            console.error('Error', err);
            return;
        }
        handleRotation();
    });

    // Handle button press event properly
    sw.watch((err, value) => {
        if (err) {
            console.error('Error', err);
            return;
        }
        if (value === 0) { // Handle only the falling edge (button pressed)
            handleButtonPress();
        }
    });

    // Keep the script running
    setInterval(() => {}, 1000);

    // Clean up GPIO on exit
    process.on('SIGINT', () => {
        clk.unexport();
        dt.unexport();
        sw.unexport();
        process.exit();
    });

    process.on('SIGTERM', () => {
        clk.unexport();
        dt.unexport();
        sw.unexport();
        process.exit();
    });
};
