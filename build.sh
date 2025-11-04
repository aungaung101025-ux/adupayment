#!/usr/bin/env bash
# exit on error
set -o errexit

# 1. Install Python packages from requirements.txt
pip install -r requirements.txt

# 2. Create a local font directory in the user's home (which is writeable)
echo "Creating local font directory at ~/.fonts"
mkdir -p ~/.fonts

# 3. Copy your font file from your project's 'fonts' folder to the local font dir
echo "Copying Pyidaungsu-Regular.ttf to ~/.fonts/"
cp fonts/Pyidaungsu-Regular.ttf ~/.fonts/

# 4. Refresh the font cache (fc-cache should be available in the build env)
echo "Refreshing font cache..."
fc-cache -fv

echo "Build script completed."