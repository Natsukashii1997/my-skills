---
name: automation-checkup
description: 「自动化体检」：只读检查常浩 Mac 上所有自建的定时任务和常驻服务（~/Library/LaunchAgents 里的 launchd 任务，加上 hermes cron 和 crontab），出一页报告，分「需要处理 / 注意 / 正常」三档，每条给一句人话解释和建议动作。用户说「体检一下自动化」「看看定时任务 / 后台服务有没有挂」「Hermes 网关是不是又挂了」「哪些自动化该跑没跑」「LaunchAgents 里有没有僵尸任务」时使用。体检本身不加载、不停止、不重启任何任务，也不改文件；用户点名要处理某一条时，按 references/actions.md 逐条确认后再动手。
metadata:
  governance:
    network: none
    external-writes: required
    destructive-actions: none
    credentials: none
    dependencies:
      - python3
---

# 自动化体检

目标：常浩本机跑着一堆自建自动化（飞书网关 Hermes、数字分身、牛马之家、路觅的营销任务等），挂了往往不会第一时间发现。这个 skill 把它们全部过一遍，用一页报告说清楚：哪些要马上处理，哪些留意一下，哪些正常。

分工：脚本负责确定性的检查和判档（读 plist、`launchctl` 状态、日志时间）；agent 负责把报告讲成人话、解读脚本读不懂的原始输出（hermes cron）；要不要处理、处理哪条，由常浩决定。

## 一、跑体检

```bash
S=~/.claude/skills/automation-checkup/scripts      # Codex 用 ~/.agents/skills/automation-checkup/scripts
python3 $S/checkup.py
```

- 报告默认写到 `~/Documents/自动化体检/自动化体检-日期时间.md`，终端打印报告路径和三档计数。
- `--stdout` 直接打印报告；`--out 路径` 指定位置；`--json 路径` 另存结构化结果；`--no-hermes`、`--no-crontab` 跳过对应检查。
- 只需要 macOS 自带的 python3，不装任何依赖。

## 二、跑完怎么回复

1. 先一句结论：「需要处理 X 项，注意 Y 项，其余正常」，给出报告路径。
2. 「需要处理」逐条用人话讲：是哪个自动化（用报告里的中文名）、出了什么事、对业务有什么影响、建议怎么做。日志原文不要整段贴，挑能说明原因的一两行。
3. 「注意」挑会影响判断的说；残留文件、文件名不一致这类整理项合成一句。「正常」一句带过。
4. hermes 定时任务：脚本只按关键字（error、failed、paused 等）判档，原始输出附在报告里。读原文，逐条说明哪些任务暂停或失败了、下次什么时候跑。看不懂的列就说看不懂，不要猜。
5. 「说明与盲区」里点名的、没配输出日志的定时任务，告诉常浩「这几个看不出有没有按时跑」。
6. 最后问：要处理哪几条？**不要自己动手。**

## 三、判档规则

每个任务可能有好几条问题，按最重的一条归档。同一档里，常驻服务挂了排最前，其次是上次运行失败、该跑没跑、没加载、僵尸任务，最后是整理类问题。

| 档 | 情况 |
|---|---|
| 需要处理 | plist 读不出来（格式坏了） |
| | 僵尸任务：plist 指向的程序或脚本已经不存在 |
| | 程序没有执行权限；工作目录不存在；日志所在的文件夹不存在（launchd 会启动失败） |
| | 常驻、定时或监视类任务：plist 在、没停用，但 launchd 里没有它（根本不会运行） |
| | 常驻服务没在运行，或异常退出后正在等待重启 |
| | 常驻服务在跑，但本次登录以来启动了 ≥ 20 次（反复崩溃） |
| | 定时任务上次退出码不是 0（被 SIGTERM 中途停止的除外） |
| | 该跑没跑：日志最后更新以来，按计划漏了 ≥ 3 次，并且日志停更 ≥ 24 小时 |
| | 两个 plist 用同一个 Label |
| | crontab 里某条指向的家目录文件不存在 |
| 注意 | 常驻服务在跑，但之前异常退出过（启动 ≥ 5 次，或上次退出码不是 0） |
| | 该跑没跑：漏了至少 1 次，但没到「需要处理」的程度 |
| | 配了输出日志但日志文件从没生成 |
| | 最近 24 小时的日志末尾有报错字样（退出码那一项已经报过的不重复报） |
| | 日志文件 ≥ 200 MB |
| | 已停用但 plist 还在；只在登录或手动触发时运行的任务没加载 |
| | 定时任务上次被 SIGTERM 中途停止 |
| | 内联命令（`bash -c "…"`）里提到的家目录路径不存在 |
| | 文件名像备份却仍以 `.plist` 结尾；文件名和 Label 不一致 |
| | LaunchAgents 里有不以 `.plist` 结尾的残留文件（`.bak`、`.disabled` 等） |
| | `hermes cron list` 运行失败，或输出里有失败、暂停、停用字样 |
| 正常 | 以上都没有。没配输出日志的定时任务（包括只配了错误日志的）也算正常，但在「说明与盲区」里点名 |

「该跑没跑」怎么算：
- 每隔 N 秒（StartInterval）：日志最后修改时间到「现在减 15 分钟」之间，能放下几个 N，就是漏了几次。
- 按日历（StartCalendarInterval）：数日志最后修改之后、「现在减 15 分钟」之前，按计划应运行的时间点有几个。周日写 0 或 7 都认。
- 常驻服务不按时间判断，看它在不在跑、重启了几次。

退出码会翻译成人话，例如 1 是「一般性错误，看日志」，75 是「临时失败，常见于网络断开」，78 是「配置错误，launchd 启动不了程序」，126 是「没有执行权限」，127 是「找不到命令，launchd 的 PATH 比终端里短」，137 是「被强制结束」，143 是「被要求退出」。

## 四、只读边界

- 脚本只执行四种查看命令：`launchctl print`、`launchctl print-disabled`、`hermes cron list`、`crontab -l`。其他命令在代码层直接拒绝，测试覆盖。
- 脚本唯一会写的是报告文件（默认 `~/Documents/自动化体检/`，`--json` 时另加一份 JSON）。日志末尾里的 token、secret、password、Bearer 等会被替换成「[已隐藏]」。
- 体检过程中，agent 也不执行任何加载、卸载、重启、结束进程、改文件、挪文件的操作。
- 处置是另一件事：常浩点名某一条后，读 [references/actions.md](references/actions.md)，一次一条，说清楚要做什么、影响什么、怎么回退，得到同意再做；做完重新体检对照。

## 五、配置

[config.json](config.json) 放在 skill 目录里，改完下次体检生效：

| 键 | 作用 |
|---|---|
| `exclude_patterns` | 跳过哪些任务（系统和第三方厂商），支持 `*` 通配。跳过的会列在报告末尾，不会悄悄消失 |
| `include_labels` | 被上面排除、但其实是自建的任务，写完整 Label 强制纳入 |
| `quiet_labels` | 平时就不写日志的定时任务，跳过「该跑没跑」判断 |
| `aliases` | Label 到中文名的对照，支持 `*`；报告标题用它 |
| `tail_lines` | 日志末尾显示几行（默认 15） |
| `grace_minutes` | 判断该跑没跑时，给刚到点的任务留的余量（默认 15 分钟） |
| `missed_runs_act`、`stale_hours_act` | 漏几次且停更几小时算「需要处理」（默认 3 次、24 小时） |
| `restart_runs_warn`、`restart_runs_act` | 常驻服务启动几次算「注意」「需要处理」（默认 5、20） |
| `log_size_warn_mb` | 日志多大算「注意」（默认 200） |
| `recent_error_hours` | 多久以内的日志报错算数（默认 24 小时） |

`--config 路径` 可以再叠一份临时配置。

## 六、局限

- 「该跑没跑」靠输出日志（StandardOutPath）的修改时间推断，错误日志不参与（任务正常时通常不写它）：任务平时不写日志、或电脑那段时间关机，都会判得偏严。前者加进 `quiet_labels`。
- 只看用户级的 `~/Library/LaunchAgents`，不看需要管理员权限的 `/Library/LaunchDaemons`。
- `launchctl print` 里的启动次数是本次登录以来的累计，重启电脑后清零。
- `hermes cron list` 的输出格式没在本机核实过，所以只做关键字判断，正文交给 agent 解读。

## 七、测试

```bash
cd ~/.claude/skills/automation-checkup
python3 -m unittest discover -s tests -v
python3 tests/scenario.py examples/sample-report.md   # 用合成数据重新生成示例报告
```

测试全部用合成 plist、伪造的 `launchctl` / `hermes` / `crontab` 输出和日志，Linux 上也能跑。示例报告见 [examples/sample-report.md](examples/sample-report.md)。
