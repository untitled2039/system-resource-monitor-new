# Raspberry Pi agent

The Pi connects to the Windows monitor over the local network (Wi-Fi or LAN). The PC and the Pi must be on the same network.

Install once from the project folder on the Pi:

```bash
cd agents/raspberry_pi
sudo sh ./install.sh
```

The installer adds `psutil`, copies the agent to `/opt/system-resource-monitor-agent`, and creates the `srm-agent` command. It also removes the old Bluetooth background service if an earlier version installed one.

## Connecting

1. In the Windows app, click **Connect device**. A 5-digit code appears.
2. On the Pi, run `srm-agent` and type that code.

The Pi finds the PC with a UDP broadcast and connects over TCP. You can also pass the code directly: `srm-agent --code 12345`. If your network blocks broadcasts, give the PC's IP address (shown in the code window): `srm-agent --host 192.168.0.10`.

Keep the command running while monitoring; press Ctrl+C to stop. When the PC disconnects, the agent asks for a new code.

The agent returns CPU, memory, and the top 20 Linux processes. GPU fields are currently empty.
