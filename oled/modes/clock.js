// modes/clock_mode.js

const date = require('date-and-time');
const fs = require('fs');
const path = require('path');

// Load unifont.hex file from the oled folder
const unifontFilePath = path.join(__dirname, '../unifont.hex');
const unifontData = fs.readFileSync(unifontFilePath, 'utf8');

// Parse unifont.hex data into a usable map
function parseUnifont(hexData) {
    const fontMap = {};
    const lines = hexData.split('\n');

    lines.forEach(line => {
        if (line.trim() === '' || line.startsWith('#')) return; // Ignore empty lines or comments
        const [code, hexValues] = line.split(':');
        const charCode = parseInt(code, 16);

        // Convert hex string into an array of binary rows
        const rows = [];
        for (let i = 0; i < hexValues.length; i += 2) {
            const hexByte = hexValues.substring(i, i + 2);
            rows.push(parseInt(hexByte, 16));
        }
        fontMap[charCode] = rows;
    });

    return fontMap;
}

const unifontMap = parseUnifont(unifontData);

// Function to draw a scaled character without anti-aliasing
function drawScaledCharWithAA(char, x, y, scale, driver) {
    const charCode = char.charCodeAt(0);
    const charData = unifontMap[charCode];

    if (!charData) return; // If no data for this char, skip it

    charData.forEach((row, rowIndex) => {
        for (let bit = 0; bit < 8; bit++) {
            if (row & (1 << (7 - bit))) {
                // Draw the primary pixel
                for (let dy = 0; dy < scale; dy++) {
                    for (let dx = 0; dx < scale; dx++) {
                        driver.drawPixel(x + bit * scale + dx, y + rowIndex * scale + dy, 150);
                    }
                }

                // Anti-aliasing code removed
            }
        }
    });
}

// Function to draw a string using scaled unifont without anti-aliasing
function drawScaledStringWithAA(string, x, y, scale, driver) {
    for (let i = 0; i < string.length; i++) {
        drawScaledCharWithAA(string[i], x + (i * 8 * scale), y, scale, driver);
    }
}

// Function to calculate the total width and height of a string with scaling
function getStringDimensions(string, scale) {
    const width = string.length * 8 * scale; // Each character is 8 pixels wide
    const height = 16 * scale; // Height of unifont is typically 16 pixels
    return { width, height };
}

module.exports = function clock_mode() {
    if (this.page === "clock") return;
    clearInterval(this.update_interval);
    this.page = "clock";

    this.refresh_action = () => {
        this.driver.buffer.fill(0x00); // Clear the display buffer
        const ftime = date.format(new Date(), 'HH:mm');

        // Define the scale factor
        const scale = 3;

        // Calculate the dimensions of the scaled string
        const { width, height } = getStringDimensions(ftime, scale);

        // Calculate the top-left corner to center the string
        const screenWidth = this.driver.WIDTH;  // Screen width (256 in your case)
        const screenHeight = this.driver.HEIGHT;  // Screen height (64 in your case)
        
        const startX = Math.floor((screenWidth - width) / 2); // Center horizontally

        // Shift up the Y-axis by 10 pixels (adjust this value as needed)
        const shiftUp = 10;
        const startY = Math.floor((screenHeight - height) / 2) - shiftUp;

        // Draw the scaled and centered time string without anti-aliasing
        drawScaledStringWithAA(ftime, startX, startY, scale, this.driver);

        this.driver.update(true); // Update the display to show the new frame
    }

    this.refresh_action();
    this.update_interval = setInterval(() => { this.refresh_action() }, 1000);
}
