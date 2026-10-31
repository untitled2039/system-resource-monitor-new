# Companion agents

The Windows monitor connects to these agents over the local network (Wi-Fi / LAN). In the Windows app click **Connect device** to show a 5-digit code, then enter that code on the device you want to monitor. The PC and the device must be on the same network.

## Raspberry Pi

Copy or clone this repository onto the Pi, then run:

```bash
cd agents/raspberry_pi
sudo sh ./install.sh
srm-agent
```

Type the code shown on the PC. The agent reports system CPU, memory, and the top 20 processes. GPU metrics are not currently provided. See [raspberry_pi/README.md](raspberry_pi/README.md) for options such as `--host`.

## Android

Open `agents/android` in Android Studio with Android SDK 35 installed and build the **app** debug APK, or run `.\gradlew.bat assembleDebug` from PowerShell in that directory. Install `app/build/outputs/apk/debug/app-debug.apk` on the phone, open **System Monitor Agent**, type the code shown on the PC, and tap **Connect**. A foreground notification shows while the agent is connected.

The app reports Android-wide CPU and memory usage. Android prevents ordinary third-party apps from reading other apps' process details, so **Top Processes** contains only the monitor agent itself. GPU metrics are not currently provided.
