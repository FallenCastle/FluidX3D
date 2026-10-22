#!/bin/zsh
script_dir="${0:A:h}"
if ! command -v python3 >/dev/null 2>&1; then
  print -u2 '需要 Python 3。请先安装 Python 3 或 Xcode Command Line Tools。'
  read '?按回车关闭此窗口…'
  exit 1
fi
python3 "$script_dir/mac-workbench.py" stop "$@"
result=$?
if [[ -t 0 ]]; then read '?按回车关闭此窗口…'; fi
exit "$result"
