package org.systemresmonitor.agent

import android.app.ActivityManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.AppOpsManager
import android.app.Service
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Debug
import android.os.IBinder
import android.os.Process
import android.os.SystemClock
import android.system.Os
import android.system.OsConstants
import org.json.JSONArray
import org.json.JSONObject
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.EOFException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.net.SocketTimeoutException
import java.nio.charset.StandardCharsets
import java.security.MessageDigest

/**
 * Connects to the Windows monitor over the local network (Wi-Fi / LAN).
 *
 * The PC shows a 5-digit code. The user types it in [MainActivity]; this service
 * broadcasts a discovery request containing a hash of the code on UDP 47821, the PC
 * answers with its TCP port, and the service connects, sends the code, and then
 * answers the PC's sample requests until the PC disconnects or the user stops it.
 */
class MonitorAgentService : Service() {
    @Volatile private var worker: Thread? = null
    @Volatile private var socket: Socket? = null
    @Volatile private var stopping = false
    @Volatile private var generation = 0
    @Volatile private var statusText = "Agent stopped"

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val code = intent?.getStringExtra(EXTRA_CODE).orEmpty()
        val host = intent?.getStringExtra(EXTRA_HOST)?.trim().orEmpty()
        statusText = "Searching for the PC..."
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, buildNotification(),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIFICATION_ID, buildNotification())
        }
        if (!isValidCode(code)) {
            publishStatus("Enter the 5-digit code shown on the PC.", connected = false)
            stopSelf()
            return START_NOT_STICKY
        }
        // A new code replaces any running connection.
        val runId = ++generation
        closeSocket()
        worker?.interrupt()
        stopping = false
        worker = Thread({ run(code, host, runId) }, "monitor-network-agent").also { it.start() }
        return START_NOT_STICKY
    }

    private fun run(code: String, host: String, runId: Int) {
        fun current() = runId == generation && !stopping
        try {
            val target = if (host.isNotEmpty()) {
                publishStatus("Connecting to $host...", connected = false)
                InetSocketAddress(host, TCP_PORT) to host
            } else {
                publishStatus("Searching the network for the PC with code $code...", connected = false)
                findPc(code, runId) ?: throw IllegalStateException(
                    "No PC with that code was found. Check the code, keep the PC's " +
                        "'Connect device' window open, and use the same Wi-Fi as the PC.")
            }
            if (!current()) return
            val sock = Socket()
            socket = sock
            sock.connect(target.first, 10_000)
            sock.soTimeout = 10_000
            val reader = DataInputStream(sock.getInputStream())
            val writer = DataOutputStream(sock.getOutputStream())
            writeFrame(writer, JSONObject()
                .put("type", "hello")
                .put("protocol", PROTOCOL)
                .put("code", code)
                .put("name", Build.MODEL ?: "Android device"))
            val reply = readFrame(reader)
            when (reply.optString("type")) {
                "authorized" -> Unit
                "auth_failed" -> throw IllegalStateException(
                    "The PC rejected the code. Check the code shown on the PC.")
                else -> throw IllegalStateException(
                    reply.optString("message").ifEmpty { "The PC refused the connection." })
            }
            val pcName = reply.optString("name").ifEmpty { target.second }
            publishStatus("Connected to $pcName", connected = true)
            sock.soTimeout = 0
            while (current()) {
                val request = try { readFrame(reader) } catch (_: EOFException) { break }
                if (request.optString("type") != "sample") break
                writeFrame(writer, sample())
            }
            if (current()) publishStatus("The PC ended the connection.", connected = false)
        } catch (exc: Exception) {
            if (current()) {
                publishStatus("Connection failed: ${exc.message ?: exc.javaClass.simpleName}",
                    connected = false)
            }
        } finally {
            if (current()) {
                closeSocket()
                stopSelf()
            }
        }
    }

    /** UDP broadcast discovery. Returns the PC's TCP address and name, or null. */
    private fun findPc(code: String, runId: Int): Pair<InetSocketAddress, String>? {
        val request = JSONObject()
            .put("type", "discover")
            .put("protocol", PROTOCOL)
            .put("code_hash", codeHash(code))
            .toString().toByteArray(StandardCharsets.UTF_8)
        DatagramSocket().use { udp ->
            udp.broadcast = true
            udp.soTimeout = 500
            val buffer = ByteArray(2048)
            val deadline = SystemClock.elapsedRealtime() + DISCOVERY_TIMEOUT_MS
            var nextSend = 0L
            while (SystemClock.elapsedRealtime() < deadline && runId == generation && !stopping) {
                if (SystemClock.elapsedRealtime() >= nextSend) {
                    for (address in broadcastAddresses()) {
                        try {
                            udp.send(DatagramPacket(request, request.size, address, DISCOVERY_PORT))
                        } catch (_: Exception) { }
                    }
                    nextSend = SystemClock.elapsedRealtime() + 1_000
                }
                val packet = DatagramPacket(buffer, buffer.size)
                try {
                    udp.receive(packet)
                } catch (_: SocketTimeoutException) {
                    continue
                }
                val reply = try {
                    JSONObject(String(packet.data, 0, packet.length, StandardCharsets.UTF_8))
                } catch (_: Exception) { continue }
                if (reply.optString("type") == "offer" && reply.optInt("protocol") == PROTOCOL) {
                    val port = reply.optInt("port", TCP_PORT)
                    val name = reply.optString("name").ifEmpty { packet.address.hostAddress ?: "PC" }
                    return InetSocketAddress(packet.address, port) to name
                }
            }
        }
        return null
    }

    private fun broadcastAddresses(): List<InetAddress> {
        val result = mutableListOf<InetAddress>(InetAddress.getByName("255.255.255.255"))
        try {
            for (networkInterface in NetworkInterface.getNetworkInterfaces()) {
                if (!networkInterface.isUp || networkInterface.isLoopback) continue
                for (address in networkInterface.interfaceAddresses) {
                    val broadcast = address.broadcast
                    if (address.address is Inet4Address && broadcast != null) result += broadcast
                }
            }
        } catch (_: Exception) { }
        return result.distinct()
    }

    private fun buildNotification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(
            CHANNEL_ID, "Monitor agent", NotificationManager.IMPORTANCE_LOW))
        return Notification.Builder(this, CHANNEL_ID).setContentTitle("System monitor agent")
            .setContentText(statusText)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setOngoing(true)
            .build()
    }

    private fun publishStatus(text: String, connected: Boolean) {
        statusText = text
        currentStatus = text
        isConnected = connected
        try {
            getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, buildNotification())
        } catch (_: Exception) { }
        sendBroadcast(Intent(ACTION_STATUS).setPackage(packageName)
            .putExtra(EXTRA_STATUS, text)
            .putExtra(EXTRA_CONNECTED, connected))
    }

    private fun sample(): JSONObject {
        val manager = getSystemService(ActivityManager::class.java)
        val info = ActivityManager.MemoryInfo().also { manager.getMemoryInfo(it) }
        val totalMem = info.totalMem.coerceAtLeast(1)
        val memory = 100.0 * (info.totalMem - info.availMem) / totalMem

        // 1) Shizuku: real CPU usage and the full process list (shell privileges).
        val shell = if (ShizukuShell.hasPermission()) shellSample(totalMem) else null

        // 2) Otherwise: /proc/stat if this device still allows it, else a clock-speed estimate.
        val cpuSource: String
        val cpu: Double
        if (shell != null) {
            cpu = shell.first; cpuSource = "shizuku"
        } else {
            val direct = procStatCpuPercent()
            val estimate = if (direct == null) frequencyEstimatePercent() else null
            cpu = direct ?: estimate ?: 0.0
            cpuSource = when {
                direct != null -> "proc_stat"
                estimate != null -> "frequency_estimate"
                else -> "unavailable"
            }
        }

        val scope: String
        val processes = JSONArray()
        val recent = if (shell == null || shell.second.isEmpty()) recentApps() else emptyList()
        when {
            shell != null && shell.second.isNotEmpty() -> {
                scope = "shizuku"; shell.second.forEach { processes.put(it) }
            }
            recent.isNotEmpty() -> {
                scope = "recent_apps"; recent.forEach { processes.put(it) }
            }
            else -> {
                scope = "agent_app_only"
                val pssKb = Debug.getPss().toDouble()
                processes.put(JSONObject()
                    .put("pid", Process.myPid())
                    .put("name", applicationInfo.loadLabel(packageManager).toString())
                    .put("cpu_percent_normalized", ownProcessCpuPercent())
                    .put("memory_percent", 100.0 * pssKb * 1024.0 / totalMem))
            }
        }
        return JSONObject()
            .put("type", "sample")
            .put("timestamp", System.currentTimeMillis() / 1000.0)
            .put("cpu", cpu)
            .put("cpu_source", cpuSource)
            .put("memory", memory)
            .put("gpu", gpuBusyPercent() ?: JSONObject.NULL)
            .put("gpu_memory", gpuMemoryPercent(totalMem) ?: JSONObject.NULL)
            .put("process_scope", scope)
            .put("agent_note", accessNote(shell))
            .put("processes", processes)
    }

    /**
     * Reads /proc/stat and every /proc/<pid>/stat twice, one second apart, as the shell
     * user. Returns (system CPU %, top 20 processes by CPU) or null if Shizuku failed.
     */
    private fun shellSample(totalMem: Long): Pair<Double, List<JSONObject>>? {
        val output = ShizukuShell.run(
            "head -n 1 /proc/stat; cat /proc/[0-9]*/stat 2>/dev/null; echo '@@'; sleep 1; " +
                "head -n 1 /proc/stat; cat /proc/[0-9]*/stat 2>/dev/null") ?: return null
        val halves = output.split("@@")
        if (halves.size != 2) return null
        val first = parseShellSnapshot(halves[0])
        val second = parseShellSnapshot(halves[1])
        val cpuBefore = first.first ?: return null
        val cpuAfter = second.first ?: return null
        val totalDelta = (cpuAfter.first - cpuBefore.first).coerceAtLeast(1)
        val idleDelta = cpuAfter.second - cpuBefore.second
        val systemCpu = (100.0 * (totalDelta - idleDelta) / totalDelta).coerceIn(0.0, 100.0)

        val pageSize = try { Os.sysconf(OsConstants._SC_PAGESIZE) } catch (_: Exception) { 4096L }
        data class Row(val pid: Int, val comm: String, val cpu: Double, val mem: Double)
        val rows = second.second.mapNotNull { (pid, now) ->
            val before = first.second[pid] ?: return@mapNotNull null
            // Share of all CPU time across all cores during the interval (matches the PC's normalized %).
            val cpu = 100.0 * (now.ticks - before.ticks).coerceAtLeast(0) / totalDelta
            Row(pid, now.comm, cpu, 100.0 * now.rssPages * pageSize / totalMem)
        }.sortedWith(compareByDescending<Row> { it.cpu }.thenByDescending { it.mem }).take(20)

        val names = processNames(rows.map { it.pid })
        return systemCpu to rows.map { row ->
            JSONObject()
                .put("pid", row.pid)
                .put("name", names[row.pid] ?: row.comm)
                .put("cpu_percent_normalized", row.cpu)
                .put("memory_percent", row.mem)
        }
    }

    /** Why the full process list is (not) available, shown on the PC. */
    private fun accessNote(shell: Pair<Double, List<JSONObject>>?): String {
        val shizuku = when {
            shell != null && shell.second.isNotEmpty() -> "Shizuku OK"
            shell != null -> "Shizuku ran but listed no processes"
            ShizukuShell.hasPermission() -> "Shizuku error: ${ShizukuShell.lastError ?: "unknown"}"
            ShizukuShell.isRunning() -> "Shizuku not allowed for this app"
            else -> "Shizuku not running"
        }
        val usage = if (hasUsageAccess(this)) "Usage access on" else "Usage access off"
        return "$shizuku, $usage"
    }

    // GPU load files differ by chip: Adreno (Snapdragon) uses kgsl, Mali (Exynos/Tensor/Dimensity) uses mali/gpu.
    private val gpuBusyFiles = listOf(
        "/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage",
        "/sys/class/kgsl/kgsl-3d0/gpubusy",
        "/sys/kernel/gpu/gpu_busy",
        "/sys/class/misc/mali0/device/utilization",
        "/sys/devices/platform/mali.0/utilization",
    )
    private val gpuMemoryFile = "/sys/class/kgsl/kgsl/page_alloc"

    private fun readSysFile(path: String): String? {
        val direct = try { java.io.File(path).readText().trim() } catch (_: Exception) { null }
        if (!direct.isNullOrEmpty()) return direct
        if (!ShizukuShell.hasPermission()) return null
        return ShizukuShell.run("cat $path 2>/dev/null", timeoutSeconds = 2)?.trim()?.ifEmpty { null }
    }

    private fun gpuBusyPercent(): Double? {
        for (path in gpuBusyFiles) {
            val text = readSysFile(path) ?: continue
            val numbers = Regex("\\d+(\\.\\d+)?").findAll(text).map { it.value.toDouble() }.toList()
            val value = when {
                path.endsWith("gpubusy") && numbers.size >= 2 ->
                    if (numbers[1] > 0) 100.0 * numbers[0] / numbers[1] else 0.0
                numbers.isNotEmpty() -> numbers[0]
                else -> continue
            }
            return value.coerceIn(0.0, 100.0)
        }
        return null
    }

    private fun gpuMemoryPercent(totalMem: Long): Double? {
        val bytes = readSysFile(gpuMemoryFile)?.trim()?.toLongOrNull() ?: return null
        return (100.0 * bytes / totalMem).coerceIn(0.0, 100.0)
    }

    private class ProcStat(val comm: String, val ticks: Long, val rssPages: Long)

    /** Parses "cpu ..." (total, idle) and the per-process stat lines from one snapshot. */
    private fun parseShellSnapshot(text: String): Pair<Pair<Long, Long>?, Map<Int, ProcStat>> {
        var cpu: Pair<Long, Long>? = null
        val processes = HashMap<Int, ProcStat>()
        for (line in text.lineSequence()) {
            if (line.startsWith("cpu ")) {
                val fields = line.trim().split(Regex("\\s+")).drop(1).mapNotNull(String::toLongOrNull)
                val idle = fields.getOrElse(3) { 0L } + fields.getOrElse(4) { 0L }
                cpu = fields.sum() to idle
                continue
            }
            val open = line.indexOf('(')
            val close = line.lastIndexOf(')')
            if (open <= 0 || close <= open) continue
            val pid = line.substring(0, open).trim().toIntOrNull() ?: continue
            val rest = line.substring(close + 1).trim().split(' ')
            // rest[0] is field 3 (state): utime=14, stime=15, rss=24 -> indexes 11, 12, 21.
            val utime = rest.getOrNull(11)?.toLongOrNull() ?: continue
            val stime = rest.getOrNull(12)?.toLongOrNull() ?: continue
            val rss = rest.getOrNull(21)?.toLongOrNull() ?: 0L
            processes[pid] = ProcStat(line.substring(open + 1, close), utime + stime, rss)
        }
        return cpu to processes
    }

    private val labelCache = HashMap<String, String?>()

    /** Full command lines for the given pids, shown as app names where possible. */
    private fun processNames(pids: List<Int>): Map<Int, String> {
        if (pids.isEmpty()) return emptyMap()
        val output = ShizukuShell.run(
            "for p in ${pids.joinToString(" ")}; do " +
                "printf '%s\\t' \$p; tr '\\0' ' ' < /proc/\$p/cmdline 2>/dev/null; echo; done",
            timeoutSeconds = 3) ?: return emptyMap()
        val names = HashMap<Int, String>()
        for (line in output.lineSequence()) {
            val tab = line.indexOf('\t')
            if (tab <= 0) continue
            val pid = line.substring(0, tab).toIntOrNull() ?: continue
            val command = line.substring(tab + 1).trim()
            if (command.isEmpty()) continue
            val first = command.substringBefore(' ')
            val pkg = first.substringBefore(':')
            val label = if (pkg.contains('.') && !pkg.startsWith("/")) appLabel(pkg) else null
            names[pid] = when {
                label != null && first.contains(':') -> "$label (${first.substringAfter(':')})"
                label != null -> label
                first.startsWith("/") -> first.substringAfterLast('/')
                else -> first
            }
        }
        return names
    }

    private fun appLabel(packageName: String): String? = labelCache.getOrPut(packageName) {
        try {
            packageManager.getApplicationLabel(packageManager.getApplicationInfo(packageName, 0)).toString()
        } catch (_: Exception) { null }
    }

    /** Apps used in the last hour (needs "Usage access"); no per-app CPU/memory is available. */
    private fun recentApps(): List<JSONObject> {
        if (!hasUsageAccess(this)) return emptyList()
        val usage = getSystemService(UsageStatsManager::class.java) ?: return emptyList()
        val now = System.currentTimeMillis()
        val stats = try {
            usage.queryUsageStats(UsageStatsManager.INTERVAL_BEST, now - 60 * 60_000L, now)
        } catch (_: Exception) { return emptyList() }
        return stats.filter { it.lastTimeUsed >= now - 60 * 60_000L && it.totalTimeInForeground > 0 }
            .groupBy { it.packageName }
            .map { (_, list) -> list.maxBy { it.lastTimeUsed } }
            .sortedByDescending { it.lastTimeUsed }
            .take(20)
            .map { stat ->
                val minutes = ((now - stat.lastTimeUsed) / 60_000L).coerceAtLeast(0)
                val label = appLabel(stat.packageName) ?: stat.packageName
                JSONObject()
                    .put("pid", JSONObject.NULL)
                    .put("name", if (minutes == 0L) "$label — in use now" else "$label — used $minutes min ago")
                    .put("cpu_percent_normalized", JSONObject.NULL)
                    .put("memory_percent", JSONObject.NULL)
            }
    }

    /** Works only on old Android versions or devices that still expose /proc/stat to apps. */
    private fun procStatCpuPercent(): Double? {
        val before = readCpuCounters() ?: return null
        Thread.sleep(450)
        val after = readCpuCounters() ?: return null
        val totalDelta = after.first - before.first
        val idleDelta = after.second - before.second
        if (totalDelta <= 0) return null
        return (100.0 * (totalDelta - idleDelta) / totalDelta).coerceIn(0.0, 100.0)
    }

    private fun readCpuCounters(): Pair<Long, Long>? = try {
        val fields = java.io.File("/proc/stat").useLines { lines ->
            lines.first().trim().split(Regex("\\s+")).drop(1).map(String::toLong)
        }
        val total = fields.sum()
        val idle = fields.getOrElse(3) { 0L } + fields.getOrElse(4) { 0L }
        total to idle
    } catch (_: Exception) { null }

    /**
     * Approximate load from how fast each core is clocked relative to its range.
     * This is not real utilization, but it rises and falls with load.
     */
    private fun frequencyEstimatePercent(): Double? {
        val cores = java.io.File("/sys/devices/system/cpu").listFiles { file ->
            file.name.matches(Regex("cpu\\d+"))
        } ?: return null
        val ratios = cores.mapNotNull { core ->
            fun read(name: String) = try {
                java.io.File(core, "cpufreq/$name").readText().trim().toLong()
            } catch (_: Exception) { null }
            val current = read("scaling_cur_freq") ?: return@mapNotNull null
            val min = read("cpuinfo_min_freq") ?: return@mapNotNull null
            val max = read("cpuinfo_max_freq") ?: return@mapNotNull null
            if (max <= min) null else ((current - min).toDouble() / (max - min)).coerceIn(0.0, 1.0)
        }
        if (ratios.isEmpty()) return null
        Thread.sleep(300) // keep the sampling cadence similar to the other paths
        return 100.0 * ratios.average()
    }

    private var lastProcessCpuMs = Process.getElapsedCpuTime()
    private var lastProcessWallMs = SystemClock.elapsedRealtime()

    private fun ownProcessCpuPercent(): Double {
        val nowCpu = Process.getElapsedCpuTime()
        val nowWall = SystemClock.elapsedRealtime()
        val deltaCpu = (nowCpu - lastProcessCpuMs).coerceAtLeast(0)
        val deltaWall = (nowWall - lastProcessWallMs).coerceAtLeast(1)
        lastProcessCpuMs = nowCpu
        lastProcessWallMs = nowWall
        val cpuCount = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
        return (100.0 * deltaCpu / (deltaWall * cpuCount)).coerceIn(0.0, 100.0)
    }

    private fun readFrame(input: DataInputStream): JSONObject {
        val size = input.readInt()
        require(size in 1..MAX_FRAME_SIZE) { "Invalid frame size" }
        val bytes = ByteArray(size)
        input.readFully(bytes)
        return JSONObject(String(bytes, StandardCharsets.UTF_8))
    }

    private fun writeFrame(output: DataOutputStream, payload: JSONObject) {
        val bytes = payload.toString().toByteArray(StandardCharsets.UTF_8)
        require(bytes.size <= MAX_FRAME_SIZE) { "Frame too large" }
        output.writeInt(bytes.size)
        output.write(bytes)
        output.flush()
    }

    private fun closeSocket() {
        try { socket?.close() } catch (_: Exception) { }
        socket = null
    }

    override fun onDestroy() {
        stopping = true
        closeSocket()
        worker?.interrupt()
        worker = null
        if (isConnected) {
            currentStatus = "Agent stopped"
            isConnected = false
            sendBroadcast(Intent(ACTION_STATUS).setPackage(packageName)
                .putExtra(EXTRA_STATUS, "Agent stopped")
                .putExtra(EXTRA_CONNECTED, false))
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val CHANNEL_ID = "monitor_agent"
        private const val NOTIFICATION_ID = 1001
        private const val MAX_FRAME_SIZE = 64 * 1024
        private const val PROTOCOL = 3
        const val TCP_PORT = 47820
        private const val DISCOVERY_PORT = 47821
        private const val DISCOVERY_TIMEOUT_MS = 6_000L

        const val EXTRA_CODE = "code"
        const val EXTRA_HOST = "host"
        const val EXTRA_STATUS = "status"
        const val EXTRA_CONNECTED = "connected"
        const val ACTION_STATUS = "org.systemresmonitor.agent.STATUS"

        @Volatile var currentStatus: String? = null
        @Volatile var isConnected = false

        fun hasUsageAccess(context: Context): Boolean {
            val appOps = context.getSystemService(AppOpsManager::class.java) ?: return false
            val mode = if (Build.VERSION.SDK_INT >= 29) {
                appOps.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                    Process.myUid(), context.packageName)
            } else {
                @Suppress("DEPRECATION")
                appOps.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                    Process.myUid(), context.packageName)
            }
            return mode == AppOpsManager.MODE_ALLOWED
        }

        fun isValidCode(code: String) = code.length == 5 && code.all { it in '0'..'9' }

        /** Must match code_hash() in monitor/remote_link.py. */
        fun codeHash(code: String): String =
            MessageDigest.getInstance("SHA-256")
                .digest("srm-pair-v3:$code".toByteArray(StandardCharsets.US_ASCII))
                .joinToString("") { "%02x".format(it) }
    }
}
