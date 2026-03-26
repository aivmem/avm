#!/bin/bash
set -e
echo "Installing AVM daemon..."
# Install deps
pip install fusepy
# Create systemd service
mkdir -p ~/.config/systemd/user/
cp avm-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable avm-daemon
systemctl --user start avm-daemon
echo "Done. Check: systemctl --user status avm-daemon"
