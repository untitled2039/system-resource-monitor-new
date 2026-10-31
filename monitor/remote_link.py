"""Code-based remote monitoring over the local network (Wi-Fi / LAN).

The PC shows a random 5-digit code and waits. A remote agent (Android,
Raspberry Pi, or another Windows PC) enters that code, finds the PC with a
UDP broadcast on the local network, connects over TCP, and proves it knows
the code. After that the PC asks the agent for samples.

Frames on the TCP connection are a 4-byte big-endian length followed by a
UTF-8 JSON object (the same framing the earlier Bluetooth protocol used).

Handshake (protocol 3):
  agent -> UDP broadcast :47821  {"type":"discover","protocol":3,"code_hash":H}
  PC    -> UDP unicast reply      {"type":"offer","protocol":3,"port":47820,"name":PC}
  agent -> TCP :47820             {"type":"hello","protocol":3,"code":"12345","name":AGENT}
  PC    -> agent                  {"type":"authorized","protocol":3,"name":PC} | {"type":"auth_failed"}
  then repeatedly:  PC -> {"type":"sample"},  agent -> {"type":"sample", ...}

H = sha256("srm-pair-v3:" + code) as lowercase hex, so the code itself is not
broadcast in plain text.
"""
import hashlib
import hmac
import json
import platform
import secrets
import socket
import struct
import threading
import time

PROTOCOL = 3
TCP_PORT = 47820
DISCOVERY_PORT = 47821
MAX_FRAME_SIZE = 64 * 1024
MAX_FAILED_ATTEMPTS = 5


def code_hash(code):
    return hashlib.sha256(f"srm-pair-v3:{code}".encode("ascii")).hexdigest()


def new_code():
    return f"{secrets.randbelow(100000):05d}"


def is_valid_code(code):
    return isinstance(code, str) and len(code) == 5 and code.isascii() and code.isdigit()


def _receive_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("Remote device disconnected.")
        data.extend(chunk)
    return bytes(data)


def receive_frame(sock):
    size = struct.unpack("!I", _receive_exact(sock, 4))[0]
    if size <= 0 or size > MAX_FRAME_SIZE:
        raise ValueError("Remote device sent an invalid data frame.")
    return json.loads(_receive_exact(sock, size).decode("utf-8"))


def send_frame(sock, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME_SIZE:
        raise ValueError("Data frame is too large.")
    sock.sendall(struct.pack("!I", len(body)) + body)


def local_ipv4_addresses():
    """Best-effort list of this computer's LAN IPv4 addresses (for display)."""
    addresses = []
    try:
        import psutil
        for name, entries in psutil.net_if_addrs().items():
            for entry in entries:
                if entry.family == socket.AF_INET and not entry.address.startswith(("127.", "169.254.")):
                    addresses.append(entry.address)
    except Exception:
        pass
    if not addresses:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("10.255.255.255", 1))
            addresses.append(probe.getsockname()[0])
            probe.close()
        except OSError:
            pass
    return sorted(set(addresses))


class RemoteConnection:
    """An authorized connection to a remote agent. Used by the monitor loop."""

    def __init__(self, sock, name):
        self.sock = sock
        self.name = name
        self._lock = threading.Lock()
        self._closed = False

    def sample(self, timeout=8):
        with self._lock:
            if self._closed:
                raise ConnectionError("No remote device is connected.")
            self.sock.settimeout(timeout)
            send_frame(self.sock, {"type": "sample"})
            response = receive_frame(self.sock)
        if response.get("type") != "sample":
            raise RuntimeError("The remote agent returned an unexpected response.")
        return response

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            send_frame(self.sock, {"type": "bye"})
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


class PairingServer:
    """Show a code on the PC and wait for an agent to connect with it.

    Callbacks are called from background threads:
      on_code(code)          - a new code is active (initially and after regenerate)
      on_connected(conn)     - an agent authorized; the server stops itself
      on_error(message)      - the server could not start
      on_attempt_failed(n)   - a wrong code was received (n = failures so far)
    """

    def __init__(self, on_code=None, on_connected=None, on_error=None, on_attempt_failed=None):
        self.on_code = on_code
        self.on_connected = on_connected
        self.on_error = on_error
        self.on_attempt_failed = on_attempt_failed
        self.name = platform.node() or "PC"
        self.code = None
        self._failed = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._tcp = None
        self._udp = None

    def start(self):
        try:
            self._tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._tcp.bind(("0.0.0.0", TCP_PORT))
            self._tcp.listen(4)
            self._tcp.settimeout(0.5)
            self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp.bind(("0.0.0.0", DISCOVERY_PORT))
            self._udp.settimeout(0.5)
        except OSError as exc:
            self.stop()
            message = (f"Could not open network ports {TCP_PORT}/TCP and {DISCOVERY_PORT}/UDP: {exc}. "
                       "Close other copies of the monitor and try again.")
            if self.on_error:
                self.on_error(message)
            return False
        self.regenerate_code()
        threading.Thread(target=self._discovery_loop, daemon=True).start()
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return True

    def regenerate_code(self):
        with self._lock:
            self.code = new_code()
            self._failed = 0
            code = self.code
        if self.on_code:
            self.on_code(code)
        return code

    def stop(self):
        self._stop.set()
        for sock in (self._tcp, self._udp):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _discovery_loop(self):
        while not self._stop.is_set():
            try:
                data, address = self._udp.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                request = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if request.get("type") != "discover" or request.get("protocol") != PROTOCOL:
                continue
            with self._lock:
                expected = code_hash(self.code) if self.code else ""
            if not hmac.compare_digest(str(request.get("code_hash", "")), expected):
                continue
            reply = {"type": "offer", "protocol": PROTOCOL, "port": TCP_PORT, "name": self.name}
            try:
                self._udp.sendto(json.dumps(reply).encode("utf-8"), address)
            except OSError:
                continue

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                client, address = self._tcp.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                if self._handshake(client):
                    return
            except (OSError, ValueError, ConnectionError):
                pass
            try:
                client.close()
            except OSError:
                pass

    def _handshake(self, client):
        client.settimeout(10)
        hello = receive_frame(client)
        if hello.get("type") != "hello" or hello.get("protocol") != PROTOCOL:
            send_frame(client, {"type": "error", "message": "Update the agent to the latest version."})
            return False
        with self._lock:
            expected = self.code or ""
        if not hmac.compare_digest(str(hello.get("code", "")), expected):
            send_frame(client, {"type": "auth_failed"})
            with self._lock:
                self._failed += 1
                failed = self._failed
            if self.on_attempt_failed:
                self.on_attempt_failed(failed)
            if failed >= MAX_FAILED_ATTEMPTS:
                self.regenerate_code()
            return False
        send_frame(client, {"type": "authorized", "protocol": PROTOCOL, "name": self.name})
        client.settimeout(None)
        name = str(hello.get("name") or "Remote device")[:80]
        self.stop()
        if self.on_connected:
            self.on_connected(RemoteConnection(client, name))
        return True


# ---------------------------------------------------------------------------
# Agent side (used by the Windows agent; the Raspberry Pi agent has its own
# standalone copy of the same logic in agents/raspberry_pi/agent.py).


def _broadcast_addresses():
    targets = {"255.255.255.255"}
    try:
        import ipaddress
        import psutil
        for entries in psutil.net_if_addrs().values():
            for entry in entries:
                if entry.family == socket.AF_INET and entry.netmask and not entry.address.startswith("127."):
                    network = ipaddress.IPv4Network(f"{entry.address}/{entry.netmask}", strict=False)
                    targets.add(str(network.broadcast_address))
    except Exception:
        pass
    return sorted(targets)


def find_pc(code, timeout=6.0):
    """Broadcast on the LAN for the PC showing this code. Returns (host, port, name) or None."""
    message = json.dumps({"type": "discover", "protocol": PROTOCOL,
                          "code_hash": code_hash(code)}).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.5)
    deadline = time.monotonic() + timeout
    next_send = 0.0
    try:
        while time.monotonic() < deadline:
            if time.monotonic() >= next_send:
                for target in _broadcast_addresses():
                    try:
                        sock.sendto(message, (target, DISCOVERY_PORT))
                    except OSError:
                        continue
                next_send = time.monotonic() + 1.0
            try:
                data, address = sock.recvfrom(2048)
            except socket.timeout:
                continue
            try:
                reply = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if reply.get("type") == "offer" and reply.get("protocol") == PROTOCOL:
                return address[0], int(reply.get("port") or TCP_PORT), reply.get("name") or address[0]
    finally:
        sock.close()
    return None


def _agent_sample(cpu_count):
    import psutil
    processes = []
    for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            processes.append({
                "pid": proc.pid,
                "name": proc.info.get("name") or "Unknown",
                "cpu_percent_normalized": proc.cpu_percent(interval=None) / cpu_count,
                "memory_percent": proc.info.get("memory_percent") or 0.0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    processes.sort(key=lambda item: item["cpu_percent_normalized"], reverse=True)
    return {"type": "sample", "timestamp": time.time(),
            "cpu": psutil.cpu_percent(interval=0.5),
            "memory": psutil.virtual_memory().percent,
            "processes": processes[:20], "gpu": None, "gpu_memory": None}


def connect_and_serve(code, host=None):
    """Connect to the PC showing `code` and answer sample requests until it disconnects."""
    import psutil
    if host:
        port, pc_name = TCP_PORT, host
    else:
        print("Searching the local network for the PC...", flush=True)
        found = find_pc(code)
        if found is None:
            raise ConnectionError(
                "No PC with that code was found. Check the code, make sure both devices are on "
                "the same Wi-Fi/LAN, and allow the monitor through Windows Firewall.")
        host, port, pc_name = found
    sock = socket.create_connection((host, port), timeout=10)
    try:
        send_frame(sock, {"type": "hello", "protocol": PROTOCOL, "code": code,
                          "name": platform.node() or "Windows PC"})
        reply = receive_frame(sock)
        if reply.get("type") == "auth_failed":
            raise PermissionError("The PC rejected the code. Check the code shown on the PC.")
        if reply.get("type") != "authorized":
            raise ConnectionError(reply.get("message") or "The PC refused the connection.")
        print(f"Connected to {reply.get('name') or pc_name}. Press Ctrl+C to stop.", flush=True)
        sock.settimeout(None)
        cpu_count = max(1, psutil.cpu_count(logical=True) or 1)
        while True:
            request = receive_frame(sock)
            if request.get("type") != "sample":
                return
            send_frame(sock, _agent_sample(cpu_count))
    finally:
        sock.close()


def run_agent(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="System Resource Monitor network agent")
    parser.add_argument("--code", help="5-digit code shown on the monitoring PC")
    parser.add_argument("--host", help="PC IP address (skip automatic discovery)")
    args = parser.parse_args(argv)
    code = args.code
    try:
        while True:
            while not is_valid_code(code):
                code = input("Enter the 5-digit code shown on the PC: ").strip()
            try:
                connect_and_serve(code, args.host)
                print("The PC ended the connection.", flush=True)
            except (OSError, ValueError, ConnectionError) as exc:
                print(f"Connection failed: {exc}", flush=True)
            code = None
    except (KeyboardInterrupt, EOFError):
        print("\nStopping monitor agent.")
