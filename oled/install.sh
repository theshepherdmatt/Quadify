#!/bin/bash
set -e

# ============================
#   Color Code Definitions
# ============================
RED='\033[0;31m'        # Red
GREEN='\033[0;32m'      # Green
YELLOW='\033[1;33m'     # Yellow
BLUE='\033[0;34m'       # Blue
CYAN='\033[0;36m'       # Cyan
MAGENTA='\033[0;35m'    # Magenta
NC='\033[0m'            # No Color

# ============================
#   Log File Definition
# ============================
LOG_FILE="/home/volumio/Quadify/oled/install_details.log"

# ============================
#   Log Message Function
# ============================
log_message() {
    local type="$1"
    local message="$2"
    case "$type" in
        "info")
            echo -e "${BLUE}[INFO]${NC} $message"
            ;;
        "success")
            echo -e "${GREEN}[SUCCESS]${NC} $message"
            ;;
        "warning")
            echo -e "${YELLOW}[WARNING]${NC} $message"
            ;;
        "error")
            echo -e "${RED}[ERROR]${NC} $message" >&2
            ;;
        "highlight")
            echo -e "${MAGENTA}$message${NC}"
            ;;
        *)
            echo -e "[UNKNOWN] $message"
            ;;
    esac
}

# ============================
#   ASCII Art Banner Function
# ============================
banner() {
    echo -e "${MAGENTA}"
    echo "  ___  _   _   _    ____ ___ _______   __"
    echo " / _ \| | | | / \  |  _ \_ _|  ___\ \ / /"
    echo "| | | | | | |/ _ \ | | | | || |_   \ V / "
    echo "| |_| | |_| / ___ \| |_| | ||  _|   | |  "
    echo " \__\_\\___/_/   \_\____/___|_|     |_|  "
    echo -e "${NC}"
}

# ============================
#   Spinner Function
# ============================
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

# ============================
#   Prompt User Function
# ============================
prompt_user() {
    local message="$1"
    local response
    while true; do
        read -rp "$(echo -e "${CYAN}$message [y/n]: ${NC}")" response
        case "$response" in
            [Yy]* ) return 0;;
            [Nn]* ) return 1;;
            * ) echo -e "${YELLOW}Please answer yes or no.${NC}";;
        esac
    done
}

# ============================
#   Check for Root Privileges
# ============================
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_message "warning" "Please run as root or use sudo."
        exit 1
    fi
}

# ============================
#   Install Build Essentials
# ============================
install_build_essentials() {
    log_message "info" "Installing build essentials and setting up compilers..."
    
    # Verify Workaround_BuildEssentials.sh exists
    if [ -f "/home/volumio/Quadify/oled/Workaround_BuildEssentials.sh" ]; then
        bash /home/volumio/Quadify/oled/Workaround_BuildEssentials.sh >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid
        log_message "success" "Build essentials installed successfully."
    else
        log_message "error" "Workaround_BuildEssentials.sh not found at /home/volumio/Quadify/oled/. Please ensure the file exists."
        exit 1
    fi
}

# ============================
#   Install Node.js and npm
# ============================
install_node_and_npm() {
    log_message "info" "Installing Node.js and npm..."
    if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
        log_message "success" "Node.js and npm are already installed."
    else
        # Add NodeSource repository
        curl -fsSL https://deb.nodesource.com/setup_14.x | bash - >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid
        
        # Install Node.js
        apt-get install -y nodejs >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid
        
        # Verify installation
        if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
            log_message "success" "Node.js and npm installed successfully."
        else
            log_message "error" "Failed to install Node.js and npm."
            exit 1
        fi
    fi
}

# ============================
#   Install Dependencies
# ============================
install_dependencies() {
    log_message "info" "Installing Node.js dependencies from package.json..."
    
    # Navigate to project directory
    cd /home/volumio/Quadify/oled || { log_message "error" "Project directory not found."; exit 1; }
    
    # Ensure package.json exists
    if [ ! -f package.json ]; then
        log_message "warning" "No package.json found. Initializing a new one..."
        npm init -y >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid
    fi
    
    # Clean npm cache
    npm cache clean --force >> "$LOG_FILE" 2>&1
    
    # Remove existing node_modules and package-lock.json
    rm -rf node_modules package-lock.json
    
    # Install dependencies
    npm install >> "$LOG_FILE" 2>&1 &
    pid=$!
    spinner $pid
    wait $pid
    
    # Update dependencies
    log_message "info" "Updating all Node.js modules to their latest versions..."
    npm update >> "$LOG_FILE" 2>&1 &
    pid=$!
    spinner $pid
    wait $pid
    
    log_message "success" "Node.js dependencies installed and updated successfully."
}

# ============================
#   Configure SPI
# ============================
configure_spi() {
    log_message "info" "Configuring SPI settings..."
    
    # Enable SPI in /boot/userconfig.txt
    echo "dtparam=spi=on" | tee -a /boot/userconfig.txt > /dev/null
    
    # Load spi-dev module
    echo "spi-dev" | tee -a /etc/modules > /dev/null
    
    # Optionally set SPI buffer size
    if [ ! -f "/etc/modprobe.d/spidev.conf" ] || ! grep -q 'bufsiz=8192' /etc/modprobe.d/spidev.conf; then
        echo "options spidev bufsiz=8192" | tee -a /etc/modprobe.d/spidev.conf > /dev/null
    fi
    
    log_message "success" "SPI settings configured."
}

# ============================
#   Configure I2C
# ============================
configure_i2c() {
    log_message "info" "Configuring I2C settings..."
    
    # Enable I2C in /boot/userconfig.txt
    echo "dtparam=i2c_arm=on" | tee -a /boot/userconfig.txt > /dev/null
    
    # Load i2c-dev module
    echo "i2c-dev" | tee -a /etc/modules > /dev/null
    
    # Install i2c-tools
    apt-get install -y i2c-tools >> "$LOG_FILE" 2>&1 &
    pid=$!
    spinner $pid
    wait $pid
    
    # Add 'volumio' user to 'i2c' group
    log_message "info" "Adding 'volumio' user to 'i2c' group..."
    usermod -aG i2c volumio
    log_message "success" "'volumio' user added to 'i2c' group."
    
    log_message "success" "I2C settings configured."
}

# ============================
#   Verify I2C Devices
# ============================
verify_i2c() {
    log_message "info" "Verifying I2C configuration and detecting devices..."
    
    # Detect I2C devices on bus 1
    sudo i2cdetect -y 1 | tee -a "$LOG_FILE"
    
    # Check if any devices are detected
    DEVICE_COUNT=$(sudo i2cdetect -y 1 | grep -E '^[0-9a-fA-F]' | grep -v '--' | wc -l)
    
    if [ "$DEVICE_COUNT" -gt 0 ]; then
        log_message "success" "I2C devices detected successfully."
    else
        log_message "warning" "No I2C devices detected. Please check your connections and device addresses."
    fi
}

# ============================
#   Verify spi_binding Module
# ============================
verify_spi_binding() {
    log_message "info" "Verifying the presence of spi_binding module..."
    if [ -f "/home/volumio/Quadify/oled/node_modules/pi-spi/build/Release/spi_binding.node" ]; then
        log_message "success" "spi_binding module found successfully."
    else
        log_message "warning" "spi_binding module is missing. Attempting to rebuild pi-spi..."
        cd /home/volumio/Quadify/oled || { log_message "error" "Project directory not found."; exit 1; }
        npm rebuild pi-spi >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid
        
        if [ -f "/home/volumio/Quadify/oled/node_modules/pi-spi/build/Release/spi_binding.node" ]; then
            log_message "success" "spi_binding module rebuilt successfully."
        else
            log_message "error" "Failed to rebuild spi_binding module. Please check the logs for details."
            exit 1
        fi
    fi
}

# ============================
#   Setup Systemd Services
# ============================
setup_startup_indicator_service() {
    log_message "info" "Setting up the Startup Indicator LED Service..."
    
    if systemctl list-unit-files | grep -q 'startup-indicator.service'; then
        log_message "success" "Startup Indicator LED Service already exists. Reloading and restarting..."
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
        systemctl enable startup-indicator.service >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid

        # Start the service
        systemctl start startup-indicator.service >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid

        log_message "success" "Startup Indicator LED Service has been created, enabled, and started."
    fi
}

setup_oled_service() {
    log_message "info" "Setting up the OLED Display Service..."
    
    if systemctl list-unit-files | grep -q 'oled.service'; then
        log_message "success" "OLED Display Service already exists. Reloading and restarting..."
        systemctl daemon-reload
        systemctl restart oled.service
    else
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

        # Reload systemd to apply the new service
        systemctl daemon-reload

        # Enable the OLED service to start on boot
        systemctl enable oled.service >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid

        # Start the OLED service
        systemctl start oled.service >> "$LOG_FILE" 2>&1 &
        pid=$!
        spinner $pid
        wait $pid

        log_message "success" "OLED Display Service has been created, enabled, and started."
    fi
}

# ============================
#   Reboot System Function
# ============================
reboot_system() {
    log_message "info" "Rebooting the system to apply SPI and I2C settings..."
    reboot
}

# ============================
#   Handle Post-Reboot Steps
# ============================
handle_post_reboot() {
    log_message "info" "Continuing with installation after reboot..."
    
    # Setup OLED and Startup Indicator services
    setup_oled_service
    setup_startup_indicator_service
    
    # Verify spi_binding module
    verify_spi_binding
    
    # Verify I2C devices
    verify_i2c
    
    log_message "success" "The Quadify Dac is set. Happy Listening!!"
    log_message "info" "Installation concluded at $(date +"%T"). Enjoy the music!"
}

# ============================
#   Check for Post-Reboot Flag
# ============================
check_post_reboot() {
    if [ -f "/home/volumio/Quadify/oled/.post_reboot" ]; then
        handle_post_reboot
        rm /home/volumio/Quadify/oled/.post_reboot
        exit 0
    fi
}

# ============================
#   Main Function
# ============================
main() {
    # Display the ASCII Art Banner
    banner

    # Check for root privileges
    check_root

    # Check if post-reboot steps need to be handled
    check_post_reboot

    log_message "info" "Quadify's audiophile installation is tuning up..."

    # Install build essentials
    install_build_essentials

    # Install Node.js and npm
    install_node_and_npm

    # Install project dependencies
    install_dependencies

    # Configure SPI
    configure_spi

    # Configure I2C
    configure_i2c

    # Verify I2C devices
    verify_i2c

    # Verify spi_binding module
    verify_spi_binding

    # Setup systemd services
    setup_startup_indicator_service
    setup_oled_service

    # Final success message
    log_message "success" "The Quadify Dac is set. Happy Listening!!"
    log_message "info" "Installation concluded at $(date +"%T"). Enjoy the music!"

    # Prompt for reboot
    if prompt_user "Do you want to reboot now to apply all changes?"; then
        # Create a flag file to handle post-reboot steps
        touch /home/volumio/Quadify/oled/.post_reboot
        reboot_system
    else
        log_message "warning" "Reboot skipped. Please reboot manually later to apply changes."
    fi
}

# Execute the main function
main
