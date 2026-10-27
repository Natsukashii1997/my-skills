#!/bin/sh
# 按 links.tsv 把 skills/<名字> 软链接到各工具的 skill 目录。可重复执行；目标已是真实目录时跳过，不覆盖。
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
tab=$(printf '\t')
status=0

while IFS="$tab" read -r name dir; do
  case "$name" in ''|'#'*) continue ;; esac
  case "$dir" in '~/'*) dir="$HOME/${dir#\~/}" ;; esac
  src="$repo/skills/$name"
  dst="$dir/$name"
  if [ ! -f "$src/SKILL.md" ]; then
    echo "缺少 $src/SKILL.md" >&2; status=1; continue
  fi
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "跳过 $dst：是真实目录，先挪走再链接" >&2; status=1; continue
  fi
  mkdir -p "$dir"
  ln -sfn "$src" "$dst"
  echo "$dst -> $src"
done < "$repo/links.tsv"

exit $status
