#!/usr/bin/env python3
"""System Resource Monitor network agent for Raspberry Pi OS / Linux.

Run it, type the 5-digit code shown in the PC app, and the agent finds the PC
on the same Wi-Fi/LAN and sends CPU, memory, and process readings to it.

    python3 agent.py                 # asks for the code
    python3 agent.py --code 12345    # code on the command line
    python3 agent.py --host 192.168.0.10   # skip discovery, connect to this PC
"""
import argparse
import hashlib
import ipaddress
import json
import platform
import socket
import struct
import time

import psutil

PROTOCOL = 3
TCP_PORT = 47820
DISCOVERY_PORT = 47821
MAX_FRAME_SIZE = 64 * 1024


def code_hash(code):
    return hashlib.sha256(f"srm-pair-v3:{code}".encode("ascii")).hexdigest()


def is_valid_code(code):
    return isinstance(code, str) and len(code) == 5 and code.isascii() and code.isdigit()


def receive_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("PC disconnected")
        data.extend(chunk)
    return bytes(data)


def receive_frame(sock):
    size = struct.unpack("!I", receive_exact(sock, 4))[0]
    if size <= 0 or size > MAX_FRAME_SIZE:
        raise ValueError("Invalid request frame")
    return json.loads(receive_exact(sock, size).decode("utf-8"))


def send_frame(sock, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME_SIZE:
        raise ValueError("Response frame is too large")
    sock.sendall(struct.pack("!I", len(body)) + body)


def broadcast_addresses():
    targets = {"255.255.255.255"}
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            if entry.family == socket.AF_INET and entry.netmask and not entry.address.startswith("127."):
                try:
                    network = ipaddress.IPv4Network(f"{entry.address}/{entry.netmask}", strict=False)
                    targets.add(str(network.broadcast_address))
                except ValueError:
                    continue
    return sorted(targets)


def find_pc(code, timeout=6.0):
    """Broadcast for the PC showing `code`. Returns (host, port, name) or None."""
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
                for target in broadcast_addresses():
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


def process_snapshot(cpu_count):
    processes = []
    for process in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            processes.append({
                "pid": process.pid,
                "name": process.info.get("name") or "Unknown",
                "cpu_percent_normalized": process.cpu_percent(interval=None) / cpu_count,
                "memory_percent": process.info.get("memory_percent") or 0.0,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    processes.sort(key=lambda item: item["cpu_percent_normalized"], reverse=True)
    return processes[:20]


def sample(cpu_count):
    return {
        "type": "sample",
        "timestamp": time.time(),
        "cpu": psutil.cpu_percent(interval=0.5),
        "memory": psutil.virtual_memory().percent,
        "gpu": None,
        "gpu_memory": None,
        "processes": process_snapshot(cpu_count),
    }


def connect_and_serve(code, host=None):
    if host:
        port, pc_name = TCP_PORT, host
    else:
        print("Searching the local network for the PC...", flush=True)
        found = find_pc(code)
        if found is None:
            raise ConnectionError(
                "No PC with that code was found. Check the code, keep the PC's "
                "'Connect device' window open, and make sure both are on the same Wi-Fi/LAN.")
        host, port, pc_name = found
    print(f"Found {pc_name} at {host}:{port}. Connecting...", flush=True)
    sock = socket.create_connection((host, port), timeout=10)
    try:
        send_frame(sock, {"type": "hello", "protocol": PROTOCOL, "code": code,
                          "name": platform.node() or "Raspberry Pi"})
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
            send_frame(sock, sample(cpu_count))
    finally:
        sock.close()


def main():
    parser = argparse.ArgumentParser(description="System Resource Monitor agent")
    parser.add_argument("--code", help="5-digit code shown on the PC")
    parser.add_argument("--host", help="PC IP address (skip automatic discovery)")
    args = parser.parse_args()
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
        print("\nStopping monitor agent")


if __name__ == "__main__":
    main()
