# 处置手册（体检之后，用户点名要处理某一条时才读）

体检本身只读。这里的每个动作都会改变本机状态，只在常浩明确说「处理第 N 条」之后做。

## 规矩

1. **一次一条**。动手前用一两句话告诉常浩：要做什么、会影响哪个自动化（比如「重启期间飞书消息会断几秒」）、做坏了怎么回退。他说可以再做。
2. **不删，只挪**。要下线的 plist、残留文件，挪到 `~/Library/LaunchAgents.retired/<今天日期>/`；改 plist 之前也先复制一份过去。回退就是挪回来。
3. **先查后做**。改 plist 后先 `plutil -lint <文件>`，通过了再让 launchd 重新加载。
4. **做完复查**。每处理完一条，用 `launchctl print gui/$(id -u)/<Label>` 看状态；全部处理完重新跑一次体检，对照前后报告告诉常浩结果。
5. 动手前，如果能读到 agent-kit 里的 LESSONS，先看里面跟 launchd、Hermes 有关的条目；那里记的是踩过的坑，优先于本手册。

## 已知的坑

- **`launchctl bootout` 是异步的**：命令返回时，服务可能还没卸干净。紧接着 `bootstrap` 会报 `Bootstrap failed: 5: Input/output error` 或「Operation already in progress」。做法：`bootout` 之后，每秒查一次 `launchctl print gui/$(id -u)/<Label>`，直到它返回「找不到」（最多等 15 秒），再 `bootstrap`。
- **launchd 的 PATH 很短**（`/usr/bin:/bin:/usr/sbin:/sbin`），所以「终端里能跑、定时就报 127」很常见。修法是在 plist 的 `EnvironmentVariables` 里写 `PATH`（加上 `/opt/homebrew/bin`、`~/.local/bin` 等，写绝对路径），或者脚本里用命令的绝对路径。
- **路径里的 `~`**：plist 里尽量写绝对路径，不要依赖 `~` 展开。
- **日志文件夹不存在**时，launchd 常常直接启动失败（退出码 78）。先建文件夹。
- **停用（disable）会被记住**：`launchctl disable` 的状态存在系统里，plist 删了再放回来也还是停用。要重新用，先 `launchctl enable`。

下面的 `<Label>` 是任务的 Label，`<plist>` 是 `~/Library/LaunchAgents/<文件名>.plist` 的完整路径，`U=$(id -u)`。

## 常见处理

### 看完整日志、找原因
```bash
tail -n 200 <日志路径>
```
只把能说明原因的几行讲给常浩，不整段贴。

### 重启常驻服务（Hermes 网关、频道桥、牛马之家等）
先确认原因已经清楚或已修好，否则重启后还会挂。
```bash
launchctl kickstart -k gui/$U/<Label>
sleep 5; launchctl print gui/$U/<Label> | grep -E '^\s*(state|pid|runs|last exit code) ='
```

### 手动触发一次定时任务（验证修好了没有）
```bash
launchctl kickstart gui/$U/<Label>
```
等它跑完，看日志有没有更新、`last exit code` 是不是 0。

### 让「文件在、但没加载」的任务重新生效
```bash
plutil -lint <plist>
launchctl bootstrap gui/$U <plist>
```
报「already loaded」或 I/O 错误时，按上面「bootout 是异步的」先卸再装。

### 改了 plist 之后让它生效
```bash
mkdir -p ~/Library/LaunchAgents.retired/$(date +%Y%m%d) && cp <plist> ~/Library/LaunchAgents.retired/$(date +%Y%m%d)/
# 改 plist ……
plutil -lint <plist>
launchctl bootout gui/$U/<Label>
# 等到 launchctl print 查不到，再：
launchctl bootstrap gui/$U <plist>
```

### 下线僵尸任务、不要的任务
```bash
D=~/Library/LaunchAgents.retired/$(date +%Y%m%d); mkdir -p "$D"
launchctl bootout gui/$U/<Label>      # 没加载的会报错，可以忽略
# 等到 launchctl print 查不到，再：
mv <plist> "$D"/
```

### 重新启用已停用的任务
```bash
launchctl enable gui/$U/<Label>
launchctl bootstrap gui/$U <plist>
```

### 清理残留文件（.bak、.disabled、同 Label 的备份 .plist）
```bash
D=~/Library/LaunchAgents.retired/$(date +%Y%m%d); mkdir -p "$D"
mv ~/Library/LaunchAgents/<残留文件名> "$D"/
```
同 Label 的两个 `.plist`：先用 `launchctl print gui/$U/<Label>` 里的 `path =` 确认 launchd 实际加载的是哪个，挪走另一个。

### plist 格式坏了
```bash
plutil -lint <plist>
```
按报错修；修不好又不用了，就挪走。

### 日志太大
先问常浩里面有没有要留的内容；要留就先复制一份，再清空：
```bash
cp <日志> "<日志>.$(date +%Y%m%d)"   # 需要留时
: > <日志>
```

### crontab 某条失效
```bash
crontab -l > ~/crontab.backup.$(date +%Y%m%d)
# 用编辑后的文件替换：先把备份复制一份、删掉那一行，再
crontab <编辑后的文件>
```

### hermes 定时任务暂停或失败
先 `hermes cron --help` 看有哪些子命令，按帮助操作，不要猜参数。暂停的先问常浩是不是故意的。
