#!/bin/sh
# 按 links.tsv 把 skills/<名字> 软链接到各工具的 skill 目录。可重复执行；目标已是真实目录时跳过，不覆盖。
# 只在主目录跑：在 worktree 里跑，链接会指向 worktree，worktree 删掉后就全断了。
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
tab=$(printf '\t')
status=0

if git_dir=$(git -C "$repo" rev-parse --absolute-git-dir 2>/dev/null); then
  common_dir=$(cd "$repo" && cd "$(git rev-parse --git-common-dir)" && pwd)
  if [ "$git_dir" != "$common_dir" ]; then
    echo "这是 worktree（$repo），不建链接。PR 合进 main 后，到主目录 $(dirname "$common_dir") 再跑。" >&2
    exit 1
  fi
fi

dirs=""
while IFS="$tab" read -r name dir; do
  case "$name" in ''|'#'*) continue ;; esac
  case "$dir" in '~/'*) dir="$HOME/${dir#\~/}" ;; esac
  src="$repo/skills/$name"
  dst="$dir/$name"
  if [ ! -f "$src/SKILL.md" ]; then
    echo "缺少 $src/SKILL.md" >&2; status=1; continue
  fi
  declared=$(sed -n 's/^name:[[:space:]]*//p' "$src/SKILL.md" | head -1 | tr -d "\"' \r")
  if [ "$declared" != "$name" ]; then
    echo "跳过 $name：SKILL.md 里的 name 是「$declared」，要和目录名一致" >&2; status=1; continue
  fi
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "跳过 $dst：是真实目录，先挪走再链接" >&2; status=1; continue
  fi
  mkdir -p "$dir"
  ln -sfn "$src" "$dst"
  echo "$dst -> $src"
  case " $dirs " in *" $dir "*) ;; *) dirs="$dirs $dir" ;; esac
done < "$repo/links.tsv"

# 改名或删掉 skill 后，工具目录里会留下指向本仓库的断链；只提示，不自动删
for dir in $dirs; do
  for link in "$dir"/*; do
    [ -L "$link" ] && [ ! -e "$link" ] || continue
    case "$(readlink "$link")" in
      "$repo/skills/"*) echo "断链 $link -> $(readlink "$link")，确认不用了就 rm 掉这个链接" >&2 ;;
    esac
  done
done

exit $status
