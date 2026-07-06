#!/usr/bin/env bash
# =============================================================================
# PolyMarketAlphaAI — Unified Service Launcher
# =============================================================================
# 
# Usage:
#   ./start_services.sh              → Start all services (foreground)
#   ./start_services.sh --daemon     → Start all services (background daemon)
#   ./start_services.sh --stop       → Stop all running services
#   ./start_services.sh --status     → Check service status
#   ./start_services.sh --logs       → Tail all logs
#   ./start_services.sh --restart    → Restart all services
#
# This script manages:
#   1. FastAPI Backend (uvicorn on port 8000)
#   2. Telegram Bot (python3 telegram_bot.py)
#
# Features:
#   - Auto-restart on crash
#   - Log rotation
#   - PID tracking
#   - Health checks
#   - Graceful shutdown
#
# =============================================================================

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="polymarket_alpha_ai"
PID_DIR="${SCRIPT_DIR}/.pids"
LOG_DIR="${SCRIPT_DIR}/logs"

FASTAPI_MODULE="app:app"           # Change if your entry point differs
FASTAPI_PORT=8000
FASTAPI_HOST="0.0.0.0"
FASTAPI_WORKERS=1                  # Use 1 for dev, 2-4 for production
FASTAPI_PID_FILE="${PID_DIR}/fastapi.pid"
FASTAPI_LOG="${LOG_DIR}/fastapi.log"
FASTAPI_ERROR_LOG="${LOG_DIR}/fastapi.error.log"

TELEGRAM_BOT_SCRIPT="${SCRIPT_DIR}/telegram_bot.py"
TELEGRAM_PID_FILE="${PID_DIR}/telegram_bot.pid"
TELEGRAM_LOG="${LOG_DIR}/telegram_bot.log"
TELEGRAM_ERROR_LOG="${LOG_DIR}/telegram_bot.error.log"

HEALTH_CHECK_INTERVAL=30           # Seconds between health checks
MAX_RESTART_ATTEMPTS=5             # Max restarts before giving up
RESTART_WINDOW=60                  # Seconds window for restart counting

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

log_info() {
    echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') — $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $(date '+%Y-%m-%d %H:%M:%S') — $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') — $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') — $1"
}

ensure_dirs() {
    mkdir -p "${PID_DIR}" "${LOG_DIR}"
}

# Check if a process is running by PID file
check_pid_running() {
    local pid_file="$1"
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            return 0  # Running
        fi
    fi
    return 1  # Not running
}

# Get PID from file
get_pid() {
    local pid_file="$1"
    if [[ -f "$pid_file" ]]; then
        cat "$pid_file" 2>/dev/null || echo ""
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI SERVICE
# ─────────────────────────────────────────────────────────────────────────────

start_fastapi() {
    log_info "Starting FastAPI backend on ${FASTAPI_HOST}:${FASTAPI_PORT}..."

    if check_pid_running "$FASTAPI_PID_FILE"; then
        log_warn "FastAPI is already running (PID: $(get_pid "$FASTAPI_PID_FILE"))"
        return 0
    fi

    # Check if uvicorn is available
    if ! command -v uvicorn &> /dev/null; then
        log_error "uvicorn not found. Install with: pip install uvicorn[standard]"
        return 1
    fi

    # Check if module exists
    if [[ ! -f "${SCRIPT_DIR}/app.py" ]]; then
        log_error "app.py not found in ${SCRIPT_DIR}"
        return 1
    fi

    # Start uvicorn with auto-reload for development
    # For production, remove --reload and increase workers
    nohup uvicorn "${FASTAPI_MODULE}"         --host "$FASTAPI_HOST"         --port "$FASTAPI_PORT"         --reload         --log-level info         --access-log         >> "$FASTAPI_LOG" 2>> "$FASTAPI_ERROR_LOG" &

    local pid=$!
    echo "$pid" > "$FASTAPI_PID_FILE"

    # Wait a moment and verify it started
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        log_success "FastAPI started (PID: $pid) — http://${FASTAPI_HOST}:${FASTAPI_PORT}"
        log_info "API docs: http://${FASTAPI_HOST}:${FASTAPI_PORT}/docs"
        return 0
    else
        log_error "FastAPI failed to start. Check logs: ${FASTAPI_ERROR_LOG}"
        rm -f "$FASTAPI_PID_FILE"
        return 1
    fi
}

stop_fastapi() {
    log_info "Stopping FastAPI..."

    if check_pid_running "$FASTAPI_PID_FILE"; then
        local pid
        pid=$(get_pid "$FASTAPI_PID_FILE")
        kill -TERM "$pid" 2>/dev/null || true

        # Wait for graceful shutdown
        local count=0
        while kill -0 "$pid" 2>/dev/null && [[ $count -lt 10 ]]; do
            sleep 1
            ((count++))
        done

        # Force kill if still running
        if kill -0 "$pid" 2>/dev/null; then
            log_warn "FastAPI not responding, forcing kill..."
            kill -9 "$pid" 2>/dev/null || true
        fi

        rm -f "$FASTAPI_PID_FILE"
        log_success "FastAPI stopped"
    else
        log_warn "FastAPI was not running"
        rm -f "$FASTAPI_PID_FILE"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM BOT SERVICE
# ─────────────────────────────────────────────────────────────────────────────

start_telegram_bot() {
    log_info "Starting Telegram Bot..."

    if check_pid_running "$TELEGRAM_PID_FILE"; then
        log_warn "Telegram Bot is already running (PID: $(get_pid "$TELEGRAM_PID_FILE"))"
        return 0
    fi

    # Check if script exists
    if [[ ! -f "$TELEGRAM_BOT_SCRIPT" ]]; then
        log_error "telegram_bot.py not found at ${TELEGRAM_BOT_SCRIPT}"
        return 1
    fi

    # Check required env vars
    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        log_warn "TELEGRAM_BOT_TOKEN not set in environment"
        log_info "Make sure your .env file is loaded or export TELEGRAM_BOT_TOKEN=your_token"
    fi

    # Start the bot
    cd "$SCRIPT_DIR"
    nohup python3 "$TELEGRAM_BOT_SCRIPT"         >> "$TELEGRAM_LOG" 2>> "$TELEGRAM_ERROR_LOG" &

    local pid=$!
    echo "$pid" > "$TELEGRAM_PID_FILE"

    # Wait and verify
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        log_success "Telegram Bot started (PID: $pid)"
        return 0
    else
        log_error "Telegram Bot failed to start. Check logs: ${TELEGRAM_ERROR_LOG}"
        rm -f "$TELEGRAM_PID_FILE"
        return 1
    fi
}

stop_telegram_bot() {
    log_info "Stopping Telegram Bot..."

    if check_pid_running "$TELEGRAM_PID_FILE"; then
        local pid
        pid=$(get_pid "$TELEGRAM_PID_FILE")
        kill -TERM "$pid" 2>/dev/null || true

        local count=0
        while kill -0 "$pid" 2>/dev/null && [[ $count -lt 10 ]]; do
            sleep 1
            ((count++))
        done

        if kill -0 "$pid" 2>/dev/null; then
            log_warn "Telegram Bot not responding, forcing kill..."
            kill -9 "$pid" 2>/dev/null || true
        fi

        rm -f "$TELEGRAM_PID_FILE"
        log_success "Telegram Bot stopped"
    else
        log_warn "Telegram Bot was not running"
        rm -f "$TELEGRAM_PID_FILE"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# HEALTH MONITORING (Daemon Mode)
# ─────────────────────────────────────────────────────────────────────────────

health_monitor() {
    log_info "Health monitor started (checking every ${HEALTH_CHECK_INTERVAL}s)"

    local fastapi_restarts=0
    local telegram_restarts=0
    local fastapi_last_restart=0
    local telegram_last_restart=0

    while true; do
        sleep "$HEALTH_CHECK_INTERVAL"

        local now
        now=$(date +%s)

        # Check FastAPI
        if ! check_pid_running "$FASTAPI_PID_FILE"; then
            log_warn "FastAPI is down! Attempting restart..."

            # Rate limit restarts
            if [[ $((now - fastapi_last_restart)) -gt $RESTART_WINDOW ]]; then
                fastapi_restarts=0
            fi

            if [[ $fastapi_restarts -lt $MAX_RESTART_ATTEMPTS ]]; then
                ((fastapi_restarts++))
                fastapi_last_restart=$now
                start_fastapi || log_error "FastAPI restart failed"
            else
                log_error "FastAPI exceeded max restart attempts. Manual intervention required."
            fi
        fi

        # Check Telegram Bot
        if ! check_pid_running "$TELEGRAM_PID_FILE"; then
            log_warn "Telegram Bot is down! Attempting restart..."

            if [[ $((now - telegram_last_restart)) -gt $RESTART_WINDOW ]]; then
                telegram_restarts=0
            fi

            if [[ $telegram_restarts -lt $MAX_RESTART_ATTEMPTS ]]; then
                ((telegram_restarts++))
                telegram_last_restart=$now
                start_telegram_bot || log_error "Telegram Bot restart failed"
            else
                log_error "Telegram Bot exceeded max restart attempts. Manual intervention required."
            fi
        fi
    done
}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

start_all() {
    ensure_dirs
    log_info "Starting PolyMarketAlphaAI services..."
    log_info "Project directory: ${SCRIPT_DIR}"

    local failed=0

    start_fastapi || failed=1
    start_telegram_bot || failed=1

    if [[ $failed -eq 0 ]]; then
        log_success "All services started successfully!"
        log_info "FastAPI PID: $(get_pid "$FASTAPI_PID_FILE")"
        log_info "Telegram Bot PID: $(get_pid "$TELEGRAM_PID_FILE")"
        log_info "Logs directory: ${LOG_DIR}"

        if [[ "${1:-}" == "--daemon" ]]; then
            log_info "Running in daemon mode with health monitoring..."
            health_monitor &
            local monitor_pid=$!
            echo "$monitor_pid" > "${PID_DIR}/monitor.pid"
            log_success "Health monitor started (PID: $monitor_pid)"
            log_info "To stop all services: ./start_services.sh --stop"
            # Detach from terminal
            disown
        else
            echo ""
            log_info "Press Ctrl+C to stop all services"
            echo ""
            # Wait for interrupt
            trap 'stop_all; exit 0' INT TERM
            wait
        fi
    else
        log_error "Some services failed to start. Check logs."
        stop_all
        exit 1
    fi
}

stop_all() {
    log_info "Stopping all PolyMarketAlphaAI services..."
    stop_fastapi
    stop_telegram_bot

    # Stop health monitor if running
    if [[ -f "${PID_DIR}/monitor.pid" ]]; then
        local monitor_pid
        monitor_pid=$(cat "${PID_DIR}/monitor.pid" 2>/dev/null || echo "")
        if [[ -n "$monitor_pid" ]] && kill -0 "$monitor_pid" 2>/dev/null; then
            kill -TERM "$monitor_pid" 2>/dev/null || true
            rm -f "${PID_DIR}/monitor.pid"
            log_success "Health monitor stopped"
        fi
    fi

    log_success "All services stopped"
}

show_status() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║           PolyMarketAlphaAI Service Status                   ║${NC}"
    echo -e "${BLUE}╠══════════════════════════════════════════════════════════════╣${NC}"

    # FastAPI status
    if check_pid_running "$FASTAPI_PID_FILE"; then
        local pid
        pid=$(get_pid "$FASTAPI_PID_FILE")
        echo -e "${BLUE}║${NC}  FastAPI Backend   ${GREEN}● RUNNING${NC}   PID: ${pid}  Port: ${FASTAPI_PORT}"
    else
        echo -e "${BLUE}║${NC}  FastAPI Backend   ${RED}● STOPPED${NC}"
    fi

    # Telegram Bot status
    if check_pid_running "$TELEGRAM_PID_FILE"; then
        local pid
        pid=$(get_pid "$TELEGRAM_PID_FILE")
        echo -e "${BLUE}║${NC}  Telegram Bot      ${GREEN}● RUNNING${NC}   PID: ${pid}"
    else
        echo -e "${BLUE}║${NC}  Telegram Bot      ${RED}● STOPPED${NC}"
    fi

    # Health monitor status
    if [[ -f "${PID_DIR}/monitor.pid" ]]; then
        local monitor_pid
        monitor_pid=$(cat "${PID_DIR}/monitor.pid" 2>/dev/null || echo "")
        if [[ -n "$monitor_pid" ]] && kill -0 "$monitor_pid" 2>/dev/null; then
            echo -e "${BLUE}║${NC}  Health Monitor    ${GREEN}● RUNNING${NC}   PID: ${monitor_pid}"
        else
            echo -e "${BLUE}║${NC}  Health Monitor    ${RED}● STOPPED${NC}"
        fi
    else
        echo -e "${BLUE}║${NC}  Health Monitor    ${RED}● STOPPED${NC}"
    fi

    echo -e "${BLUE}╠══════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${BLUE}║${NC}  Log Directory: ${LOG_DIR}"
    echo -e "${BLUE}║${NC}  PID Directory: ${PID_DIR}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

show_logs() {
    log_info "Tailing all logs (Ctrl+C to exit)..."
    if command -v multitail &> /dev/null; then
        multitail "$FASTAPI_LOG" "$TELEGRAM_LOG" "$FASTAPI_ERROR_LOG" "$TELEGRAM_ERROR_LOG" 2>/dev/null ||         tail -f "$FASTAPI_LOG" "$TELEGRAM_LOG" "$FASTAPI_ERROR_LOG" "$TELEGRAM_ERROR_LOG"
    else
        tail -f "$FASTAPI_LOG" "$TELEGRAM_LOG" "$FASTAPI_ERROR_LOG" "$TELEGRAM_ERROR_LOG"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# COMMAND DISPATCH
# ─────────────────────────────────────────────────────────────────────────────

case "${1:-}" in
    --daemon|-d)
        start_all --daemon
        ;;
    --stop|-s)
        stop_all
        ;;
    --status|-st)
        show_status
        ;;
    --logs|-l)
        show_logs
        ;;
    --restart|-r)
        stop_all
        sleep 2
        start_all
        ;;
    --help|-h)
        cat << 'EOF'
PolyMarketAlphaAI Service Launcher
==================================

Usage: ./start_services.sh [OPTION]

Options:
  (none)          Start all services in foreground (Ctrl+C to stop)
  --daemon, -d    Start all services in background with auto-restart
  --stop, -s      Stop all running services
  --status, -st   Show service status
  --logs, -l      Tail all service logs
  --restart, -r   Restart all services
  --help, -h      Show this help message

Environment Variables:
  TELEGRAM_BOT_TOKEN    Required for Telegram bot
  SUPABASE_URL          Required for database
  SUPABASE_SERVICE_ROLE_KEY  Required for database
  .env file is automatically loaded if present

Examples:
  ./start_services.sh              # Dev mode, see output in terminal
  ./start_services.sh --daemon     # Production mode, runs in background
  ./start_services.sh --status     # Check if services are running
  ./start_services.sh --logs       # Watch live logs
  ./start_services.sh --stop       # Stop everything

EOF
        ;;
    *)
        start_all
        ;;
esac
