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

1. **日志里有 `operation not permitted` 或「有些文件没读到」**：macOS 没让后台任务读「文稿」（知识库就在里面）。按从窄到宽处理，能用窄的就别用宽的：
   - **先只开「文稿」**：第一次 `kickstart` 时留意有没有弹窗「python3 想访问“文稿”文件夹中的文件」，点「允许」。这只开放文稿，不开放整个硬盘；之后在 系统设置 → 隐私与安全性 → 文件和文件夹 里能看到这一项。没注意到弹窗，就再 `kickstart` 一次。
   - **没有弹窗、仍然读不到，才考虑「完全磁盘访问权限」**。先把代价讲给用户、等他同意：这个权限是给 python3 这个程序的，以后**任何**由它运行的脚本（不只是备份）都能读整个硬盘，包括邮件、聊天记录、其他应用的数据。用户同意后：系统设置 → 隐私与安全性 → 完全磁盘访问权限，点 +，加入 plist 里 `ProgramArguments` 第一行的那个 python3（`grep -A1 ProgramArguments ~/Library/LaunchAgents/local.vault-backup.plist` 可看到路径；在「前往文件夹」里粘贴路径即可选中）。restic 是由这个 python3 启动的，macOS 按启动它的 python3 判断权限，所以不用另给 restic 加。改完再 `kickstart` 一次。
   - 不要为此给「终端」开完全磁盘访问：那等于给终端里运行的所有东西开权限。
2. **日志里有「没找到备份密码」或「密码不对」**：后台任务读的是同一个登录钥匙串，正常登录状态下可以读到。如果弹出「security 想要访问钥匙串」，点「始终允许」。

## 平时

- Mac 在设定时间睡眠：醒来后补跑一次。关机错过：不补，下一个时间点再跑。
- 外置盘没插：这次跳过外置盘，其他位置照常；超过 `warn_after_days` 天没成功会弹通知。
- 看最近情况：`status`，或 `tail -40 ~/Library/Logs/vault-backup.log`。日志每次十几行，一年也只有几 MB，不用管。

## 改时间

改配置里的 `schedule`，然后：

```bash
L=gui/$(id -u)/local.vault-backup
P=~/Library/LaunchAgents/local.vault-backup.plist
launchctl bootout "$L"
# bootout 是异步的：命令返回时旧任务可能还没卸完，马上 bootstrap 会偶尔报
# 「Bootstrap failed: 5」，任务就卸下了却没装回去（全局坑 G-18）。所以等它查不到了再装，最多等 10 秒。
for i in $(seq 20); do launchctl print "$L" >/dev/null 2>&1 || break; sleep 0.5; done
python3 "$VB" plist > "$P"
plutil -lint "$P"
# 装回去；失败隔 3 秒重试，最多 3 次
for i in 1 2 3; do launchctl bootstrap gui/$(id -u) "$P" && break; sleep 3; done
launchctl print "$L" | grep -E "state|path"   # 能看到这几行才算装回去了
```

最后一行什么都没显示，说明任务没装回去：plist 已经写好，再单独运行一次 `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.vault-backup.plist`，然后用 `status` 确认「定时备份：已安装」。

## 卸载

```bash
launchctl bootout gui/$(id -u)/local.vault-backup
mv ~/Library/LaunchAgents/local.vault-backup.plist ~/.Trash/   # 移到废纸篓，想恢复还能拿回来
```

卸载只是停掉定时，备份库和里面的历史版本都不动。
