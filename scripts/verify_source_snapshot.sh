#!/usr/bin/env bash
set -euo pipefail

if (($# != 1)); then
  printf 'usage: %s SNAPSHOT_DIRECTORY\n' "$0" >&2
  exit 2
fi

task_snapshot=$1
for task_subtree in recipe upstream toolchain-source cargo; do
  task_path="$task_snapshot/$task_subtree"
  if [[ ! -d "$task_path" || -z $(find "$task_path" -mindepth 1 -print -quit) ]]; then
    printf 'source snapshot subtree is empty: %s\n' "$task_subtree" >&2
    exit 1
  fi
done
