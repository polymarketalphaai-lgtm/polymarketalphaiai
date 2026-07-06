#!/usr/bin/env bash
# =============================================================================
# PolyMarketAlphaAI — Enhanced Service Launcher (Codespaces Compatible)
# =============================================================================
# 
# Auto-detects environment and loads .env automatically.
# Works on: local VMs, GitHub Codespaces, cloud servers, Docker containers.
#
# Usage:
#   ./start_services.sh              → Start all services (foreground)
#   ./start_services.sh --daemon     → Start in background with auto-restart
#   ./start_services.sh --stop       → Stop all services
#   ./start_services.sh --status     → Check status
#   ./start_services.sh --logs       → Tail logs
#   ./start_services.sh --restart    → Restart all
#   ./start_services.sh --setup      → Interactive setup (create .env)
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
ENV_FILE="${SCRIPT_DIR}/.env"

FASTAPI_MODULE="app:app"
FASTAPI_PORT=8000
FASTAPI_HOST="0.0.0.0"
FASTAPI_PID_FILE="${PID_DIR}/fastapi.pid"
FASTAPI_LOG="${LOG_DIR}/fastapi.log"
FASTAPI_ERROR_LOG="${LOG_DIR}/fastapi.error.log"

TELEGRAM_BOT_SCRIPT="${SCRIPT_DIR}/telegram_bot.py"
TELEGRAM_PID_FILE="${PID_DIR}/telegram_bot.pid"
TELEGRAM_LOG="${LOG_DIR}/telegram_bot.log"
TELEGRAM_ERROR_LOG="${LOG_DIR}/telegram_bot.error.log"

HEALTH_CHECK_INTERVAL=30
MAX_RESTART_ATTEMPTS=5
RESTART_WINDOW=60

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT DETECTION
# ─────────────────────────────────────────────────────────────────────────────

detect_environment() {
    if [[ -n "${CODESPACE_NAME:-}" ]] || [[ "${CODESPACES:-}" == "true" ]]; then
        echo "github_codespaces"
    elif [[ -f /.dockerenv ]] || grep -q docker /proc/1/cgroup 2>/dev/null; then
        echo "docker"
    elif [[ "$(uname)" == "Darwin" ]]; then
        echo "macos"
    else
        echo "linux"
    fi
}

ENV_TYPE=$(detect_environment)

# ─────────────────────────────────────────────────────────────────────────────
# AUTO-LOAD .env FILE
# ─────────────────────────────────────────────────────────────────────────────

load_env() {
    if [[ -f "$ENV_FILE" ]]; then
        # Export all variables from .env
        set -a
        source "$ENV_FILE"
        set +a
        log_info "Loaded environment from ${ENV_FILE}"
    else
        log_warn ".env file not found at ${ENV_FILE}"
        log_info "Run: ./start_services.sh --setup  to create one interactively"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
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

log_section() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# ─────────────────────────────────────────────────────────────────────────────
# PROCESS MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

ensure_dirs() {
    mkdir -p "${PID_DIR}" "${LOG_DIR}"
}

check_pid_running() {
    local pid_file="$1"
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

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
        log_warn "FastAPI already running (PID: $(get_pid "$FASTAPI_PID_FILE"))"
        return 0
    fi

    if ! command -v uvicorn &> /dev/null; then
        log_error "uvicorn not found. Install: pip install uvicorn[standard]"
        return 1
    fi

    if [[ ! -f "${SCRIPT_DIR}/app.py" ]]; then
        log_error "app.py not found in ${SCRIPT_DIR}"
        return 1
    fi

    # Detect virtual environment
    local python_cmd="python3"
    local uvicorn_cmd="uvicorn"
    if [[ -d "${SCRIPT_DIR}/venv" ]]; then
        python_cmd="${SCRIPT_DIR}/venv/bin/python3"
        uvicorn_cmd="${SCRIPT_DIR}/venv/bin/uvicorn"
        log_info "Using virtual environment"
    elif [[ -d "${SCRIPT_DIR}/.venv" ]]; then
        python_cmd="${SCRIPT_DIR}/.venv/bin/python3"
        uvicorn_cmd="${SCRIPT_DIR}/.venv/bin/uvicorn"
        log_info "Using virtual environment"
    fi

    nohup "$uvicorn_cmd" "${FASTAPI_MODULE}"         --host "$FASTAPI_HOST"         --port "$FASTAPI_PORT"         --reload         --log-level info         --access-log         >> "$FASTAPI_LOG" 2>> "$FASTAPI_ERROR_LOG" &

    local pid=$!
    echo "$pid" > "$FASTAPI_PID_FILE"

    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        log_success "FastAPI started (PID: $pid)"

        if [[ "$ENV_TYPE" == "github_codespaces" ]]; then
            log_info "Codespaces detected — API may be forwarded automatically"
            log_info "Check: https://${CODESPACE_NAME}-${FASTAPI_PORT}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
        fi

        log_info "API docs: http://${FASTAPI_HOST}:${FASTAPI_PORT}/docs"
        return 0
    else
        log_error "FastAPI failed to start. Check: ${FASTAPI_ERROR_LOG}"
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

        local count=0
        while kill -0 "$pid" 2>/dev/null && [[ $count -lt 10 ]]; do
            sleep 1
            ((count++))
        done

        if kill -0 "$pid" 2>/dev/null; then
            log_warn "FastAPI not responding, forcing kill..."
            kill -9 "$pid" 2>/dev/null || true
        fi

        rm -f "$FASTAPI_PID_FILE"
        log_success "FastAPI stopped"
    else
        rm -f "$FASTAPI_PID_FILE"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# TELEGRAM BOT SERVICE
# ─────────────────────────────────────────────────────────────────────────────

start_telegram_bot() {
    log_info "Starting Telegram Bot..."

    if check_pid_running "$TELEGRAM_PID_FILE"; then
        log_warn "Telegram Bot already running (PID: $(get_pid "$TELEGRAM_PID_FILE"))"
        return 0
    fi

    if [[ ! -f "$TELEGRAM_BOT_SCRIPT" ]]; then
        log_error "telegram_bot.py not found at ${TELEGRAM_BOT_SCRIPT}"
        return 1
    fi

    # Check token
    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        log_warn "TELEGRAM_BOT_TOKEN not set!"
        log_info "The bot will fail to start without a valid token."
        log_info "Get one from @BotFather on Telegram, then:"
        log_info "  echo 'TELEGRAM_BOT_TOKEN=your_token_here' >> .env"
    fi

    # Detect virtual environment
    local python_cmd="python3"
    if [[ -d "${SCRIPT_DIR}/venv" ]]; then
        python_cmd="${SCRIPT_DIR}/venv/bin/python3"
    elif [[ -d "${SCRIPT_DIR}/.venv" ]]; then
        python_cmd="${SCRIPT_DIR}/.venv/bin/python3"
    fi

    cd "$SCRIPT_DIR"
    nohup "$python_cmd" "$TELEGRAM_BOT_SCRIPT"         >> "$TELEGRAM_LOG" 2>> "$TELEGRAM_ERROR_LOG" &

    local pid=$!
    echo "$pid" > "$TELEGRAM_PID_FILE"

    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        log_success "Telegram Bot started (PID: $pid)"
        return 0
    else
        log_error "Telegram Bot failed to start. Check: ${TELEGRAM_ERROR_LOG}"

        # Show last few lines of error log
        if [[ -f "$TELEGRAM_ERROR_LOG" ]]; then
            echo ""
            echo -e "${RED}Last error lines:${NC}"
            tail -n 5 "$TELEGRAM_ERROR_LOG" | sed 's/^/  /'
            echo ""
        fi

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
        rm -f "$TELEGRAM_PID_FILE"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# HEALTH MONITOR
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
# INTERACTIVE SETUP
# ─────────────────────────────────────────────────────────────────────────────

run_setup() {
    log_section "Interactive Environment Setup"

    echo ""
    echo "This will create a .env file with your configuration."
    echo "Press Ctrl+C at any time to cancel."
    echo ""

    local sb_url=""
    local sb_anon=""
    local sb_service=""
    local tg_token=""
    local smtp_host=""
    local smtp_user=""
    local smtp_pass=""

    read -rp "Supabase URL [https://your-project.supabase.co]: " sb_url
    read -rp "Supabase Anon Key [eyJ...]: " sb_anon
    read -rp "Supabase Service Role Key [eyJ...]: " sb_service
    read -rp "Telegram Bot Token (from @BotFather) [optional]: " tg_token
    read -rp "SMTP Host [smtp.gmail.com]: " smtp_host
    read -rp "SMTP User [your-email@gmail.com]: " smtp_user
    read -rsp "SMTP Password [app-specific-password]: " smtp_pass
    echo ""

    cat > "$ENV_FILE" << EOF
# PolyMarketAlphaAI — Environment Configuration
# Generated on $(date)

# Supabase
SUPABASE_URL=${sb_url}
SUPABASE_ANON_KEY=${sb_anon}
SUPABASE_SERVICE_ROLE_KEY=${sb_service}

# Telegram
TELEGRAM_BOT_TOKEN=${tg_token}

# Email (SMTP)
SMTP_HOST=${smtp_host:-smtp.gmail.com}
SMTP_PORT=587
SMTP_USER=${smtp_user}
SMTP_PASSWORD=${smtp_pass}
SMTP_FROM=${smtp_user}

# API
RESEARCH_API_URL=http://localhost:8000/research
PORT=8000
ENV=development
EOF

    chmod 600 "$ENV_FILE"
    log_success ".env file created at ${ENV_FILE}"
    log_info "File permissions set to 600 (owner read/write only)"
    echo ""
    log_info "You can now run: ./start_services.sh"
}

# ─────────────────────────────────────────────────────────────────────────────
# STATUS / LOGS
# ─────────────────────────────────────────────────────────────────────────────

show_status() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║           PolyMarketAlphaAI Service Status                   ║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  Environment: ${ENV_TYPE}"
    echo -e "${CYAN}║${NC}  Project:     ${SCRIPT_DIR}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════╣${NC}"

    if check_pid_running "$FASTAPI_PID_FILE"; then
        local pid
        pid=$(get_pid "$FASTAPI_PID_FILE")
        echo -e "${CYAN}║${NC}  FastAPI Backend   ${GREEN}● RUNNING${NC}   PID: ${pid}  Port: ${FASTAPI_PORT}"
    else
        echo -e "${CYAN}║${NC}  FastAPI Backend   ${RED}● STOPPED${NC}"
    fi

    if check_pid_running "$TELEGRAM_PID_FILE"; then
        local pid
        pid=$(get_pid "$TELEGRAM_PID_FILE")
        echo -e "${CYAN}║${NC}  Telegram Bot      ${GREEN}● RUNNING${NC}   PID: ${pid}"
    else
        echo -e "${CYAN}║${NC}  Telegram Bot      ${RED}● STOPPED${NC}"
    fi

    if [[ -f "${PID_DIR}/monitor.pid" ]]; then
        local monitor_pid
        monitor_pid=$(cat "${PID_DIR}/monitor.pid" 2>/dev/null || echo "")
        if [[ -n "$monitor_pid" ]] && kill -0 "$monitor_pid" 2>/dev/null; then
            echo -e "${CYAN}║${NC}  Health Monitor    ${GREEN}● RUNNING${NC}   PID: ${monitor_pid}"
        else
            echo -e "${CYAN}║${NC}  Health Monitor    ${RED}● STOPPED${NC}"
        fi
    else
        echo -e "${CYAN}║${NC}  Health Monitor    ${RED}● STOPPED${NC}"
    fi

    echo -e "${CYAN}╠══════════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}  Log Directory: ${LOG_DIR}"
    echo -e "${CYAN}║${NC}  PID Directory: ${PID_DIR}"
    echo -e "${CYAN}║${NC}  .env File:     ${ENV_FILE}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
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
# MAIN START/STOP
# ─────────────────────────────────────────────────────────────────────────────

start_all() {
    ensure_dirs
    load_env

    log_section "Starting PolyMarketAlphaAI Services"
    log_info "Environment: ${ENV_TYPE}"
    log_info "Project: ${SCRIPT_DIR}"

    local failed=0

    start_fastapi || failed=1
    start_telegram_bot || failed=1

    if [[ $failed -eq 0 ]]; then
        log_success "All services started successfully!"

        if [[ "${1:-}" == "--daemon" ]]; then
            log_info "Running in daemon mode with health monitoring..."
            health_monitor &
            local monitor_pid=$!
            echo "$monitor_pid" > "${PID_DIR}/monitor.pid"
            log_success "Health monitor started (PID: $monitor_pid)"
            log_info "To stop: ./start_services.sh --stop"
            disown
        else
            echo ""
            log_info "Press Ctrl+C to stop all services"
            echo ""
            trap 'stop_all; exit 0' INT TERM
            wait
        fi
    else
        log_error "Some services failed to start."
        log_info "Showing recent error logs..."
        echo ""

        if [[ -f "$FASTAPI_ERROR_LOG" ]]; then
            echo -e "${RED}--- FastAPI Errors ---${NC}"
            tail -n 10 "$FASTAPI_ERROR_LOG" | sed 's/^/  /'
            echo ""
        fi

        if [[ -f "$TELEGRAM_ERROR_LOG" ]]; then
            echo -e "${RED}--- Telegram Bot Errors ---${NC}"
            tail -n 10 "$TELEGRAM_ERROR_LOG" | sed 's/^/  /'
            echo ""
        fi

        stop_all
        exit 1
    fi
}

stop_all() {
    log_info "Stopping all PolyMarketAlphaAI services..."
    stop_fastapi
    stop_telegram_bot

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
    --setup)
        run_setup
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
  --setup         Interactive .env file setup
  --help, -h      Show this help message

Environment:
  The script automatically loads .env from the project directory.
  If .env is missing, run: ./start_services.sh --setup

Examples:
  ./start_services.sh              # Dev mode
  ./start_services.sh --daemon     # Production mode
  ./start_services.sh --status     # Check if running
  ./start_services.sh --logs       # Watch live logs
  ./start_services.sh --stop       # Stop everything

EOF
        ;;
    *)
        start_all
        ;;
esac
