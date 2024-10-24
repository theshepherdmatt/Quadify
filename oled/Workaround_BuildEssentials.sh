#!/bin/bash
set -e

# Define the APT sources list file
SRC=/etc/apt/sources.list

# Backup the original sources list in case something goes wrong
sudo cp "$SRC" "${SRC}.backup"

# Check if 'buster' is not already in the sources list
if ! grep -q 'buster' "$SRC"; then
    echo "Adding Buster sources..."
    echo 'deb http://raspbian.raspberrypi.org/raspbian/ buster main contrib non-free rpi' | sudo tee -a "$SRC"
fi

# Update the package lists
sudo apt-get update

# Install the required packages
sudo apt-get install -y binutils libstdc++-6-dev gcc-8 g++-8 build-essential python3

# Set gcc-8 and g++-8 as the default compilers
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-8 100
sudo update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-8 100

# Verify the default gcc and g++ versions
gcc --version
g++ --version

# Remove the Buster sources to prevent future compatibility issues
sudo sed -i '/buster/d' "$SRC"

# Update the package lists after removing the Buster sources
sudo apt-get update

echo "Installation complete. Buster sources removed."
