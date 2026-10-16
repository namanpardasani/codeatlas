"""Fake parse functions used only by tests to exercise the sandbox."""
import os
import time

from .types import ParseResult


def hang(path, source):
    time.sleep(3600)


def crash(path, source):
    os._exit(139)  # simulate a native segfault


def selective(path, source):
    if path == "hang.ts":
        time.sleep(3600)
    if path == "crash.ts":
        os._exit(139)
    return ParseResult()
