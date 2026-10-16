#!/usr/bin/env python3
"""aserve [DIR] [START_PORT] — serve a folder over HTTP on the first FREE port and print the real URL.

Starts detached (survives the shell). Example:  aserve ./site 8000   ->  http://localhost:8001/
"""
import os
import socket
import subprocess
import sys
import time

def in_use(port: int) -> bool:
    for fam, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        s = socket.socket(fam, socket.SOCK_STREAM)
        s.settimeout(0.25)
        try:
            if s.connect_ex((addr, port)) == 0:
                return True
        except OSError:
            pass
        finally:
            s.close()
    for fam, addr in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        s = socket.socket(fam, socket.SOCK_STREAM)
        try:
            s.bind((addr, port))
        except OSError:
            return True
        finally:
            s.close()
    return False


def first_free(start: int = 8000, end: int = 9999) -> int:
    for p in range(start, end + 1):
        if not in_use(p):
            return p
    raise SystemExit(f"no free port between {start} and {end}")




d = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
port = first_free(int(sys.argv[2]) if len(sys.argv) > 2 else 8000)
log = open(os.path.join("/tmp", f"aserve-{port}.log"), "w")
p = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "0.0.0.0", "-d", d],
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
time.sleep(0.6)
if p.poll() is not None:
    sys.exit(f"server failed to start on port {port}; see /tmp/aserve-{port}.log")
print(f"http://localhost:{port}/   (serving {d}, pid {p.pid}; stop with: kill {p.pid})")
