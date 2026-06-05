#!/usr/bin/env bash
# Remove .venv if it was copied from another Mac (pip shebang points at wrong user/path).
# Usage: source scripts/ensure-venv.sh   OR   ./scripts/ensure-venv.sh

_ensure_venv_root() {
  if [[ -n "${ROOT:-}" ]]; then
    echo "$ROOT"
    return
  fi
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

_venv_is_broken() {
  local root="$1"
  local venv="$root/.venv"
  [[ -d "$venv" ]] || return 1
  [[ -x "$venv/bin/python3" || -x "$venv/bin/python" ]] || return 0

  if [[ -f "$venv/bin/pip" ]]; then
    local shebang
    shebang="$(head -1 "$venv/bin/pip")"
    if [[ "$shebang" == \#!* ]]; then
      local interp="${shebang#\#?}"
      interp="${interp%%$'\r'}"
      if [[ ! -x "$interp" ]]; then
        return 0
      fi
      local interp_dir
      interp_dir="$(cd "$(dirname "$interp")" 2>/dev/null && pwd -P)" || return 0
      local venv_bin
      venv_bin="$(cd "$venv/bin" && pwd -P)"
      if [[ "$interp_dir" != "$venv_bin" ]]; then
        return 0
      fi
    fi
  fi
  return 1
}

ensure_matrix_venv() {
  local root
  root="$(_ensure_venv_root)"
  if _venv_is_broken "$root"; then
    echo "==> Removing .venv from another computer (paths like /Users/vinnygilberti/... will not work here)"
    rm -rf "$root/.venv"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  ensure_matrix_venv
fi