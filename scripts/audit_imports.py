#!/usr/bin/env python3
"""
scripts/audit_imports.py — AST аналіз імпортів у кодовій базі SmartGarage
Визначає реальні залежності для розділення requirements.txt.
"""
import ast
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Стандартні модулі Python 3.12 (які не потребують pip)
STDLIB = {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii", "bisect",
    "builtins", "calendar", "cmath", "cmd", "code", "codecs", "collections",
    "concurrent", "configparser", "contextlib", "contextvars", "copy", "csv",
    "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
    "dis", "doctest", "email", "encodings", "ensurepip", "enum", "errno", "faulthandler",
    "fcntl", "filecmp", "fileinput", "fnmatch", "fractions", "ftplib", "functools",
    "gc", "getopt", "getpass", "gettext", "glob", "graphlib", "gzip", "hashlib",
    "heapq", "hmac", "html", "http", "idlelib", "imaplib", "imghdr", "importlib",
    "inspect", "io", "ipaddress", "itertools", "json", "keyword", "linecache",
    "locale", "logging", "lzma", "mailbox", "mailcap", "marshal", "math",
    "mimetypes", "mmap", "modulefinder", "multiprocessing", "netrc", "nntplib",
    "numbers", "operator", "optparse", "os", "pathlib", "pdb", "pickle", "pickletools",
    "pipes", "pkgutil", "platform", "plistlib", "poplib", "posix", "pprint",
    "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue",
    "quopri", "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "sched", "secrets", "select", "selectors", "shelve", "shlex", "shutil",
    "signal", "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
    "spwd", "sqlite3", "ssl", "stat", "statistics", "string", "stringprep",
    "struct", "subprocess", "sunau", "symtable", "sys", "sysconfig", "syslog",
    "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "tokenize", "trace",
    "traceback", "tracemalloc", "tty", "turtle", "turtledemo", "types", "typing",
    "unicodedata", "unittest", "urllib", "uu", "uuid", "venv", "warnings",
    "wave", "weakref", "webbrowser", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp",
    "zipfile", "zipimport", "zlib", "_thread"
}

def analyze_directory(directory: Path):
    imports = set()
    for py_file in directory.rglob("*.py"):
        try:
            with open(py_file, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        imports.add(top)
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        top = node.module.split(".")[0]
                        imports.add(top)
        except Exception as e:
            print(f"Помилка читання {py_file}: {e}", file=sys.stderr)

    # Прибираємо стандартну бібліотеку та локальні пакети
    filtered = set()
    for imp in imports:
        if imp not in STDLIB and imp not in {"server", "tests", "scripts", "training"}:
            filtered.add(imp)
    return sorted(filtered)

def main():
    sections = {
        "Core Server (server/)": REPO_ROOT / "server",
        "Voice & TTS (server/tts, server/voice)": [REPO_ROOT / "server" / "tts", REPO_ROOT / "server" / "voice"],
        "AI Subsystem (server/ai)": REPO_ROOT / "server" / "ai",
        "Tests (tests/)": REPO_ROOT / "tests",
        "Scripts (scripts/)": REPO_ROOT / "scripts",
        "Training (training/)": REPO_ROOT / "training"
    }

    results = {}
    for name, path in sections.items():
        if isinstance(path, list):
            found = set()
            for p in path:
                if p.exists():
                    found.update(analyze_directory(p))
            results[name] = sorted(found)
        else:
            if path.exists():
                results[name] = analyze_directory(path)
            else:
                results[name] = []

    print("=== AST AUDIT OF IMPORTS ===")
    for sec, imps in results.items():
        print(f"\n[{sec}]")
        for i in imps:
            print(f"  - {i}")

if __name__ == "__main__":
    main()
