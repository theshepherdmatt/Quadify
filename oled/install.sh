#!/bin/bash
set -e

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
    echo -e "$message" | tee -a "$LOG_FILE"
}

# Function to check if the script is run as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_message "${YELLOW}Please run as root or use sudo.${NC}"
        exit 1
    fi
}

# Function to install build essentials and set up compilers
install_build_essentials() {
    log_message "${YELLOW}Installing build essentials and setting up compilers...${NC}"
    
    # Run the updated build script
    bash Workaround_BuildEssentials.sh >> "$LOG_FILE" 2>&1
    
    log_message "${GREEN}Build essentials installed and compilers set to gcc-8/g++-8.${NC}"
}

# Function to install Node.js and npm using NodeSource
install_node_and_npm() {
    log_message "${YELLOW}Installing Node.js and npm...${NC}"
    if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
        log_message "${GREEN}Node.js and npm are already installed.${NC}"
    else
        # Add NodeSource repository for the latest Node.js
        curl -fsSL https://deb.nodesource.com/setup_14.x | bash - >> "$LOG_FILE" 2>&1
        apt-get install -y nodejs >> "$LOG_FILE" 2>&1
        
        # Verify installation
        if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
            log_message "${GREEN}Node.js and npm installed successfully.${NC}"
        else
            log_message "${RED}Failed to install Node.js and npm.${NC}"
            exit 1
        fi
    fi
}

# Function to install dependencies for Volumio with audiophile elegance
install_dep_volumio() {
    log_message "${YELLOW}Installing dependencies for Volumio...${NC}"
    if apt-get install -y build-essential raspberrypi-kernel-headers libffi-dev libssl-dev >/dev/null 2>&1; then
        log_message "${GREEN}Essential Volumio dependencies installed successfully.${NC}"
    else
        log_message "${YELLOW}Failed to install some dependencies. Attempting workaround...${NC}"
        if bash Workaround_BuildEssentials.sh >> "$LOG_FILE" 2>&1; then
            log_message "${GREEN}Workaround executed successfully.${NC}"
        else
            log_message "${RED}Workaround failed. Cannot proceed.${NC}"
            exit 1
        fi
    fi
}

# Function to install Node.js dependencies using package.json
install_dependencies() {
    log_message "${YELLOW}Installing Node.js dependencies from package.json...${NC}"
    
    # Ensure package.json exists
    if [ ! -f package.json ]; then
        log_message "${YELLOW}No package.json found. Initializing a new one...${NC}"
        npm init -y >> "$LOG_FILE" 2>&1
    fi
    
    # Clean npm cache to prevent corrupted installations
    npm cache clean --force >> "$LOG_FILE" 2>&1
    
    # Remove existing node_modules and package-lock.json for a clean install
    rm -rf node_modules package-lock.json
    
    # Install dependencies
    npm install >> "$LOG_FILE" 2>&1
    
    # Optionally, update all packages to their latest versions
    log_message "${YELLOW}Updating all Node.js modules to their latest versions...${NC}"
    npm update >> "$LOG_FILE" 2>&1
}

# Function to create and enable the Startup Indicator LED Service
setup_startup_indicator_service() {
    log_message "${YELLOW}Setting up the Startup Indicator LED Service...${NC}"
    
    if systemctl list-unit-files | grep -q 'startup-indicator.service'; then
        log_message "${GREEN}Startup Indicator LED Service already exists. Reloading and restarting...${NC}"
        systemctl daemon-reload
        systemctl restart startup-indicator.service
    else
        # Create the systemd service file
        tee /etc/systemd/system/startup-indicator.service > /dev/null <<EOL
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
        systemctl daemon-reload

        # Enable the service to start on boot
        systemctl enable startup-indicator.service

        # Start the service
        systemctl start startup-indicator.service

        log_message "${GREEN}Startup Indicator LED Service has been created, enabled, and started.${NC}"
    fi
}

# Function to set up the OLED service
setup_oled_service() {
    log_message "${YELLOW}Setting up the OLED Display Service...${NC}"
    
    # Create the systemd service file
    tee /etc/systemd/system/oled.service > /dev/null <<EOL
[Unit]
Description=Quadify OLED Display Service
After=volumio.service

[Service]
WorkingDirectory=/home/volumio/Quadify/oled/
ExecStart=/usr/bin/node /home/volumio/Quadify/oled/index.js
ExecStop=/usr/bin/node /home/volumio/Quadify/oled/off.js
StandardOutput=null
Type=simple
User=volumio

[Install]
WantedBy=multi-user.target
EOL

    # Enable the OLED service to start on boot
    systemctl enable oled >> "$LOG_FILE" 2>&1

    # Start the OLED service
    systemctl start oled >> "$LOG_FILE" 2>&1

    log_message "${GREEN}OLED Display Service has been created, enabled, and started.${NC}"
}

# Function to configure SPI settings
configure_spi() {
    log_message "${YELLOW}Configuring SPI settings...${NC}"
    
    # Enable spi-dev and spi in userconfig.txt
    echo "spi-dev" | tee -a /etc/modules > /dev/null
    echo "dtparam=spi=on" | tee -a /boot/userconfig.txt > /dev/null

    # Check for SPI buffer size and set if necessary
    if [ ! -f "/etc/modprobe.d/spidev.conf" ] || ! grep -q 'bufsiz=8192' /etc/modprobe.d/spidev.conf; then
        echo "options spidev bufsiz=8192" | tee -a /etc/modprobe.d/spidev.conf > /dev/null
    fi

    # Reboot to apply SPI settings
    log_message "${YELLOW}Rebooting to apply SPI settings...${NC}"
    reboot
}

# Function to verify the presence of spi_binding
verify_spi_binding() {
    log_message "${YELLOW}Verifying the presence of spi_binding module...${NC}"
    if [ -f "/home/volumio/Quadify/oled/node_modules/pi-spi/build/Release/spi_binding.node" ]; then
        log_message "${GREEN}spi_binding module found successfully.${NC}"
    else
        log_message "${RED}spi_binding module is missing. Attempting to rebuild pi-spi...${NC}"
        cd /home/volumio/Quadify/oled
        npm rebuild pi-spi >> "$LOG_FILE" 2>&1
        
        if [ -f "/home/volumio/Quadify/oled/node_modules/pi-spi/build/Release/spi_binding.node" ]; then
            log_message "${GREEN}spi_binding module rebuilt successfully.${NC}"
        else
            log_message "${RED}Failed to rebuild spi_binding module. Please check the logs for details.${NC}"
            exit 1
        fi
    fi
}

# Main Installation Flow

# Check for root privileges
check_root

# Start the installation with flair
log_message "${GREEN}Quadify's audiophile installation is tuning up...${NC}"

# Install build essentials and set up compilers
install_build_essentials

# Install Node.js and npm
install_node_and_npm

# Alternatively, if you prefer using nvm, uncomment the following lines:
# install_nvm_and_node

# Installation steps for Volumio dependencies
install_dep_volumio

# Navigate to project directory
cd /home/volumio/Quadify/oled

# Install Node.js dependencies
install_dependencies

# Configure SPI settings (reboot required)
configure_spi

# After reboot, you need to run the remaining steps manually or automate the script to continue post-reboot.

# Setup OLED and Startup Indicator services
setup_oled_service
setup_startup_indicator_service

# Verify spi_binding module
verify_spi_binding

log_message "${GREEN}The Quadify Dac is set. Happy Listening!!${NC}"
log_message "Installation began at $(date -d @$start_time +%T) and concluded at $(date +"%T"). Enjoy the music!"
