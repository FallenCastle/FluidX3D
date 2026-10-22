#!/bin/zsh
set -eu
# Windows owns the execution service. This terminal owns only its SSH tunnel.
port="${SOLVER_WEB_PORT:-8765}"
remote_checkout="${SOLVER_WEB_CHECKOUT:-F:\\01-Project\\Opensource\\01-FluidX3D\\web-src}"
case "$port" in (*[!0-9]*|'') print -u2 'SOLVER_WEB_PORT must be numeric'; exit 1;; esac
if [[ "$remote_checkout" == *'"'* || "$remote_checkout" == *'$'* || "$remote_checkout" == *'`'* ]]; then
  print -u2 'Invalid SOLVER_WEB_CHECKOUT'; exit 1
fi
url="http://127.0.0.1:$port"
if /usr/bin/curl --noproxy '*' -fsS --max-time 2 "$url/api/session" 2>/dev/null | /usr/bin/grep -q '"product": "Solver-IBM"'; then
  print "工作台已连接：$url"
  /usr/bin/open "$url"
  exit 0
fi
print "工作台地址：$url"
print '请保持此终端运行以访问网页；关闭终端只断开连接，Windows 任务会继续。'
ssh -o ConnectTimeout=10 desktop-msi \
  "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"$remote_checkout\\workbench\\scripts\\start-windows.ps1\" -Port $port -Background"
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
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L "127.0.0.1:$port:127.0.0.1:$port" desktop-msi
