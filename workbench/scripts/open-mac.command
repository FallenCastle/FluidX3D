#!/bin/zsh
set -eu
# One foreground SSH connection owns the service and forwards its loopback port.
# Ctrl+C closes this connection. Windows Job Objects terminate owned calculations.
port="${SOLVER_WEB_PORT:-8765}"
remote_checkout="${SOLVER_WEB_CHECKOUT:-F:\\01-Project\\Opensource\\01-FluidX3D\\web-src}"
case "$port" in (*[!0-9]*|'') print -u2 'SOLVER_WEB_PORT must be numeric'; exit 1;; esac
if [[ "$remote_checkout" == *'"'* || "$remote_checkout" == *'$'* || "$remote_checkout" == *'`'* ]]; then
  print -u2 'Invalid SOLVER_WEB_CHECKOUT'; exit 1
fi
url="http://127.0.0.1:$port"
print "工作台地址：$url"
print '请保持此终端运行；关闭连接前，在界面确认任务已结束。'
print '如 Windows 已单独启动服务，可使用 ssh -N -L 8765:127.0.0.1:8765 desktop-msi。'
(
  for attempt in {1..60}; do
    if /usr/bin/curl --noproxy '*' -fsS "$url/api/session" >/dev/null 2>&1; then
      /usr/bin/open "$url"
      exit 0
    fi
    sleep 1
  done
) &
opener_pid=$!
trap 'kill "$opener_pid" 2>/dev/null || true' EXIT INT TERM
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L "127.0.0.1:$port:127.0.0.1:$port" desktop-msi \
  "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"$remote_checkout\\workbench\\scripts\\start-windows.ps1\" -Port $port"
