# 定时备份（launchd）

脚本**不会**自己装定时任务。下面每一步都要用户同意后再做。

## 装之前

- 先手动跑通：`backup` 成功、`restore-drill` 通过。
- 时间在配置里改：`schedule = 12:30, 21:30`（可以写多个）。

## 安装

```bash
VB=~/.claude/skills/vault-backup/scripts/vault_backup.py
python3 "$VB" plist > ~/Library/LaunchAgents/local.vault-backup.plist   # 生成定时任务文件（只是写文件）
plutil -lint ~/Library/LaunchAgents/local.vault-backup.plist             # 检查格式，应显示 OK
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.vault-backup.plist   # 正式启用
launchctl kickstart -k gui/$(id -u)/local.vault-backup                   # 立刻跑一次试试
tail -40 ~/Library/Logs/vault-backup.log                                  # 看结果
```

生成的文件做的事：在设定时间运行 `vault_backup.py backup --notify`，输出写到 `~/Library/Logs/vault-backup.log`；出问题或好几天没备份成功时，弹一条 macOS 通知。

## 第一次定时运行可能遇到的（待在真机上验证）

云端测试环境是 Linux，下面两条无法在那里验证，装好后按日志判断：

1. **日志里有 `operation not permitted` 或「有些文件没读到」**：macOS 不让后台任务读「文稿」。打开 系统设置 → 隐私与安全性 → 完全磁盘访问权限，点 +，加入 plist 里 `ProgramArguments` 第一行的那个 python3（`grep -A1 ProgramArguments ~/Library/LaunchAgents/local.vault-backup.plist` 可看到路径；在「前往文件夹」里粘贴路径即可选中）。仍不行，再把 `which restic` 显示的 restic 也加进去。改完再 `kickstart` 一次。
2. **日志里有「没找到备份密码」或「密码不对」**：后台任务读的是同一个登录钥匙串，正常登录状态下可以读到。如果弹出「security 想要访问钥匙串」，点「始终允许」。

## 平时

- Mac 在设定时间睡眠：醒来后补跑一次。关机错过：不补，下一个时间点再跑。
- 外置盘没插：这次跳过外置盘，其他位置照常；超过 `warn_after_days` 天没成功会弹通知。
- 看最近情况：`status`，或 `tail -40 ~/Library/Logs/vault-backup.log`。日志每次十几行，一年也只有几 MB，不用管。

## 改时间

改配置里的 `schedule`，然后：

```bash
launchctl bootout gui/$(id -u)/local.vault-backup
python3 "$VB" plist > ~/Library/LaunchAgents/local.vault-backup.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.vault-backup.plist
```

## 卸载

```bash
launchctl bootout gui/$(id -u)/local.vault-backup
mv ~/Library/LaunchAgents/local.vault-backup.plist ~/.Trash/   # 移到废纸篓，想恢复还能拿回来
```

卸载只是停掉定时，备份库和里面的历史版本都不动。
