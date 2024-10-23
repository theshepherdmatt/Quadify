#!/bin/sh

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Log file for detailed installation messages
LOG_FILE="install_details.log"

# Function to log messages
log_message() {
    local message=$1
    echo -e "$message" | tee -a $LOG_FILE
}

# Function to install Node.js and npm with an audiophile twist
install_node_and_npm() {
    log_message "${YELLOW}Tuning in to Node.js and npm frequencies...${NC}"
    if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
        log_message "${GREEN}Node.js and npm are already in harmony.${NC}"
    else
        log_message "${YELLOW}Node.js or npm not found. Setting up the system...${NC}"
        sudo apt-get update
        sudo apt-get install -y nodejs npm
        # Encore: Check again after installation
        if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
            log_message "${GREEN}Node.js and npm have tuned in perfectly.${NC}"
            log_message "${YELLOW}Initializing package setup...${NC}"
            npm init -y
        else
            log_message "${RED}Encore failed. Node.js and npm are out of tune. Check your package manager or install manually.${NC}"
            exit 1
        fi
    fi
}

# Function to install dependencies for Volumio with a touch of audiophile elegance
install_dep_volumio() {
    if apt-get -qq install build-essential > /dev/null 2>&1; then
        log_message "${GREEN}Essential building blocks are in place, like a solid music collection.${NC}"
    else
        log_message "${YELLOW}Missing some tunes in your collection, attempting a rare find workaround...${NC}"
        if bash Workaround_BuildEssentials.sh > /dev/null 2>> $LOG_FILE; then
            log_message "${GREEN}...Success! Your Dac is almost complete.${NC}"
        else
            log_message "${RED}...No luck, the tunes remain elusive. The OLED display can't be installed without it.${NC}"
            exit 1
        fi
    fi
}

# Function to create and enable the startup indicator service
setup_startup_indicator_service() {
    log_message "${YELLOW}Setting up the Startup Indicator LED Service...${NC}"
    # Create the systemd service file
    sudo tee /etc/systemd/system/startup-indicator.service > /dev/null <<EOL
[Unit]
Description=Startup Indicator LED Service
After=network.target

[Service]
ExecStart=/usr/bin/node /home/volumio/Quadify/oled/startupindicator.js
Restart=no
User=volumio
Environment=PATH=/usr/bin:/usr/local/bin
Environment=NODE_ENV=production
WorkingDirectory=/home/volumio/Quadify/oled/
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOL

    # Reload systemd to apply the new service
    sudo systemctl daemon-reload

    # Enable the service to start on boot
    sudo systemctl enable startup-indicator.service

    # Start the service
    sudo systemctl start startup-indicator.service

    log_message "${GREEN}Startup Indicator LED Service has been created, enabled, and started.${NC}"
}

# -------------------------------------------------------------------
# Function to install the remote script
# Commented out to remove remote installation
# -------------------------------------------------------------------
# install_remote_script() {
#     log_message "${YELLOW}Running the remote install script...${NC}"
#     if [ -f "$(pwd)/../remote/install.sh" ]; then
#         (cd ../remote && bash install.sh >> $LOG_FILE 2>> $LOG_FILE)
#         log_message "${GREEN}Remote install script executed successfully.${NC}"
#     else
#         log_message "${RED}Remote install script not found!${NC}"
#         exit 1
#     fi
# }

# Start the installation with a bit of flair
log_message "${GREEN}Quadify's audiophile installation is tuning up...${NC}"
install_node_and_npm

# Installation steps for Volumio
start_time="$(date +"%T")"
log_message "* Setting up the stage for Quadify OLED on Volumio"
install_dep_volumio
npm install async i2c-bus pi-spi onoff date-and-time socket.io-client@2.1.1 spi-device >> $LOG_FILE 2>> $LOG_FILE

# Setting up the stage for SPI interfacing, like fine-tuning your turntable
echo "spi-dev" | sudo tee -a /etc/modules > /dev/null
echo "dtparam=spi=on" | sudo tee -a /boot/userconfig.txt > /dev/null

# Check for SPI buffer size like checking for the right pressure on your vinyl
if [ ! -f "/etc/modprobe.d/spidev.conf" ] || ! grep -q 'bufsiz=8192' /etc/modprobe.d/spidev.conf; then
    echo "options spidev bufsiz=8192" | sudo tee -a /etc/modprobe.d/spidev.conf > /dev/null
fi

# Setting up the OLED service, like setting up your amplifier
printf "[Unit]\nDescription=Quadify OLED Display Service\nAfter=volumio.service\n[Service]\nWorkingDirectory=%s\nExecStart=/usr/bin/node %s/index.js\nExecStop=/usr/bin/node %s/off.js\nStandardOutput=null\nType=simple\nUser=volumio\n[Install]\nWantedBy=multi-user.target" "$PWD" "$PWD" "$PWD" | sudo tee /etc/systemd/system/oled.service > /dev/null
sudo systemctl enable oled > /dev/null 2>> $LOG_FILE

# Restart the OLED service, like dropping the needle on a fresh record
sudo systemctl restart oled

# Set up the Startup Indicator LED Service
setup_startup_indicator_service

# -------------------------------------------------------------------
# Install the remote script
# Commented out to remove remote installation
# -------------------------------------------------------------------
# install_remote_script

log_message "${GREEN}The Quadify Dac is set, Happy Listening!!${NC}"

log_message "Installation began at $start_time and concluded at $(date +"%T"). Enjoy the music!"
