#!/usr/bin/env bash
set -euo pipefail

scope=project
target=
source_dir=
apply_flag=
replace_flag=
uninstall_flag=
while (($#)); do
  case "$1" in
    --scope) scope="$2"; shift 2 ;;
    --target) target="$2"; shift 2 ;;
    --source) source_dir="$2"; shift 2 ;;
    --apply) apply_flag=--apply; shift ;;
    --replace-existing) replace_flag=--replace-existing; shift ;;
    --uninstall) uninstall_flag=--uninstall; shift ;;
    -h|--help) echo "Usage: setup.sh --target PATH [--scope global|project] [--apply] [--replace-existing] [--uninstall] [--source PATH]"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
if [[ -z "$target" ]]; then
  echo "--target is required; no home directory is inferred" >&2
  exit 2
fi
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
args=("$script_dir/scripts/install.py" --scope "$scope" --target "$target")
[[ -n "$source_dir" ]] && args+=(--source "$source_dir")
[[ -n "$apply_flag" ]] && args+=("$apply_flag")
[[ -n "$replace_flag" ]] && args+=("$replace_flag")
[[ -n "$uninstall_flag" ]] && args+=("$uninstall_flag")
exec python3 "${args[@]}"
