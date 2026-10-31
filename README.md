
## Windows EXE installer

End users install the application from `SystemResourceMonitor-Setup.exe`; Python is not needed on the target computer. The installer includes the desktop monitor and the Bluetooth agent. To monitor a remote computer, install the same package on that computer and launch **Monitor Agent** from the Start menu, then type the code that the monitoring PC shows under **Connect device**.

Press **F11** or click **Fullscreen** to cover the entire display. Press **Esc** or click **Windowed** to return.

To create the installer from source on a Windows build machine:

1. Install 64-bit Python 3.12 and Inno Setup 6.
2. Run `python -m pip install -r requirements-build.txt`.
3. Run `powershell -ExecutionPolicy Bypass -File .\build_windows.ps1`.
4. Find `release\SystemResourceMonitor-Setup.exe`.

The build creates both EXE applications under `dist`. Inno Setup combines them into the installable setup program. The target computer does not need Python.

## Remote monitoring over Wi-Fi / LAN

The PC and the device being measured must be on the same local network. In the monitor app click **Connect device**: a random 5-digit code appears. Enter that code on the other device — in the Android app, with `srm-agent` on a Raspberry Pi, or in **Monitor Agent** on another Windows PC (`python bluetooth_agent.py` while developing). The device finds the PC with a UDP broadcast (port 47821), connects over TCP (port 47820), and proves it knows the code. Five wrong codes in a row generate a new code; **New code** does the same manually. The agent shares CPU, memory, and process readings. Remote GPU metrics are not currently available.

The installer adds Windows Firewall rules for these two ports on Private and Domain networks. If Windows marks your Wi-Fi as a Public network, switch it to Private or allow the ports yourself. If your router blocks broadcasts, the agents also accept the PC's IP address directly (shown in the code window).

## Raspberry Pi and Android agents

Platform-specific companion agents are in [`agents/`](agents/README.md). Update the Windows installer, Raspberry Pi agent, and Android APK together; the verification handshake requires the current protocol version. The Raspberry Pi agent runs as a systemd service and reports system CPU, memory, and top processes. The Android companion app reports system CPU and memory. Android restricts third-party apps from reading other apps' process details, so its process list contains only the agent app. Build the Android APK with Android Studio/Gradle and install it on the phone, then enter the code shown on the PC in the app.
