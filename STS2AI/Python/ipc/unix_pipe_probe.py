"""Minimal Mac-compatible HeadlessSim pipe probe (Unix Domain Socket).

On macOS/Linux, .NET NamedPipeServerStream maps to a Unix Domain Socket at
    $TMPDIR/CoreFxPipe_<pipeName>  (or /tmp/CoreFxPipe_<pipeName>)

This script:
1. Connects to the socket
2. Reads the handshake (length-prefix + binary body)
3. Parses protocol version + schema hash
4. Prints OK / error

Run with HeadlessSim already started:
    STS2AI/ENV/Sim/Host/bin/Debug/net9.0/headless_sim_host_0991 --port 15527 --protocol bin
"""
from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
from pathlib import Path


def corefx_pipe_path(pipe_name: str) -> Path:
    """Return macOS/Linux equivalent of \\\\.\\pipe\\<name>."""
    tmpdir = os.environ.get("TMPDIR") or "/tmp"
    return Path(tmpdir) / f"CoreFxPipe_{pipe_name}"


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"Socket closed after {len(buf)}/{n} bytes")
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock: socket.socket) -> bytes:
    prefix = recv_exact(sock, 4)
    length = struct.unpack("<i", prefix)[0]
    if length < 0 or length > 64 * 1024 * 1024:
        raise ValueError(f"Invalid frame length {length}")
    return recv_exact(sock, length)


def write_frame(sock: socket.socket, body: bytes) -> None:
    sock.sendall(struct.pack("<i", len(body)) + body)


def parse_handshake_binary(body: bytes) -> dict:
    """Binary handshake:
        u8  status
        u8  opcode (0x00 = Handshake)
        u16 protocol_version
        u16 build_git_sha_len, bytes
        u16 binary_schema_hash_len, bytes
    """
    assert body[0] == 0, f"handshake status {body[0]}"
    assert body[1] == 0x00, f"handshake opcode {body[1]}"
    offset = 2
    protocol_version = struct.unpack_from("<H", body, offset)[0]
    offset += 2

    def read_string() -> str:
        nonlocal offset
        length = struct.unpack_from("<H", body, offset)[0]
        offset += 2
        s = body[offset : offset + length].decode("utf-8")
        offset += length
        return s

    build_sha = read_string()
    schema_hash = read_string()
    return {
        "protocol_version": protocol_version,
        "build_git_sha": build_sha,
        "schema_hash": schema_hash,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=15527)
    ap.add_argument("--protocol", choices=["json", "bin"], default="bin")
    args = ap.parse_args()

    pipe_name = (
        f"sts2_mcts_bin_{args.port}" if args.protocol == "bin" else f"sts2_mcts_{args.port}"
    )
    path = corefx_pipe_path(pipe_name)
    print(f"[probe] connecting to {path}")

    if not path.exists():
        print(f"[probe] ERROR: socket does not exist. Is HeadlessSim running?")
        print(f"[probe] TMPDIR={os.environ.get('TMPDIR')}")
        return 2

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.connect(str(path))
    print("[probe] connected")

    body = read_frame(sock)
    print(f"[probe] handshake frame: {len(body)} bytes")
    print(f"[probe] raw hex: {body.hex()}")

    if args.protocol == "bin":
        info = parse_handshake_binary(body)
        print(f"[probe] protocol_version={info['protocol_version']}")
        print(f"[probe] build_git_sha={info['build_git_sha']!r}")
        print(f"[probe] schema_hash={info['schema_hash']!r}")
    else:
        print(f"[probe] json handshake: {body.decode('utf-8', errors='replace')}")

    sock.close()
    print("[probe] OK — Mac pipe bridge works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
