#!/usr/bin/env python3
"""freeport [START] [END]  — print the first TCP port >= START (default 8000) that nothing is listening on.

Checks IPv4 + IPv6, wildcard and loopback, so a server bound to *:8000 or [::]:8000 is detected too.
"""
import socket
import sys


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


if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:3]] if len(sys.argv) > 1 else []
    print(first_free(*(a or [8000])))
