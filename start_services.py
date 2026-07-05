#!/usr/bin/env python3
"""
PolyMarketAlphaAI — Python Service Launcher
=============================================

Cross-platform alternative to start_services.sh.
Works on Linux, macOS, and Windows.

Usage:
    python3 start_services.py              → Start all services
    python3 start_services.py --daemon     → Start with auto-restart
    python3 start_services.py --stop       → Stop all services
    python3 start_services.py --status     → Check status

"""

import os
import sys
import time
import signal
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
PID_DIR = SCRIPT_DIR / ".pids"
LOG_DIR = SCRIPT_DIR / "logs"

FASTAPI_MODULE = "app:app"
FASTAPI_PORT = 8000
FASTAPI_HOST = "0.0.0.0"

TELEGRAM_SCRIPT = SCRIPT_DIR / "telegram_bot.py"

HEALTH_CHECK_INTERVAL = 30
MAX_RESTART_ATTEMPTS = 5
RESTART_WINDOW = 60

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def log_info(msg: str) -> None:
    print(f"[INFO] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {msg}")

def log_ok(msg: str) -> None:
    print(f"[OK] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {msg}")

def log_warn(msg: str) -> None:
    print(f"[WARN] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {msg}")

def log_error(msg: str) -> None:
    print(f"[ERROR] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — {msg}")

# ─────────────────────────────────────────────────────────────────────────────
# PROCESS MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def ensure_dirs() -> None:
    PID_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)

def write_pid(name: str, pid: int) -> None:
    (PID_DIR / f"{name}.pid").write_text(str(pid))

def read_pid(name: str) -> int | None:
    pid_file = PID_DIR / f"{name}.pid"
    if pid_file.exists():
        try:
            return int(pid_file.read_text().strip())
        except ValueError:
            return None
    return None

def is_running(name: str) -> bool:
    pid = read_pid(name)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False

def stop_service(name: str) -> None:
    pid = read_pid(name)
    if pid is None:
        log_warn(f"{name} was not running")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for graceful shutdown
        for _ in range(10):
            if not is_running(name):
                break
            time.sleep(1)

        # Force kill if still running
        if is_running(name):
            log_warn(f"{name} not responding, forcing kill...")
            os.kill(pid, signal.SIGKILL)

        log_ok(f"{name} stopped")
    except (OSError, ProcessLookupError):
        log_warn(f"{name} was not running")
    finally:
        (PID_DIR / f"{name}.pid").unlink(missing_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# SERVICE STARTERS
# ─────────────────────────────────────────────────────────────────────────────

def start_fastapi() -> bool:
    if is_running("fastapi"):
        log_warn(f"FastAPI already running (PID: {read_pid('fastapi')})")
        return True

    log_info(f"Starting FastAPI on {FASTAPI_HOST}:{FASTAPI_PORT}...")

    log_file = LOG_DIR / "fastapi.log"
    err_file = LOG_DIR / "fastapi.error.log"

    # Check if uvicorn is available
    try:
        subprocess.run(["uvicorn", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        log_error("uvicorn not found. Install: pip install uvicorn[standard]")
        return False

    # Start uvicorn
    proc = subprocess.Popen(
        [
            "uvicorn", FASTAPI_MODULE,
            "--host", FASTAPI_HOST,
            "--port", str(FASTAPI_PORT),
            "--reload",
            "--log-level", "info",
        ],
        stdout=open(log_file, "a"),
        stderr=open(err_file, "a"),
        cwd=SCRIPT_DIR,
    )

    write_pid("fastapi", proc.pid)
    time.sleep(2)

    if is_running("fastapi"):
        log_ok(f"FastAPI started (PID: {proc.pid}) — http://{FASTAPI_HOST}:{FASTAPI_PORT}")
        return True
    else:
        log_error(f"FastAPI failed to start. Check: {err_file}")
        return False

def start_telegram() -> bool:
    if is_running("telegram"):
        log_warn(f"Telegram Bot already running (PID: {read_pid('telegram')})")
        return True

    log_info("Starting Telegram Bot...")

    if not TELEGRAM_SCRIPT.exists():
        log_error(f"telegram_bot.py not found at {TELEGRAM_SCRIPT}")
        return False

    log_file = LOG_DIR / "telegram_bot.log"
    err_file = LOG_DIR / "telegram_bot.error.log"

    proc = subprocess.Popen(
        [sys.executable, str(TELEGRAM_SCRIPT)],
        stdout=open(log_file, "a"),
        stderr=open(err_file, "a"),
        cwd=SCRIPT_DIR,
    )

    write_pid("telegram", proc.pid)
    time.sleep(2)

    if is_running("telegram"):
        log_ok(f"Telegram Bot started (PID: {proc.pid})")
        return True
    else:
        log_error(f"Telegram Bot failed to start. Check: {err_file}")
        return False

# ─────────────────────────────────────────────────────────────────────────────
# HEALTH MONITOR
# ─────────────────────────────────────────────────────────────────────────────

def health_monitor() -> None:
    log_info("Health monitor started")

    restart_counts = {"fastapi": 0, "telegram": 0}
    last_restarts = {"fastapi": 0, "telegram": 0}

    while True:
        time.sleep(HEALTH_CHECK_INTERVAL)
        now = time.time()

        for service, starter in [("fastapi", start_fastapi), ("telegram", start_telegram)]:
            if not is_running(service):
                log_warn(f"{service} is down! Restarting...")

                # Rate limit restarts
                if now - last_restarts[service] > RESTART_WINDOW:
                    restart_counts[service] = 0

                if restart_counts[service] < MAX_RESTART_ATTEMPTS:
                    restart_counts[service] += 1
                    last_restarts[service] = now
                    starter()
                else:
                    log_error(f"{service} exceeded max restarts. Manual fix needed.")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PolyMarketAlphaAI Service Launcher")
    parser.add_argument("--daemon", "-d", action="store_true", help="Run with auto-restart")
    parser.add_argument("--stop", "-s", action="store_true", help="Stop all services")
    parser.add_argument("--status", "-st", action="store_true", help="Show status")
    parser.add_argument("--restart", "-r", action="store_true", help="Restart all services")
    args = parser.parse_args()

    ensure_dirs()

    if args.stop:
        log_info("Stopping all services...")
        stop_service("fastapi")
        stop_service("telegram")
        log_ok("All services stopped")
        return

    if args.status:
        print("\n" + "=" * 60)
        print("PolyMarketAlphaAI Service Status")
        print("=" * 60)
        for service in ["fastapi", "telegram"]:
            status = "RUNNING" if is_running(service) else "STOPPED"
            pid = read_pid(service) or "N/A"
            print(f"  {service:12s} {status:10s} PID: {pid}")
        print("=" * 60 + "\n")
        return

    if args.restart:
        log_info("Restarting all services...")
        stop_service("fastapi")
        stop_service("telegram")
        time.sleep(2)

    # Start services
    log_info("Starting PolyMarketAlphaAI services...")
    failed = False

    if not start_fastapi():
        failed = True
    if not start_telegram():
        failed = True

    if failed:
        log_error("Some services failed to start")
        sys.exit(1)

    log_ok("All services started!")

    if args.daemon:
        log_info("Running in daemon mode with health monitoring...")
        try:
            health_monitor()
        except KeyboardInterrupt:
            log_info("Monitor stopped")
    else:
        log_info("Press Ctrl+C to stop all services")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log_info("Stopping all services...")
            stop_service("fastapi")
            stop_service("telegram")
            log_ok("All services stopped")

if __name__ == "__main__":
    main()
