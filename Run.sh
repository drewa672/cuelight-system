#!/bin/bash

# This script activates the virtual environment and runs the Python app.

# Get the directory where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Activate the virtual environment
source "$DIR/.venv/bin/activate"

# Run the Python application, passing along any arguments like --fullscreen
python "$DIR/main_app.py" "$@"

# The environment deactivates automatically when the script finishes.

