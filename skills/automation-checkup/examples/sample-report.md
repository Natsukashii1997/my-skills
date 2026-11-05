# 自动化体检报告

体检时间：2026-11-05 10:30（本机时间）　检查了 15 个自建后台任务，按配置跳过 1 个系统或第三方任务。

**结论：需要处理 10 项，注意 5 项，正常 3 项。**

最该先看的：
- 飞书频道桥 `ai.lark-channel-bridge.server`：常驻服务现在正在等待重启（多半刚崩溃，被系统限速）；上次退出码 1（一般性错误，程序自己报错退出，具体原因要看日志）。本次登录以来已启动 3 次。
- 路觅工作任务 `com.lumiedu.weekly-report`：上次运行失败：上次退出码 127（找不到命令：launchd 的 PATH 比终端里短，脚本里用到的命令可能找不到）。
- 数字分身 `cn.digital-twin.healthcheck`：疑似该跑没跑：日志停在 11 月 2 日 10:30（3 天前），按计划这之后应该运行 143 次。

> 这份报告是只读生成的：没有启动、停止、重启或修改任何任务，也没有动任何文件。
> 下面的「建议」都还没做；要处理哪一条，告诉 agent 条目编号，它会先跟你确认再动手。

## 需要处理（10）

### 1. 飞书频道桥 `ai.lark-channel-bridge.server`

- **问题**：常驻服务现在正在等待重启（多半刚崩溃，被系统限速）；上次退出码 1（一般性错误，程序自己报错退出，具体原因要看日志）。本次登录以来已启动 3 次。
  **建议**：先看下面的日志末尾找原因；原因清楚后再重启它。
- 计划：常驻：登录时启动，退出后自动重启
- 运行状态：等待重启，本次登录以来启动 3 次
- 上次退出码：1，一般性错误，程序自己报错退出，具体原因要看日志
- 程序：`~/projects/lark-bridge/server.js` 存在
- 日志最后更新：今天 10:28（2 分钟前）

<details><summary>错误日志末尾 2 行：<code>~/logs/lark-bridge.err.log</code></summary>

```text
Error: Cannot find module 'ws'
    at Module._resolveFilename (node:internal/modules/cjs/loader:1145:15)
```
</details>

### 2. 路觅工作任务 `com.lumiedu.weekly-report`

- **问题**：上次运行失败：上次退出码 127（找不到命令：launchd 的 PATH 比终端里短，脚本里用到的命令可能找不到）。
  **建议**：看下面的日志末尾找原因；修好后可以手动触发一次确认。
- 计划：每周一 09:00
- 运行状态：待命，到点才运行，本次登录以来启动 1 次
- 上次退出码：127，找不到命令：launchd 的 PATH 比终端里短，脚本里用到的命令可能找不到
- 命令：`cd ~/work/weekly && ./run.sh > ~/work/weekly/out.txt`
- 日志最后更新：11 月 2 日 09:00（3 天前）
- 按计划最近一次应运行：11 月 2 日 09:00（3 天前）

<details><summary>日志末尾 1 行：<code>~/work/weekly/weekly.log</code></summary>

```text
zsh:1: command not found: lark-cli
```
</details>

### 3. 数字分身 `cn.digital-twin.healthcheck`

- **问题**：疑似该跑没跑：日志停在 11 月 2 日 10:30（3 天前），按计划这之后应该运行 143 次。
  **建议**：先确认电脑那段时间是不是关机了；不是的话看日志末尾和 launchd 状态找原因。如果这个任务平时就不写日志，把它加到 config.json 的 quiet_labels 里，以后不再按日志判断。
- 计划：每 30 分钟；登录时运行一次
- 运行状态：待命，到点才运行，本次登录以来启动 2 次
- 上次退出码：0，正常结束
- 程序：`~/projects/digital-twin/healthcheck.sh` 存在
- 日志最后更新：11 月 2 日 10:30（3 天前）

<details><summary>日志末尾 1 行：<code>~/logs/digital-twin.log</code></summary>

```text
health ok
```
</details>

### 4. GitHub 中心 `cn.github-center.pull`

- **问题**：plist 文件在，但 launchd 里没有这个任务：它现在根本不会运行（可能被手动卸载过，或加载时出错）。
  **建议**：确认还要不要这个任务：要就重新加载，不要就把 plist 挪走（否则下次登录它又会自己回来）。
- 计划：每 15 分钟
- 运行状态：没有加载到 launchd
- 程序：`~/scripts/backup.sh` 存在
- 日志：plist 里没配

### 5. `cn.lumiedu.moved.plist`

- **问题**：`cn.lumiedu.moved.plist` 是个链接，指向的 `~/projects/moved-away/cn.lumiedu.moved.plist` 已经不存在，launchd 加载不了它（多半是项目挪了位置或删了）。
  **建议**：确认这个任务还要不要：要就把链接改到 plist 的新位置，不要就把这个链接挪出 LaunchAgents。

### 6. 数字世界 `local.digitalworld.sync`

- **问题**：僵尸任务：要运行的脚本 `~/projects/digitalworld/sync.sh` 已经不存在（多半是项目挪了位置或删了）。
  **建议**：确认这个任务还要不要：不要了就停用并把 plist 挪出 LaunchAgents；还要的话把路径改到脚本的新位置。
- **问题**：`local.digitalworld.sync.backup.plist`、`local.digitalworld.sync.plist` 用的是同一个 Label，launchd 只会加载其中一个，另一个等于没生效，改配置时很容易改错文件。
  **建议**：确认哪个是在用的，把另一个挪出 LaunchAgents。
- 计划：每 10 分钟
- 运行状态：待命，到点才运行，本次登录以来启动 9 次
- 上次退出码：127，找不到命令：launchd 的 PATH 比终端里短，脚本里用到的命令可能找不到
- 程序：`~/projects/digitalworld/sync.sh` **不存在**
- 日志：plist 里没配

### 7. 数字世界 `local.digitalworld.sync`（文件 `local.digitalworld.sync.backup.plist`）

- **问题**：僵尸任务：要运行的脚本 `~/projects/digitalworld/sync.sh` 已经不存在（多半是项目挪了位置或删了）。
  **建议**：确认这个任务还要不要：不要了就停用并把 plist 挪出 LaunchAgents；还要的话把路径改到脚本的新位置。
- **问题**：`local.digitalworld.sync.backup.plist`、`local.digitalworld.sync.plist` 用的是同一个 Label，launchd 只会加载其中一个，另一个等于没生效，改配置时很容易改错文件。
  **建议**：确认哪个是在用的，把另一个挪出 LaunchAgents。
- **问题**［注意］：文件名 `local.digitalworld.sync.backup.plist` 像备份，但仍以 .plist 结尾，launchd 登录时会照样加载它。
  **建议**：如果它是备份，把它挪出 LaunchAgents；如果在用，改个正经名字。
- 计划：每 10 分钟
- 运行状态：待命，到点才运行，本次登录以来启动 9 次
- 上次退出码：127，找不到命令：launchd 的 PATH 比终端里短，脚本里用到的命令可能找不到
- 程序：`~/projects/digitalworld/sync.sh` **不存在**
- 日志：plist 里没配

### 8. Codex 相关 `ai.ops.codex`

- **问题**：输出日志所在的文件夹 `~/no-such-dir` 不存在，launchd 常因此直接启动失败。
  **建议**：建好这个文件夹，或把日志路径改到存在的位置。
- 计划：每 5 分钟
- 运行状态：待命，到点才运行，本次登录以来启动 30 次
- 上次退出码：0，正常结束
- 程序：`~/scripts/ops.sh` 存在
- 日志最后更新：日志文件不存在

### 9. crontab 定时任务（2 条）

- **问题**：crontab 这条指向的文件不存在：`~/scripts/gone.sh`，每次到点都会失败。
  **建议**：确认这条还要不要；不要了就从 crontab 里删掉这一行，要就改成正确路径。
- `0 3 * * * ~/scripts/backup.sh >> ~/logs/backup.log 2>&1`
- `30 7 * * 1 ~/scripts/gone.sh`

### 10. `broken.plist`

- **问题**：plist 文件读不出来（ExpatError），launchd 也加载不了它。
  **建议**：让 agent 用 `plutil -lint` 查出具体哪里坏了再修；不用了就挪走。

## 注意（5）

### 11. 飞书网关 Hermes `ai.hermes.gateway`

- **问题**：常驻服务现在在跑，但本次登录以来启动了 7 次，有过崩溃重启；上次退出码 75（EX_TEMPFAIL：临时失败，程序自己报告「暂时不行，稍后再试」，常见于网络或连接断开）。
  **建议**：目前能用。看一下日志末尾，判断是偶发断线还是反复出错；反复出错再处理。
- 计划：常驻：登录时启动，退出后自动重启
- 运行状态：正在运行，PID 48211，本次登录以来启动 7 次
- 上次退出码：75，EX_TEMPFAIL：临时失败，程序自己报告「暂时不行，稍后再试」，常见于网络或连接断开
- 程序：`~/.local/bin/hermes` 存在
- 日志最后更新：今天 10:20（10 分钟前）

<details><summary>错误日志末尾 3 行：<code>~/.hermes/logs/gateway.err.log</code></summary>

```text
2026-11-05 07:28:01 WARNING reconnecting
2026-11-05 07:29:12 ERROR websocket disconnected: app_secret=[已隐藏] Bearer [已隐藏]
2026-11-05 07:29:13 exiting with EX_TEMPFAIL
```
</details>

<details><summary>输出日志末尾 15 行：<code>~/.hermes/logs/gateway.log</code></summary>

```text
[info] heartbeat 15
[info] heartbeat 16
[info] heartbeat 17
[info] heartbeat 18
[info] heartbeat 19
[info] heartbeat 20
[info] heartbeat 21
[info] heartbeat 22
[info] heartbeat 23
[info] heartbeat 24
[info] heartbeat 25
[info] heartbeat 26
[info] heartbeat 27
[info] heartbeat 28
[info] heartbeat 29
```
</details>

### 12. 牛马之家 `cn.niuma-home.worker`

- **问题**：疑似该跑没跑：日志停在 今天 08:30（2 小时前），按计划这之后应该运行 1 次。
  **建议**：先确认电脑那段时间是不是关机了；不是的话看日志末尾和 launchd 状态找原因。如果这个任务平时就不写日志，把它加到 config.json 的 quiet_labels 里，以后不再按日志判断。
- 计划：每 1 小时
- 运行状态：待命，到点才运行，本次登录以来启动 8 次
- 上次退出码：0，正常结束
- 程序：`~/projects/niuma/worker.sh` 存在
- 日志最后更新：今天 08:30（2 小时前）

<details><summary>输出日志末尾 1 行：<code>~/logs/niuma-worker.log</code></summary>

```text
worker done
```
</details>

### 13. hermes 定时任务（hermes cron list）

- **问题**：hermes 定时任务列表里有 2 行带失败、暂停或停用字样：`c-03      旧群同步             */30 * * * *    -                     paused`；`c-04      数据回流             15 * * * *      2026-11-05 11:15      error (last run failed: token=[已隐藏]`。
  **建议**：让 agent 对照下面的原始输出逐条解释；确认是故意暂停的就不用管。

```text
ID        NAME                 SCHEDULE        NEXT RUN              STATUS
c-01      早报汇总             0 8 * * *       2026-11-06 08:00      active
c-02      周报提醒             0 17 * * 5      2026-11-06 17:00      active
c-03      旧群同步             */30 * * * *    -                     paused
c-04      数据回流             15 * * * *      2026-11-05 11:15      error (last run failed: token=[已隐藏]
```

### 14. 个人 AI 工作台 `cn.personal-ai-workbench.server`

- **问题**：这个任务已被停用，不会自动运行，但 plist 文件还在。
  **建议**：确认不用了就把 plist 挪出 LaunchAgents（先挪到备份文件夹，不要直接删）；还要用就重新启用。
- 计划：常驻：登录时启动，退出后自动重启
- 运行状态：没有加载到 launchd（已停用）
- 程序：`~/projects/niuma/server.js` 存在
- 日志：plist 里没配

### 15. LaunchAgents 里的残留文件

- **问题**：有 2 个不以 .plist 结尾的残留文件。launchd 一般不会加载它们，但留着容易和在用的配置混淆，改错文件。
  **建议**：确认没用后统一挪到一个备份文件夹（例如 ~/Library/LaunchAgents.retired/），不要直接删。
- `ai.hermes.gateway.plist.bak`：是在用任务 `ai.hermes.gateway` 的旧版本或备份
- `cn.old-thing.plist.disabled`：对应的任务 `cn.old-thing` 已经不在用

## 正常（3）

| 任务 | 计划 | 状态 | 日志最后更新 |
|---|---|---|---|
| Codex 额度守护 `com.openai.codex-quota-guard` | 每 10 分钟 | 待命，到点才运行，本次登录以来启动 12 次 | 没配日志 |
| 牛马之家 `cn.niuma-home.web` | 常驻：登录时启动，退出后自动重启 | 正在运行，PID 1234，本次登录以来启动 1 次 | 今天 10:29（1 分钟前） |
| 路觅工作任务 `cn.lumiedu.campaign-daily` | 每天 09:00 | 待命，到点才运行，本次登录以来启动 4 次 | 今天 09:00（1 小时前） |

## 说明与盲区

- 1 个定时任务在 plist 里没配输出日志，没法判断它们有没有按时运行：Codex 额度守护 `com.openai.codex-quota-guard`。
- hermes 定时任务：已读取
- crontab：2 条
- 检查的目录：`~/Library/LaunchAgents`
- 按配置跳过（系统或第三方）：`com.google.keystone.agent.plist`
- 「该跑没跑」是用日志文件的最后修改时间推断的：任务平时不写日志、或电脑那段时间关机，都会让判断偏严。
- 本次只执行了这些查看命令：`crontab -l`、`hermes cron list`、`launchctl print`、`launchctl print-disabled`
