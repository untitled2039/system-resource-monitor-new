# Android agent

This companion app connects to the Windows monitor over the local network (Wi-Fi). It requires Android 8.0 or later, and the phone must be on the same Wi-Fi as the PC.

Build a debug APK by opening this folder in Android Studio, or from PowerShell in this directory with Android SDK 35 installed:

```powershell
.\gradlew.bat assembleDebug
```

The APK is written to `app/build/outputs/apk/debug/app-debug.apk`. Install it on the phone.

## Connecting

1. In the Windows app, click **Connect device**. A 5-digit code appears.
2. Open **System Monitor Agent** on the phone, type the code, and tap **Connect**.

The app finds the PC with a UDP broadcast and connects over TCP. If the PC is not found (some routers block broadcasts or isolate Wi-Fi clients), type the PC's IP address shown in the code window into the optional field. A foreground notification shows while the agent is connected; tap **Disconnect** to stop. Install this updated APK together with the updated Windows app; older versions used Bluetooth and cannot connect.

## CPU and process list

Android blocks ordinary apps from reading total CPU usage and other apps' processes. The agent uses the best source available:

| Setup on the phone | CPU | Top Processes |
|---|---|---|
| **Shizuku** running and allowed | Real usage (`/proc/stat`) | All processes with CPU and memory |
| **Usage access** allowed (no Shizuku) | Clock-speed estimate | Apps used in the last hour (no CPU/memory per app) |
| Nothing | Clock-speed estimate | This agent app only |

**Shizuku:** install the Shizuku app, start it with *Wireless debugging* (Developer options), then tap **Allow Shizuku** in this app. Shizuku must be started again after each reboot.

**Usage access:** tap **Open Usage access settings** and turn it on for System Monitor Agent.

The PC shows "(CPU: clock-speed estimate)" next to the device name when the estimate is in use.
