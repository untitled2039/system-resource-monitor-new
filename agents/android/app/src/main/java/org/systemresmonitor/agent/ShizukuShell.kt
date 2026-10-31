package org.systemresmonitor.agent

import android.content.pm.PackageManager
import rikka.shizuku.Shizuku
import java.util.concurrent.TimeUnit

/**
 * Runs shell commands with ADB-shell privileges through Shizuku.
 *
 * Normal apps cannot read /proc/stat or other apps' processes. The shell user can,
 * so when Shizuku is running and has granted this app permission, the agent uses it
 * to read real CPU usage and the full process list.
 */
object ShizukuShell {
    /** Last failure from [run], shown in the app and on the PC for troubleshooting. */
    @Volatile var lastError: String? = null
        private set

    /** Shizuku app is installed and its service is running. */
    fun isRunning(): Boolean = try {
        Shizuku.pingBinder() && !Shizuku.isPreV11()
    } catch (_: Throwable) {
        false
    }

    fun hasPermission(): Boolean = try {
        isRunning() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    } catch (_: Throwable) {
        false
    }

    /** Runs `sh -c command` as the shell user; returns stdout, or null on any failure. */
    fun run(command: String, timeoutSeconds: Long = 6): String? {
        if (!hasPermission()) return null
        return try {
            // Shizuku.newProcess is not public in API 13, but is still present and is the
            // simplest way to run a one-off command without a bound UserService.
            val method = Shizuku::class.java.getDeclaredMethod(
                "newProcess", Array<String>::class.java, Array<String>::class.java, String::class.java)
            method.isAccessible = true
            val process = method.invoke(null, arrayOf("sh", "-c", command), null, null) as Process
            val output = StringBuilder()
            val reader = Thread {
                try {
                    process.inputStream.bufferedReader().use { output.append(it.readText()) }
                } catch (_: Exception) { }
            }
            reader.start()
            // Shizuku's remote process throws IllegalArgumentException from exitValue() while
            // running, which breaks Process.waitFor(timeout). Use the blocking waitFor() on a
            // helper thread and enforce the timeout ourselves.
            val waiter = Thread {
                try { process.waitFor() } catch (_: Exception) { }
            }
            waiter.start()
            waiter.join(TimeUnit.SECONDS.toMillis(timeoutSeconds))
            if (waiter.isAlive) {
                try { process.destroy() } catch (_: Exception) { }
                lastError = "command timed out"
                return null
            }
            reader.join(2_000)
            lastError = null
            output.toString()
        } catch (exc: Throwable) {
            val cause = (exc as? java.lang.reflect.InvocationTargetException)?.targetException ?: exc
            lastError = "${cause.javaClass.simpleName}: ${cause.message ?: ""}".trim()
            null
        }
    }
}
