#!/usr/bin/env bash
# exit on error
set -o errexit

# 1. Install Python packages from requirements.txt
pip install -r requirements.txt

# 2. Install system font utilities
apt-get update && apt-get install -y fontconfig

# 3. Create a directory for our custom font
mkdir -p /usr/share/fonts/truetype/myanmar/

# 4. Copy your font file from your project's 'fonts' folder to the system folder
cp fonts/Pyidaungsu-Regular.ttf /usr/share/fonts/truetype/myanmar/

# 5. Refresh the system font cache so Kaleido can find it
echo "Refreshing font cache..."
fc-cache -fv