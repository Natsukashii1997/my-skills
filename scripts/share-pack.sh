#!/bin/sh
# 给同事打 skill 分享包：dist/share/<名字>-<版本>.zip，内含 skill 目录和 share/<名字>.md（改名为 INSTALL.md，避免 Windows 解压中文名乱码）。
# 用法：sh scripts/share-pack.sh <skill名> [<skill名> ...]    只打包，不发送。
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT="$ROOT/dist/share"
mkdir -p "$OUT"
for name in "$@"; do
  dir="$ROOT/skills/$name"
  [ -f "$dir/SKILL.md" ] || { echo "没有 skills/$name/SKILL.md" >&2; exit 1; }
  [ -f "$ROOT/share/$name.md" ] || { echo "没有 share/$name.md（自装说明）" >&2; exit 1; }
  ver=$(sed -n 's/^  version: *"\{0,1\}\([^"]*\)"\{0,1\} *$/\1/p' "$dir/SKILL.md" | head -1)
  [ -n "$ver" ] || { echo "skills/$name/SKILL.md 没有 metadata.version" >&2; exit 1; }
  tmp=$(mktemp -d)
  mkdir "$tmp/$name"
  (cd "$dir" && find . -name __pycache__ -prune -o -name .DS_Store -prune -o -type f -print | while read -r f; do
     mkdir -p "$tmp/$name/$(dirname "$f")"; cp "$f" "$tmp/$name/$f"; done)
  cp "$ROOT/share/$name.md" "$tmp/$name/INSTALL.md"
  zip="$OUT/$name-$ver.zip"
  rm -f "$zip"
  (cd "$tmp" && zip -qr "$zip" "$name")
  rm -rf "$tmp"
  echo "$zip"
done
