package org.systemresmonitor.agent

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputFilter
import android.text.InputType
import android.view.Gravity
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import rikka.shizuku.Shizuku

class MainActivity : ComponentActivity() {
    private lateinit var status: TextView
    private lateinit var codeInput: EditText
    private lateinit var hostInput: EditText
    private lateinit var accessStatus: TextView

    private val shizukuPermissionListener =
        Shizuku.OnRequestPermissionResultListener { _, _ -> runOnUiThread { refreshAccessStatus() } }
    private val shizukuBinderListener =
        Shizuku.OnBinderReceivedListener { runOnUiThread { refreshAccessStatus() } }
    private val shizukuDeadListener =
        Shizuku.OnBinderDeadListener { runOnUiThread { refreshAccessStatus() } }

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            status.text = intent?.getStringExtra(MonitorAgentService.EXTRA_STATUS).orEmpty()
        }
    }

    // Notifications are optional; connect either way once the user has answered.
    private val notificationPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { startAgent() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
        }
        layout.addView(TextView(this).apply {
            text = "System Resource Monitor"
            textSize = 22f
        })
        layout.addView(TextView(this).apply {
            text = "On the PC, click \"Connect device\" and enter the 5-digit code it shows. " +
                "The phone and the PC must be on the same Wi-Fi. " +
                "Android only exposes this app's own process to the process list."
            textSize = 15f
            setPadding(0, 20, 0, 20)
        })
        codeInput = EditText(this).apply {
            hint = "5-digit code"
            inputType = InputType.TYPE_CLASS_NUMBER
            filters = arrayOf(InputFilter.LengthFilter(5))
            textSize = 32f
            gravity = Gravity.CENTER
            letterSpacing = 0.3f
        }
        layout.addView(codeInput)
        hostInput = EditText(this).apply {
            hint = "PC IP address (optional, if the PC is not found)"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            textSize = 14f
        }
        layout.addView(hostInput)
        layout.addView(Button(this).apply {
            text = "Connect"
            setOnClickListener { beginConnect() }
        })
        layout.addView(Button(this).apply {
            text = "Disconnect"
            setOnClickListener {
                stopService(Intent(this@MainActivity, MonitorAgentService::class.java))
                status.text = "Agent stopped"
            }
        })
        status = TextView(this).apply {
            text = "Not connected"
            textSize = 16f
            setPadding(0, 24, 0, 0)
        }
        layout.addView(status)

        layout.addView(TextView(this).apply {
            text = "CPU and process access"
            textSize = 18f
            setPadding(0, 40, 0, 8)
        })
        layout.addView(TextView(this).apply {
            text = "Android blocks apps from reading total CPU usage and other apps' processes. " +
                "With Shizuku running, the agent reads real CPU usage and all processes. " +
                "Without it, CPU is estimated from clock speed and only recently used apps are listed " +
                "(requires Usage access)."
            textSize = 14f
        })
        accessStatus = TextView(this).apply { textSize = 15f; setPadding(0, 12, 0, 8) }
        layout.addView(accessStatus)
        layout.addView(Button(this).apply {
            text = "Allow Shizuku"
            setOnClickListener { requestShizuku() }
        })
        layout.addView(Button(this).apply {
            text = "Open Usage access settings"
            setOnClickListener {
                try {
                    startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
                } catch (_: Exception) {
                    startActivity(Intent(Settings.ACTION_SETTINGS))
                }
            }
        })
        setContentView(android.widget.ScrollView(this).apply { addView(layout) })

        Shizuku.addRequestPermissionResultListener(shizukuPermissionListener)
        Shizuku.addBinderReceivedListenerSticky(shizukuBinderListener)
        Shizuku.addBinderDeadListener(shizukuDeadListener)
    }

    override fun onResume() {
        super.onResume()
        refreshAccessStatus()
    }

    override fun onDestroy() {
        Shizuku.removeRequestPermissionResultListener(shizukuPermissionListener)
        Shizuku.removeBinderReceivedListener(shizukuBinderListener)
        Shizuku.removeBinderDeadListener(shizukuDeadListener)
        super.onDestroy()
    }

    private fun refreshAccessStatus() {
        val shizuku = when {
            ShizukuShell.hasPermission() -> "Shizuku: allowed - real CPU and full process list"
            ShizukuShell.isRunning() -> "Shizuku: running, tap 'Allow Shizuku'"
            else -> "Shizuku: not running (install Shizuku and start it)"
        }
        val usage = if (MonitorAgentService.hasUsageAccess(this)) "Usage access: allowed"
        else "Usage access: not allowed"
        val error = ShizukuShell.lastError?.let { "\nLast Shizuku error: $it" } ?: ""
        accessStatus.text = "$shizuku\n$usage$error"
    }

    private fun requestShizuku() {
        if (!ShizukuShell.isRunning()) {
            accessStatus.text = "Shizuku is not running. Install the Shizuku app, start it with " +
                "Wireless debugging, then tap 'Allow Shizuku' again."
            return
        }
        try {
            if (Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) {
                refreshAccessStatus()
            } else if (Shizuku.shouldShowRequestPermissionRationale()) {
                accessStatus.text = "Shizuku permission was denied permanently. " +
                    "Allow System Monitor Agent in the Shizuku app."
            } else {
                Shizuku.requestPermission(SHIZUKU_REQUEST_CODE)
            }
        } catch (exc: Exception) {
            accessStatus.text = "Shizuku error: ${exc.message}"
        }
    }

    companion object {
        private const val SHIZUKU_REQUEST_CODE = 7101
    }

    override fun onStart() {
        super.onStart()
        MonitorAgentService.currentStatus?.let { status.text = it }
        val filter = IntentFilter(MonitorAgentService.ACTION_STATUS)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(statusReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(statusReceiver, filter)
        }
    }

    override fun onStop() {
        unregisterReceiver(statusReceiver)
        super.onStop()
    }

    private fun beginConnect() {
        val code = codeInput.text.toString().trim()
        if (!MonitorAgentService.isValidCode(code)) {
            status.text = "Enter exactly 5 digits."
            return
        }
        getSystemService(InputMethodManager::class.java)
            ?.hideSoftInputFromWindow(codeInput.windowToken, 0)
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            startAgent()
        }
    }

    private fun startAgent() {
        val code = codeInput.text.toString().trim()
        if (!MonitorAgentService.isValidCode(code)) return
        val intent = Intent(this, MonitorAgentService::class.java)
            .putExtra(MonitorAgentService.EXTRA_CODE, code)
            .putExtra(MonitorAgentService.EXTRA_HOST, hostInput.text.toString().trim())
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent) else startService(intent)
        status.text = "Searching for the PC..."
    }
}
