// playlistManager.js

const io = require('socket.io-client');
const fonts = require('./fonts.js');  // Assuming you have appropriate fonts for the OLED display

class PlaylistManager {
    constructor(oled) {
        this.oled = oled;

        this.playlists = [];
        this.currentSelection = 0;
        this.isInPlaylistMode = false;
        this.isPlaying = false;

        // Initialize WebSocket connection to Volumio
        this.socket = io.connect('http://localhost:3000');

        // WebSocket event listeners
        this.socket.on('connect', () => {
            console.log('WebSocket connected to Volumio');
        });

        this.socket.on('disconnect', (reason) => {
            console.warn('WebSocket disconnected:', reason);
        });

        this.socket.on('connect_error', (error) => {
            console.error('WebSocket connection error:', error);
        });

        // Event listener to handle playlist responses
        this.socket.on('pushBrowseLibrary', (data) => {
            console.log('Received library data:', data);
            this.handleBrowseLibraryData(data);
        });

        console.log('PlaylistManager initialized.');
    }

    async startPlaylistMode() {
        this.isInPlaylistMode = true;
        console.log('Entering Playlist Mode...');
        
        // Stop any ongoing clock or playback intervals to avoid conflicts
        if (this.oled.update_interval) {
            clearInterval(this.oled.update_interval);
            this.oled.update_interval = null;
        }
        if (this.oled.pause_to_clock_timeout) {
            clearTimeout(this.oled.pause_to_clock_timeout);
            this.oled.pause_to_clock_timeout = null;
        }
        
        // Override the mode to ensure that the display remains in Playlist Mode
        this.oled.forceMode('playlist');
        this.oled.currentMode = 'playlist'; // Explicitly set the current mode to prevent conflicts
    
        try {
            await this.fetchPlaylists(3);  // Attempt 3 retries if needed
            this.displayPlaylists();
        } catch (error) {
            console.error('Failed to start playlist mode:', error);
            this.isInPlaylistMode = false;
            this.displayError('Failed to start Playlist Mode');
        }
    }
    

    // Method to fetch playlists with retry logic
    async fetchPlaylists(retries = 3) {
        for (let attempt = 1; attempt <= retries; attempt++) {
            try {
                return await this._fetchPlaylists(); // Use the updated _fetchPlaylists logic
            } catch (error) {
                console.error(`Attempt ${attempt} failed: ${error.message}`);
                if (attempt === retries) throw error;  // Only throw if the last retry fails
            }
        }
    }

    // Internal method to fetch playlists via WebSocket
    _fetchPlaylists() {
        return new Promise((resolve, reject) => {
            console.log('Requesting playlists via WebSocket...');
            this.socket.emit('browseLibrary', { uri: 'playlists' });

            const timeout = setTimeout(() => {
                reject(new Error('Timeout while fetching playlists.'));
            }, 5000); // Timeout after 5 seconds

            // Store the timeout and resolve or reject as needed in handleBrowseLibraryData
            this.playlistFetchTimeout = timeout;

            // This will be handled by `handleBrowseLibraryData()`
        });
    }

    // Method to handle the pushBrowseLibrary event and process the playlist data
    handleBrowseLibraryData(data) {
        if (this.playlistFetchTimeout) {
            clearTimeout(this.playlistFetchTimeout);
            this.playlistFetchTimeout = null;
        }

        if (data && data.navigation && data.navigation.lists && data.navigation.lists.length > 0) {
            const playlists = data.navigation.lists[0].items.map(item => ({
                name: item.title,
                uri: item.uri
            }));
            this.playlists = playlists;
            console.log('Playlists fetched successfully:', this.playlists);
            this.displayPlaylists();  // Display playlists on the OLED
        } else {
            console.error('No playlists found.');
            this.displayError('No Playlists Found');
        }
    }

    // Method to display playlists on the OLED screen
    displayPlaylists() {
        console.log('Displaying playlists on OLED...');
        if (this.playlists.length === 0) {
            console.log('No playlists to display.');
            this.displayError('No Playlists Found');
            return;
        }

        const itemHeight = 12;  // Adjusted height to fit more items
        const maxVisibleItems = Math.floor(this.oled.height / itemHeight);
        const startIndex = Math.max(0, this.currentSelection - Math.floor(maxVisibleItems / 2));
        const endIndex = Math.min(this.playlists.length, startIndex + maxVisibleItems);

        if (typeof this.oled.driver.fullRAMclear === 'function') {
            this.oled.driver.fullRAMclear(() => {
                this.renderPlaylists(startIndex, endIndex, itemHeight);
            });
        } else {
            console.error('No method available to clear the display.');
        }
    }

    // Method to render playlists on the OLED screen
    renderPlaylists = (startIndex, endIndex, itemHeight) => {
        for (let i = startIndex; i < endIndex; i++) {
            const y = (i - startIndex) * itemHeight;
            const playlist = this.playlists[i];
    
            if (i === this.currentSelection) {
                // Draw an arrow next to the highlighted item
                this.oled.driver.setCursor(0, y + 2);
                this.oled.driver.writeString(fonts.monospace, 1, '>', 255); // Use '>' as a marker for the selected item
                
                // Write the playlist name next to the marker in white
                this.oled.driver.setCursor(12, y + 2); // Leave space for the arrow marker
                this.oled.driver.writeString(fonts.monospace, 1, playlist.name, 255);
                
                // Optionally, underline the text for further emphasis
                const textWidth = this.oled.driver.getStringWidthUnifont(playlist.name);
                this.oled.driver.drawLine(12, y + itemHeight - 1, 12 + textWidth, y + itemHeight - 1, 255); // Draw underline below text
            } else {
                // Write the playlist name in white on a black background
                this.oled.driver.setCursor(12, y + 2);
                this.oled.driver.writeString(fonts.monospace, 1, playlist.name, 100);
            }
        }
        this.oled.driver.update();
    };          
    
    
    // Method to move selection up or down
    moveSelection(direction) {
        console.log(`Moving playlist selection by ${direction}.`);
        this.currentSelection += direction;
        if (this.currentSelection < 0) this.currentSelection = 0;
        if (this.currentSelection >= this.playlists.length) this.currentSelection = this.playlists.length - 1;
        console.log(`Current playlist index: ${this.currentSelection}`);
        this.displayPlaylists();
    }

    // Method to select and play the current playlist
    playSelectedPlaylist() {
        const selectedPlaylist = this.getSelectedPlaylist();
        if (selectedPlaylist) {
            console.log(`Playing selected playlist: ${selectedPlaylist.name}`);
            this.isInPlaylistMode = false;
            this.isPlaying = true;

            // Emit the playPlaylist command via WebSocket
            this.socket.emit('playPlaylist', { name: selectedPlaylist.name });
        }
    }

    // Method to get the currently selected playlist
    getSelectedPlaylist() {
        return this.playlists[this.currentSelection];
    }

    // Method to display an error message on the OLED
    displayError(message) {
        console.log(`Displaying error message: ${message}`);
        if (typeof this.oled.clearDisplay === 'function') {
            this.oled.clearDisplay();
        } else if (this.oled.driver && typeof this.oled.driver.fullRAMclear === 'function') {
            this.oled.driver.fullRAMclear(() => {
                this.oled.driver.setCursor(0, 0);
                this.oled.driver.writeString(fonts.monospace, 1, message, 1);
                this.oled.driver.update();
            });
        } else {
            console.error('No method available to clear the display.');
        }
    }

    // Method to handle rotary button press for selecting a playlist
    handleButtonPress() {
        console.log('Button Pressed');
        if (!this.isInPlaylistMode) {
            if (!this.isPlaying) {
                this.startPlaylistMode();  // Enter playlist mode if nothing is playing
            } else {
                console.log('Button press ignored while music is playing.');
            }
        } else {
            this.playSelectedPlaylist();  // Play selected playlist
        }
    }

    // Method to scroll through playlists using the rotary encoder
    scrollPlaylists(direction) {
        console.log(`Scrolling playlists: ${direction}`);
        const moveDirection = direction === 'Clockwise' ? 1 : -1;
        this.moveSelection(moveDirection);
    }

    // Method to exit playlist mode and handle cleanup
    exitPlaylistMode() {
        console.log('Exiting Playlist Mode...');
        this.isInPlaylistMode = false;
        if (this.oled.currentMode === 'playlist') {
            if (this.isPlaying) {
                this.oled.forceMode("playback");
            } else {
                this.oled.forceMode("clock");
            }
        }
    }
}

module.exports = PlaylistManager;
