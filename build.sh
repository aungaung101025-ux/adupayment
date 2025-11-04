#!/usr/bin/env bash
# exit on error
set -o errexit

# 1. Install Python packages
pip install -r requirements.txt

# 2. Create local font directory
echo "Creating local font directory at ~/.fonts"
mkdir -p ~/.fonts

# 3. Copy font to local dir
echo "Copying Pyidaungsu-Regular.ttf to ~/.fonts/"
cp fonts/Pyidaungsu-Regular.ttf ~/.fonts/

# 4. Refresh font cache
echo "Refreshing font cache..."
fc-cache -fv

echo "Build script completed."