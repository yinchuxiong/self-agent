#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start.sh — 一键启动 self-agent 前后端开发服务
#
# 用法:
#   ./start.sh            # 启动前后端
#   ./start.sh backend     # 仅启动后端
#   ./start.sh frontend    # 仅启动前端
#
# 后端: http://localhost:8000  (API: /api/health)
# 前端: http://localhost:5173
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── Python 解释器（优先用 3.11+）──────────────────────────────────────────
PYTHON=""
for candidate in \
  "/c/Users/yincx/AppData/Local/Programs/Python/Python311/python.exe" \
  python3.11 python3.12 python3 python; do
  if command -v "$candidate" &>/dev/null || [ -x "$candidate" ]; then
    ver=$("$candidate" -c "import sys; print(sys.version_info[:2])" 2>/dev/null || echo "(0,0)")
    major=$(echo "$ver" | grep -oP '\d+' | head -1)
    if [ "${major:-0}" -ge 11 ]; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "❌ 未找到 Python 3.11+，请确认已安装并加入 PATH"
  exit 1
fi
echo "✓ Python: $("$PYTHON" --version)"

# ── Node.js ────────────────────────────────────────────────────────────────
if ! command -v npm &>/dev/null; then
  echo "❌ 未找到 npm，请安装 Node.js"
  exit 1
fi
echo "✓ Node:  $(node --version)"
echo "✓ npm:   $(npm --version)"

# ── 颜色 ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# ── 清理函数：Ctrl+C 时同时杀前后端 ───────────────────────────────────────
cleanup() {
  echo ""
  echo -e "${CYAN}正在停止服务...${NC}"
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null && echo "  ✓ 后端已停止"
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null && echo "  ✓ 前端已停止"
  echo -e "${GREEN}已退出${NC}"
  exit 0
}
trap cleanup SIGINT SIGTERM

# ── 安装依赖 ───────────────────────────────────────────────────────────────
install_deps() {
  # Python
  if [ ! -d ".venv" ] && [ ! -f "uv.lock" ]; then
    echo -e "${CYAN}安装 Python 依赖...${NC}"
    "$PYTHON" -m pip install -e ".[dev]" --quiet 2>&1 | tail -1
  fi

  # Frontend
  if [ ! -d "frontend/node_modules" ]; then
    echo -e "${CYAN}安装前端依赖...${NC}"
    cd frontend && npm install --silent 2>&1 | tail -3 && cd "$ROOT"
  fi
}

# ── 启动后端 ───────────────────────────────────────────────────────────────
start_backend() {
  echo ""
  echo -e "${BOLD}${GREEN}▶ 启动后端 (uvicorn)${NC}"
  "$PYTHON" -m uvicorn self_agent.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --log-level info &
  BACKEND_PID=$!
  echo "  后端 PID: $BACKEND_PID  |  http://localhost:8000"
  echo "  API 文档: http://localhost:8000/docs"
}

# ── 启动前端 ───────────────────────────────────────────────────────────────
start_frontend() {
  echo ""
  echo -e "${BOLD}${GREEN}▶ 启动前端 (Vite)${NC}"
  cd frontend
  npm run dev &
  FRONTEND_PID=$!
  cd "$ROOT"
  echo "  前端 PID: $FRONTEND_PID  |  http://localhost:5173"
}

# ── 主流程 ─────────────────────────────────────────────────────────────────
MODE="${1:-all}"

install_deps

case "$MODE" in
  backend)
    start_backend
    ;;
  frontend)
    start_frontend
    ;;
  all)
    start_backend
    sleep 1
    start_frontend
    ;;
  *)
    echo "用法: $0 [backend|frontend|all]"
    exit 1
    ;;
esac

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  后端: http://localhost:8000${NC}"
echo -e "${GREEN}  前端: http://localhost:5173${NC}"
echo -e "${CYAN}  按 Ctrl+C 停止所有服务${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# 等待任意子进程退出
wait
