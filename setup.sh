#!/bin/bash

# This script installs all necessary components for the Cue Light System
# using a Python virtual environment, which is the recommended method.
# Run it with: ./setup.sh

echo "--- Starting Cue Light System Setup ---"

# 1. Update the package list on the Pi
echo "--> Updating package list..."
sudo apt-get update -y

# 2. Install Mosquitto MQTT Broker and the Python venv tool
echo "--> Installing Mosquitto and Python's venv tool..."
sudo apt-get install mosquitto mosquitto-clients python3-venv -y

# 3. Enable the Mosquitto service to start on boot
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
echo "--> Mosquitto MQTT Broker installed and enabled."

# 4. Create a Python virtual environment in a folder named '.venv'
echo "--> Creating Python virtual environment..."
python3 -m venv .venv

# 5. Activate the virtual environment and install packages with pip
echo "--> Activating environment and installing Python libraries..."
source .venv/bin/activate
pip install PySide6 paho-mqtt zeroconf
deactivate # Deactivate after installation is complete

echo ""
echo "--- Setup Complete! ---"
echo "A virtual environment has been created in the '.venv' folder."
echo ""
echo "TO RUN YOUR APP:"
echo "1. Create the 'device_role.json' file for your device."
echo "2. Use the ./run.sh script to start the application."
