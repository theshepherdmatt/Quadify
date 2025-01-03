#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status
#set -x  # Uncomment to enable debugging

# ============================
#   Colour Code Definitions
# ============================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# ============================
#   Variables for Progress Tracking
# ============================
TOTAL_STEPS=17  # Updated from 10 to 11
CURRENT_STEP=0
LOG_FILE="install.log"

# Remove existing log file
rm -f "$LOG_FILE"

# ============================
#   ASCII Art Banner Function
# ============================
banner() {
    echo -e "\033[0;35m"
    echo "                                                                                                                                 "
    echo "                                                                  dddddddd                                                       "
    echo "     QQQQQQQQQ                                                    d::::::d  iiii     ffffffffffffffff                            "
    echo "   QQ:::::::::QQ                                                  d::::::d i::::i   f::::::::::::::::f                           "
    echo " QQ:::::::::::::QQ                                                d::::::d  iiii   f::::::::::::::::::f                          "
    echo "Q:::::::QQQ:::::::Q                                               d:::::d          f::::::fffffff:::::f                          "
    echo "Q::::::O   Q::::::Quuuuuu    uuuuuu    aaaaaaaaaaaaa      ddddddddd:::::d iiiiiii  f:::::f       ffffffyyyyyyy           yyyyyyy"
    echo "Q:::::O     Q:::::Qu::::u    u::::u    a::::::::::::a   dd::::::::::::::d i:::::i  f:::::f              y:::::y         y:::::y "
    echo "Q:::::O     Q:::::Qu::::u    u::::u    aaaaaaaaa:::::a d::::::::::::::::d  i::::i f:::::::ffffff         y:::::y       y:::::y  "
    echo "Q:::::O     Q:::::Qu::::u    u::::u             a::::ad:::::::ddddd:::::d  i::::i f::::::::::::f          y:::::y     y:::::y   "
    echo "Q:::::O     Q:::::Qu::::u    u::::u      aaaaaaa:::::ad::::::d    d:::::d  i::::i f::::::::::::f           y:::::y   y:::::y    "
    echo "Q:::::O     Q:::::Qu::::u    u::::u    aa::::::::::::ad:::::d     d:::::d  i::::i f:::::::ffffff            y:::::y y:::::y     "
    echo "Q:::::O  QQQQ:::::Qu::::u    u::::u   a::::aaaa::::::ad:::::d     d:::::d  i::::i  f:::::f                   y:::::y:::::y      "
    echo "Q::::::O Q::::::::Qu:::::uuuu:::::u  a::::a    a:::::ad:::::d     d:::::d  i::::i  f:::::f                    y:::::::::y       "
    echo "Q:::::::QQ::::::::Qu:::::::::::::::uua::::a    a:::::ad::::::ddddd::::::ddi::::::if:::::::f                    y:::::::y        "
    echo " QQ::::::::::::::Q  u:::::::::::::::ua:::::aaaa::::::a d:::::::::::::::::di::::::if:::::::f                     y:::::y         "
    echo "   QQ:::::::::::Q    uu::::::::uu:::u a::::::::::aa:::a d:::::::::ddd::::di::::::if:::::::f                    y:::::y          "
    echo "     QQQQQQQQ::::QQ    uuuuuuuu  uuuu  aaaaaaaaaa  aaaa  ddddddddd   dddddiiiiiiiifffffffff                   y:::::y           "
    echo "             Q:::::Q                                                                                         y:::::y            "
    echo "              QQQQQQ                                                                                        y:::::y             "
    echo "                                                                                                           y:::::y              "
    echo "                                                                                                          yyyyyyy               "
    echo "                                                                                                                                 "
    echo -e "\033[0m"
}

# ============================
#   Log Message Functions
# ============================
log_message() {
    local type="$1"
    local message="$2"
    case "$type" in
        "info") echo -e "${BLUE}[INFO]${NC} $message" ;;
        "success") echo -e "${GREEN}[SUCCESS]${NC} $message" ;;
        "warning") echo -e "${YELLOW}[WARNING]${NC} $message" ;;
        "error") echo -e "${RED}[ERROR]${NC} $message" >&2 ;;
    esac
}

log_progress() {
    local message="$1"
    CURRENT_STEP=$(( CURRENT_STEP + 1 ))
    echo -e "${BLUE}[${CURRENT_STEP}/${TOTAL_STEPS}]${NC} $message"
}

# ============================
#   Run Command Function
# ============================
run_command() {
    local cmd="$1"
    eval "$cmd" >> "$LOG_FILE" 2>&1
    if [ $? -ne 0 ]; then
        log_message "error" "Command failed: $cmd. See $LOG_FILE for details."
        exit 1
    fi
}

# ============================
#   Check for Root Privileges
# ============================
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_message "error" "Please run as root or use sudo."
        exit 1
    fi
}

# ============================
#   Install System-Level Dependencies
# ============================
install_system_dependencies() {
    log_progress "Installing system-level dependencies..."

    # Update package lists
    run_command "apt-get update"

    # Install essential packages
    run_command "apt-get install -y \
        python3.7 \
        python3.7-dev \
        python3-pip \
        libjpeg-dev \
        zlib1g-dev \
        libfreetype6-dev \
        i2c-tools \
        python3-smbus \
        libgirepository1.0-dev \
        pkg-config \
        libcairo2-dev \
        libffi-dev \
        build-essential \
        libxml2-dev \
        libxslt1-dev \
        libssl-dev \
        lsof"

    log_message "success" "System-level dependencies installed successfully."
}

# ============================
#   Upgrade pip, setuptools, and wheel
# ============================
upgrade_pip() {
    log_progress "Upgrading pip, setuptools, and wheel..."

    run_command "python3.7 -m pip install --upgrade pip setuptools wheel"

    log_message "success" "pip, setuptools, and wheel upgraded."
}

# ============================
#   Install Python Dependencies
# ============================
install_python_dependencies() {
    log_progress "Installing Python dependencies..."

    # Install pycairo first to resolve PyGObject dependency
    run_command "python3.7 -m pip install --upgrade --ignore-installed pycairo"

    # Install dependencies from requirements.txt globally with --ignore-installed
    run_command "python3.7 -m pip install --upgrade --ignore-installed -r /home/volumio/Quadify/requirements.txt"

    log_message "success" "Python dependencies installed successfully."
}

# ============================
#   Enable I2C and SPI in config.txt
# ============================
enable_i2c_spi() {
    log_progress "Enabling I2C and SPI in config.txt..."

    CONFIG_FILE="/boot/userconfig.txt"

    if [ ! -f "$CONFIG_FILE" ]; then
        run_command "touch \"$CONFIG_FILE\""
    fi

    # Enable SPI and I2C
    if ! grep -q "^dtparam=spi=on" "$CONFIG_FILE"; then
        echo "dtparam=spi=on" >> "$CONFIG_FILE"
        log_message "success" "SPI enabled."
    else
        log_message "info" "SPI is already enabled."
    fi

    if ! grep -q "^dtparam=i2c_arm=on" "$CONFIG_FILE"; then
        echo "dtparam=i2c_arm=on" >> "$CONFIG_FILE"
        log_message "success" "I2C enabled."
    else
        log_message "info" "I2C is already enabled."
    fi

    log_message "success" "I2C and SPI enabled in config.txt."

    # Load kernel modules
    log_progress "Loading I2C and SPI kernel modules..."
    run_command "modprobe i2c-dev"
    run_command "modprobe spi-bcm2835"
    log_message "success" "I2C and SPI kernel modules loaded."

    # Verify that /dev/i2c-1 exists
    if [ -e /dev/i2c-1 ]; then
        log_message "success" "/dev/i2c-1 is present."
    else
        log_message "warning" "/dev/i2c-1 is not present. Attempting to initialize I2C..."
        run_command "modprobe i2c-bcm2708"
        sleep 1
        if [ -e /dev/i2c-1 ]; then
            log_message "success" "/dev/i2c-1 successfully initialized."
        else
            log_message "error" "/dev/i2c-1 could not be initialized. Please ensure I2C is enabled correctly."
            exit 1
        fi
    fi
}

# ============================
#   Detect MCP23017 I2C Address
# ============================

detect_i2c_address() {
    log_progress "Detecting MCP23017 I2C address..."

    # Use the absolute path to i2cdetect and capture the output
    i2c_output=$(/usr/sbin/i2cdetect -y 1)
    echo "$i2c_output" >> "$LOG_FILE"
    
    # For debugging: Print the i2c_output to the terminal
    echo "$i2c_output"

    # Use word boundaries in grep to match exact addresses
    address=$(echo "$i2c_output" | grep -oE '\b(20|21|22|23|24|25|26|27)\b' | head -n 1)

    if [[ -z "$address" ]]; then
        log_message "warning" "MCP23017 not found. Check wiring and connections as per instructions on our website."
    else
        log_message "success" "Detected MCP23017 at I2C address: 0x$address."
        update_buttonsleds_address "$address"
    fi
}

# ============================
#   Update MCP23017 Address in buttonsleds.py
# ============================
update_buttonsleds_address() {
    local detected_address="$1"
    BUTTONSLEDS_FILE="/home/volumio/Quadify/src/hardware/buttonsleds.py"

    if [[ -f "$BUTTONSLEDS_FILE" ]]; then
        # Check if the line exists
        if grep -q "mcp23017_address" "$BUTTONSLEDS_FILE"; then
            # Replace the existing address
            run_command "sed -i \"s/mcp23017_address = 0x[0-9a-fA-F]\\{2\\}/mcp23017_address = 0x$detected_address/\" \"$BUTTONSLEDS_FILE\""
            log_message "success" "Updated MCP23017 address in buttonsleds.py to 0x$detected_address."
        else
            # Append the address line if it doesn't exist
            run_command "echo \"mcp23017_address = 0x$detected_address\" >> \"$BUTTONSLEDS_FILE\""
            log_message "success" "Added MCP23017 address in buttonsleds.py as 0x$detected_address."
        fi
    else
        log_message "error" "buttonsleds.py not found at $BUTTONSLEDS_FILE. Ensure the path is correct."
        exit 1
    fi
}

# ============================
#   Configure Samba
# ============================

# Add the Samba setup function
setup_samba() {
    log_progress "Configuring Samba for Quadify..."

    SMB_CONF="/etc/samba/smb.conf"

    # Backup the original smb.conf
    if [ ! -f "$SMB_CONF.bak" ]; then
        run_command "cp $SMB_CONF $SMB_CONF.bak"
        log_message "info" "Backup of smb.conf created."
    fi

    # Append Samba configuration for Quadify
    if ! grep -q "\[Quadify\]" "$SMB_CONF"; then
        echo -e "\n[Quadify]\n   path = /home/volumio/Quadify\n   writable = yes\n   browseable = yes\n   guest ok = yes\n   force user = volumio\n   create mask = 0777\n   directory mask = 0777\n   public = yes" >> "$SMB_CONF"
        log_message "success" "Samba configuration for Quadify added."
    else
        log_message "info" "Samba configuration for Quadify already exists."
    fi

    # Restart Samba service
    run_command "systemctl restart smbd"
    log_message "success" "Samba service restarted."

    # Set ownership and permissions for the Quadify directory
    run_command "chown -R volumio:volumio /home/volumio/Quadify"
    run_command "chmod -R 777 /home/volumio/Quadify"
    log_message "success" "Permissions for /home/volumio/Quadify set successfully."
}

# ============================
#   Configure Systemd Service
# ============================
setup_main_service() {
    log_progress "Setting up the Main Quadify Service..."

    SERVICE_FILE="/etc/systemd/system/quadify.service"

    # Copy the service file from the service folder
    if [[ -f "/home/volumio/Quadify/service/quadify.service" ]]; then
        run_command "cp /home/volumio/Quadify/service/quadify.service \"$SERVICE_FILE\""
        log_message "success" "quadify.service copied to $SERVICE_FILE."
    else
        log_message "error" "Service file quadify.service not found in services directory."
        exit 1
    fi

    # Reload systemd daemon to recognize the new service
    run_command "systemctl daemon-reload"

    # Enable and start the service
    run_command "systemctl enable quadify.service"
    run_command "systemctl start quadify.service"

    log_message "success" "Main Quadify Service has been enabled and started."
}

# ============================
#   Update MPD Configuration
# ============================
configure_mpd() {
    log_progress "Configuring MPD for CAVA..."

    MPD_CONF_FILE="/volumio/app/plugins/music_service/mpd/mpd.conf.tmpl"
    FIFO_OUTPUT="
audio_output {
    type            \"fifo\"
    name            \"my_fifo\"
    path            \"/tmp/cava.fifo\"
    format          \"44100:16:2\"
}"

    # Check if the FIFO configuration already exists
    if grep -q "path.*\"/tmp/cava.fifo\"" "$MPD_CONF_FILE"; then
        log_message "info" "FIFO output configuration already exists in MPD config."
    else
        log_progress "Adding FIFO output configuration to MPD config..."
        echo "$FIFO_OUTPUT" | sudo tee -a "$MPD_CONF_FILE" > /dev/null
        log_message "success" "FIFO output configuration added to MPD config."
    fi

    # Restart MPD to apply changes
    run_command "sudo systemctl restart mpd"
    log_message "success" "MPD restarted with updated configuration."
}


# ============================
#   Install CAVA Dependencies and Build
# ============================
check_cava_installed() {
    if command -v cava >/dev/null 2>&1; then
        log_message "info" "CAVA is already installed. Skipping installation."
        return 0
    else
        return 1
    fi
}

install_cava_from_fork() {
    log_progress "Installing CAVA from fork..."

    CAVA_REPO="https://github.com/theshepherdmatt/cava.git"
    CAVA_INSTALL_DIR="/home/volumio/cava"

    # Check if CAVA is already installed
    if check_cava_installed; then
        log_message "info" "Skipping CAVA installation."
        return
    fi

    # Install dependencies required to build CAVA
    log_progress "Installing CAVA dependencies..."
    run_command "apt-get install -y \
        libfftw3-dev \
        libasound2-dev \
        libncursesw5-dev \
        libpulse-dev \
        libtool \
        automake \
        autoconf \
        gcc \
        make \
        pkg-config \
        libiniparser-dev"

    log_message "success" "CAVA dependencies installed successfully."

    # Clone the forked CAVA repository
    if [[ ! -d "$CAVA_INSTALL_DIR" ]]; then
        run_command "git clone $CAVA_REPO $CAVA_INSTALL_DIR"
        log_message "success" "Cloned CAVA repository from fork."
    else
        log_message "info" "CAVA repository already exists. Pulling latest changes..."
        run_command "cd $CAVA_INSTALL_DIR && git pull"
    fi

    # Build and install CAVA
    log_progress "Building and installing CAVA..."
    run_command "cd $CAVA_INSTALL_DIR && ./autogen.sh"
    log_message "info" "autogen.sh completed"
    run_command "cd $CAVA_INSTALL_DIR && ./configure"
    log_message "info" "configure completed"
    run_command "cd $CAVA_INSTALL_DIR && make"
    log_message "info" "make completed"
    run_command "cd $CAVA_INSTALL_DIR && sudo make install"
    log_message "success" "CAVA installed successfully."
}


# ============================
#   Install CAVA Configuration
# ============================

setup_cava_config() {
    log_progress "Setting up CAVA configuration..."

    CONFIG_DIR="/home/volumio/.config/cava"
    CONFIG_FILE="$CONFIG_DIR/config"
    REPO_CONFIG_FILE="/home/volumio/cava/config/default_config"

    # Create the configuration directory
    run_command "mkdir -p $CONFIG_DIR"

    # Check if the file already exists in the destination
    if [[ ! -f $CONFIG_FILE ]]; then
        if [[ -f $REPO_CONFIG_FILE ]]; then
            log_message "info" "Copying default CAVA configuration from repository."
            run_command "cp $REPO_CONFIG_FILE $CONFIG_FILE"
        else
            log_message "error" "Default configuration file not found in repository."
            exit 1
        fi
    else
        log_message "info" "CAVA configuration already exists. Skipping copy."
    fi

    # Set ownership and permissions
    run_command "chown -R volumio:volumio $CONFIG_DIR"
    log_message "success" "CAVA configuration setup completed."
}


# ============================
#   Configure CAVA Service
# ============================
setup_cava_service() {
    log_progress "Setting up the CAVA Service..."

    CAVA_SERVICE_FILE="/etc/systemd/system/cava.service"

    # Copy the CAVA service file from the service folder
    if [[ -f "/home/volumio/Quadify/service/cava.service" ]]; then
        run_command "cp /home/volumio/Quadify/service/cava.service \"$CAVA_SERVICE_FILE\""
        log_message "success" "cava.service copied to $CAVA_SERVICE_FILE."
    else
        log_message "error" "Service file cava.service not found in services directory."
        exit 1
    fi

    # Reload systemd daemon to recognize the new service
    run_command "systemctl daemon-reload"

    # Enable and start the CAVA service
    run_command "systemctl enable cava.service"
    run_command "systemctl start cava.service"

    log_message "success" "CAVA Service has been enabled and started."
}


# ============================
#   Configure Buttons and LEDs
# ============================
configure_buttons_leds() {
    log_progress "Configuring Buttons and LEDs activation..."

    # Path to main.py
    MAIN_PY_PATH="/home/volumio/Quadify/src/main.py"

    # Check if main.py exists
    if [[ ! -f "$MAIN_PY_PATH" ]]; then
        log_message "error" "main.py not found at $MAIN_PY_PATH. Please ensure the path is correct."
        exit 1
    fi

    # Prompt the user
    while true; do
        read -rp "Do you need buttons and LEDs activated? (y/n): " yn
        case $yn in
            [Yy]* )
                log_message "info" "Buttons and LEDs will be activated."
                # Uncomment the initialization line
                if grep -q "^[#]*\s*buttons_leds\s*=\s*ButtonsLEDController" "$MAIN_PY_PATH"; then
                    sed -i.bak '/buttons_leds\s*=\s*ButtonsLEDController/ s/^#//' "$MAIN_PY_PATH"
                    log_message "success" "Activated 'buttons_leds = ButtonsLEDController(...)' in main.py."
                else
                    log_message "info" "'buttons_leds = ButtonsLEDController(...)' is already active in main.py."
                fi

                # Uncomment the start line
                if grep -q "^[#]*\s*buttons_leds.start()" "$MAIN_PY_PATH"; then
                    sed -i.bak '/buttons_leds.start()/ s/^#//' "$MAIN_PY_PATH"
                    log_message "success" "Activated 'buttons_leds.start()' in main.py."
                else
                    log_message "info" "'buttons_leds.start()' is already active in main.py."
                fi
                break
                ;;
            [Nn]* )
                log_message "info" "Buttons and LEDs will be deactivated."
                # Comment out the initialization line by adding a '#'
                if grep -q "^[^#]*\s*buttons_leds\s*=\s*ButtonsLEDController" "$MAIN_PY_PATH"; then
                    # Add '#' after leading spaces
                    sed -i.bak '/buttons_leds\s*=\s*ButtonsLEDController/ s/^\(\s*\)/\1#/' "$MAIN_PY_PATH"
                    log_message "success" "Deactivated 'buttons_leds = ButtonsLEDController(...)' in main.py."
                else
                    log_message "info" "'buttons_leds = ButtonsLEDController(...)' is already deactivated in main.py."
                fi

                # Comment out the start line by adding a '#'
                if grep -q "^[^#]*\s*buttons_leds.start()" "$MAIN_PY_PATH"; then
                    # Add '#' after leading spaces
                    sed -i.bak '/buttons_leds.start()/ s/^\(\s*\)/\1#/' "$MAIN_PY_PATH"
                    log_message "success" "Deactivated 'buttons_leds.start()' in main.py."
                else
                    log_message "info" "'buttons_leds.start()' is already deactivated in main.py."
                fi
                break
                ;;
            * )
                log_message "warning" "Please answer with 'y' or 'n'."
                ;;
        esac
    done

    log_message "success" "Buttons and LEDs configuration completed."
}

# ============================
#   Set Ownership and Permissions
# ============================
set_permissions() {
    log_progress "Setting ownership and permissions of project directory..."

    run_command "chown -R volumio:volumio /home/volumio/Quadify"
    run_command "chmod -R 755 /home/volumio/Quadify"

    log_message "success" "Ownership and permissions set to volumio user."
}

# ============================
#   Main Installation Function
# ============================
main() {
    banner
    log_message "info" "Starting the installation script..."
    check_root
    install_system_dependencies
    enable_i2c_spi
    upgrade_pip
    install_python_dependencies
    detect_i2c_address
    setup_main_service

    # Update MPD configuration
    configure_mpd
    echo "DEBUG: Finished installing MPD"

    # Install CAVA and configure its service
    install_cava_from_fork
    echo "DEBUG: Finished installing CAVA from fork"

    setup_cava_config
    echo "DEBUG: Finished installing CAVA Configuration"

    setup_cava_service
    echo "DEBUG: Finished installing CAVA Service"

    # Add the new configuration step here
    configure_buttons_leds

    # Add the Samba setup step
    setup_samba

    set_permissions
    log_message "success" "Installation complete. Please verify the setup."
}

# Execute the main function
main
