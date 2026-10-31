#!/bin/sh
set -eu

AGENT_DIR="/opt/system-resource-monitor-agent"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo sh ./install.sh"
    exit 1
fi

# Remove the old Bluetooth background service if an earlier version installed it.
if [ -f /etc/systemd/system/system-resource-monitor-agent.service ]; then
    systemctl disable --now system-resource-monitor-agent.service || true
    rm -f /etc/systemd/system/system-resource-monitor-agent.service
    systemctl daemon-reload
fi

apt-get update
apt-get install -y python3-psutil
install -d "$AGENT_DIR"
install -m 0755 "$SCRIPT_DIR/agent.py" "$AGENT_DIR/agent.py"
ln -sf "$AGENT_DIR/agent.py" /usr/local/bin/srm-agent

echo
echo "Installed. On the PC click 'Connect device', then run on this Pi:"
echo "    srm-agent"
echo "and type the 5-digit code shown on the PC."
