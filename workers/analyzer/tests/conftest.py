"""Test-run safety nets (each one exists because of something that really went wrong).

* HF_HUB_OFFLINE=1: tests never touch the network. The real-model test loads the model from the local cache and is
  skipped when it is not cached.
* Hard exit after the report: with the embedding model loaded (native ONNX/HF threads) the interpreter occasionally
  hung for minutes AFTER all tests had passed, blocked on name-resolution sockets under WSL's flaky DNS. Once pytest
  has printed its summary there is nothing left to clean up, so the process exits immediately.
  (Set TEST_HARD_EXIT=0 to disable.)
* faulthandler watchdog: if a test itself hangs, dump every stack and exit instead of freezing.
* TEST_DNS_LOG=<file>: record every Python-level name lookup (who resolves what, from which thread). This is how the
  stdlib's reverse-DNS lookup in http.server (socket.getfqdn) was found as a hang source.
"""
import faulthandler
import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

WATCHDOG_SECONDS = int(os.environ.get("TEST_WATCHDOG_S", "240"))
_exit_status = 0


def pytest_sessionstart(session):
    faulthandler.dump_traceback_later(WATCHDOG_SECONDS, exit=True)


def pytest_sessionfinish(session, exitstatus):
    global _exit_status
    _exit_status = int(exitstatus)
    faulthandler.cancel_dump_traceback_later()


def pytest_unconfigure(config):
    if os.environ.get("TEST_HARD_EXIT", "1") == "1":
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_exit_status)


if os.environ.get("TEST_DNS_LOG"):
    import socket
    import threading
    import traceback

    _log = open(os.environ["TEST_DNS_LOG"], "a", buffering=1)

    def _wrap(name):
        orig = getattr(socket, name)

        def wrapper(*args, **kwargs):
            where = " <- ".join(f"{f.name}({os.path.basename(f.filename)}:{f.lineno})" for f in traceback.extract_stack()[-6:-1][::-1][:4])
            _log.write(f"{name}{args[:2]!r} thread={threading.current_thread().name} :: {where}\n")
            return orig(*args, **kwargs)
        setattr(socket, name, wrapper)

    for _n in ("getaddrinfo", "gethostbyaddr", "gethostbyname", "getfqdn"):
        _wrap(_n)
