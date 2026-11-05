# 真要找回文件时

原则：**先恢复到一个新文件夹，看过没问题，再由用户自己挪回去。** 不直接覆盖知识库。

下面的命令直接用 restic，不依赖本 skill，换了电脑也能照做。先让 restic 能拿到密码：

```bash
# 这台 Mac 上：从钥匙串取
export RESTIC_PASSWORD_COMMAND="security find-generic-password -s vault-backup -a restic-password -w"
# 新电脑上：钥匙串里还没有，就临时输入（-s 不回显）
read -rs RESTIC_PASSWORD && export RESTIC_PASSWORD
```

`<位置>` 就是配置里 `target = 名字 | 位置` 竖线右边那段。用 S3/B2 时还要 `export AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=…`。

## 情况一：要最新那份完整拷贝

最省事：用演练命令，加 `--keep` 保留、`--to` 放到桌面：

```bash
python3 "$VB" restore-drill --keep --to ~/Desktop/找回 --source "Obsidian Vault"
```

文件在 `~/Desktop/找回/vault-backup-drill-<随机字符>/Users/<用户名>/Documents/Obsidian Vault/` 下。会顺便和现在的知识库比一遍，告诉你哪些不一样。用完自己删掉这个文件夹。

## 情况二：误删或改坏了，要回到某个时间点

```bash
restic -r <位置> snapshots --path "$HOME/Documents/Obsidian Vault"     # 列出所有版本和时间
restic -r <位置> ls <版本ID> | grep "某篇笔记"                         # 看那个版本里有没有它
restic -r <位置> restore <版本ID> --target ~/Desktop/找回 \
    --include "$HOME/Documents/Obsidian Vault/笔记/某篇笔记.md"         # 只取一篇；去掉 --include 取整个库
```

恢复出来的文件在 `~/Desktop/找回/Users/<用户名>/Documents/Obsidian Vault/…` 下面（保留了原来的完整路径）。

## 情况三：电脑没了，在新电脑上全部取回

需要：① 备份密码（另存的那份）；② 能访问备份位置（插上外置盘 / 登录同一个 Apple ID 并等 iCloud 云盘把 `vault-backup` 下载完 / S3 密钥）。

```bash
brew install restic
read -rs RESTIC_PASSWORD && export RESTIC_PASSWORD
restic -r <位置> snapshots                                   # 能列出版本，说明密码和位置都对
restic -r <位置> restore latest --target ~/Desktop/恢复
```

然后把 `~/Desktop/恢复/Users/<旧用户名>/Documents/Obsidian Vault` 挪到想放的位置，用 Obsidian 打开。`.git` 也在里面，git 历史一起回来了。最后照 SKILL.md「第一次设置」在新电脑上重新配一遍。
