# 处置手册（体检之后，常浩点名要处理某一条时才读）

体检本身只读。这里的每个动作都会改变本机状态，只在常浩明确说「处理第 N 条」之后做。

## 规矩

1. **一次一条**。动手前用一两句话告诉常浩：要做什么、会影响哪个自动化（比如「重启期间飞书消息会断几秒」）、做坏了怎么回退。他说可以再做。例外：只挪文件的整理项（残留文件、多余的同名配置文件、确认不要的任务），可以列成清单一次确认。
2. **先判断会不会对外发东西**。下面几种操作都等于让任务真跑一次：
   - 手动触发（`kickstart`）
   - 重新加载（`bootstrap`）：配置里带 RunAtLoad 的，加载后会立刻跑一次
   - 重启常驻服务

   发飞书消息、发营销短信、写多维表格、推周报，都会真的再来一遍。动手前先看脚本和最近的日志，判断它会对外做什么，告诉常浩「这样会再给 X 发一次 Y」，他同意再做。判断不了就照实说，改成「等下次按计划运行再看」。
3. **不删，只挪**。
   - 要下线的配置文件、残留文件，挪到 `~/Library/LaunchAgents.retired/<今天日期>/`；改配置文件之前，也先复制一份过去。
   - 每挪一次，在同目录的 `说明.txt` 末尾追加一行：时间、挪了什么、为什么、怎么挪回。`~/Library` 在访达里默认看不见，这份说明是常浩以后找回的线索。
   - 回退就是挪回来，再重新加载。
4. **先查后做**。改配置文件后先 `plutil -lint <文件>`，通过了再让 launchd 重新加载。
5. **做完复查**。
   - 每处理完一条，用 `launchctl print gui/$(id -u)/<Label>` 看状态。
   - 全部处理完，重新跑一次体检。新报告开头会写「比上次：已恢复 N 个」，拿它告诉常浩结果。
6. **原因在项目代码或依赖里的，这里不修**。缺模块、脚本报错、命令没装、凭据过期都属于这类。
   - 告诉常浩是哪个项目（路径）、日志哪一行说明了原因、建议怎么修。
   - 修改按那个项目自己的流程走，有仓库的按 agent-kit《工程流程》：issue → 分支 → PR。
   - 修好后回到这里重启，或等下次按计划运行验证。
7. **先读踩坑记录**。动手前，到 `/Users/nat/Documents/ChatGPT/个人/work/agent-kit/` 里找 LESSONS（例如 `LESSONS.md` 或 `docs/LESSONS.md`），先看跟 launchd、Hermes 有关的条目；那里记的是踩过的坑，优先于本手册。读不到就跳过，并告诉常浩。

## 已知的坑

- **`launchctl bootout` 是异步的**：命令返回时，服务可能还没卸干净。要等它卸完再 `bootstrap`：

  ```bash
  for i in $(seq 15); do launchctl print gui/$(id -u)/<Label> >/dev/null 2>&1 || break; sleep 1; done
  ```

- **常见报错码**：
  - `Boot-out failed: 36: Operation now in progress`：还在卸，等上面的循环跑完。
  - `Bootstrap failed: 37: Operation already in progress`：已经加载了，不用再加载。
- **`Bootstrap failed: 5: Input/output error` 原因很多**，按顺序查，都是只读命令：
  1. `launchctl print-disabled gui/$(id -u) | grep <Label>`：停用了吗？停用了要先 `enable`。
  2. `ls -l <plist>`：属主是不是本人、是不是只有本人能写？应为 `-rw-r--r--` 且属主是自己。
  3. `plutil -lint <plist>`：格式对不对？
  4. `log show --last 2m --predicate 'subsystem == "com.apple.xpc.launchd"' | grep <Label>`：launchd 自己写的原因。
  5. 以上都没问题，再按「bootout 是异步的」先卸再装。
- **launchd 不展开 `~`**：配置文件里的程序、脚本参数、工作目录、日志路径都要写完整路径，比如 `/Users/nat/...`。只有 `bash -c "…"` 内联命令里的 `~` 会被 shell 展开。
- **launchd 只在系统目录里找程序**：只写了程序名（比如 `node`）时，launchd 只在 `/usr/bin:/bin:/usr/sbin:/sbin` 里找，不看配置里自己设的 PATH。所以「终端里能跑、定时就报 127」很常见。有两种修法：
  - 程序写完整路径，比如 `/opt/homebrew/bin/node`。
  - 脚本内部要用的命令：在配置的 `EnvironmentVariables` 里写 `PATH`，加上 `/opt/homebrew/bin`、`/Users/nat/.local/bin` 等。
- **隐私权限（退出码 126 或 78，日志写 Operation not permitted）**：脚本或项目在「文稿」「桌面」「下载」或 iCloud 云盘里时，launchd 拉起的进程会被 macOS 拦住；终端里能跑，是因为终端自己有授权。有两种修法，都要常浩自己操作或拍板：
  - 把项目挪到不受保护的位置，比如 `~/Projects`。这是项目层面的改动，按规矩 6 处理。
  - 在「系统设置 → 隐私与安全性 → 完全磁盘访问权限」里，给对应的解释器（例如 `/bin/bash`、python）授权。这会放宽所有用它跑的程序，先说明风险。
- **日志文件夹不存在**时，launchd 常常直接启动失败（退出码 78）。先建文件夹。
- **停用（disable）会被记住**：`launchctl disable` 的状态存在系统里，配置文件挪走再放回来也还是停用。要重新用，先 `launchctl enable`。
- **退出过多会被关进「penalty box」**：反复崩溃的常驻服务会被 launchd 暂缓重启。原因修好后，要 `bootout` 再 `bootstrap` 才会恢复。

下面的 `<Label>` 是任务名，`<plist>` 是 `~/Library/LaunchAgents/<文件名>.plist` 的完整路径。每条命令都写成 `gui/$(id -u)`，不要依赖上一条命令里设的变量。

## 常见处理

### 看完整日志、找原因
```bash
tail -n 200 <日志路径>
```
只把能说明原因的几行讲给常浩，不整段贴。日志里有密钥的，转述时隐去。

### 重启常驻服务（Hermes 网关、频道桥、牛马之家等）
先确认原因已经清楚或已修好，否则重启后还会挂；按规矩 2 说清重启的影响。
```bash
launchctl kickstart -k gui/$(id -u)/<Label>
sleep 5; launchctl print gui/$(id -u)/<Label> | grep -E '^\s*(state|pid|runs|last exit code) ='
```
回退：无（重启不改配置）。还是起不来，就看日志找原因。

### 手动触发一次定时任务（验证修好了没有）
先按规矩 2 判断副作用。会对外发消息的任务，默认不手动触发，改为等下次按计划运行。
```bash
launchctl kickstart gui/$(id -u)/<Label>
```
等它跑完，看日志有没有更新、`last exit code` 是不是 0。

### 让「文件在、但没加载」的任务重新生效
带 RunAtLoad 的，加载后会立刻跑一次，先按规矩 2 说清楚。
```bash
plutil -lint <plist>
launchctl bootstrap gui/$(id -u) <plist>
```
报错时，按上面「常见报错码」和 error 5 的检查顺序处理。
回退：`launchctl bootout gui/$(id -u)/<Label>`。

### 改了配置文件之后让它生效
适用于：把 `~` 改成完整路径、给 Program 写完整路径、加 PATH、改工作目录或日志路径。
```bash
D=~/Library/LaunchAgents.retired/$(date +%Y%m%d); mkdir -p "$D"
cp <plist> "$D"/ && echo "$(date '+%F %T') 复制 <plist>：改之前的备份，回退时复制回去" >> "$D/说明.txt"
# 改 plist（用 plutil -replace 或编辑器）……
plutil -lint <plist>
launchctl bootout gui/$(id -u)/<Label>
for i in $(seq 15); do launchctl print gui/$(id -u)/<Label> >/dev/null 2>&1 || break; sleep 1; done
launchctl bootstrap gui/$(id -u) <plist>
```
回退：把 `$D` 里的备份复制回原位置，再 bootout、等待、bootstrap。

### 下线僵尸任务、不要的任务
```bash
D=~/Library/LaunchAgents.retired/$(date +%Y%m%d); mkdir -p "$D"
launchctl bootout gui/$(id -u)/<Label>      # 没加载的会报错，可以忽略
for i in $(seq 15); do launchctl print gui/$(id -u)/<Label> >/dev/null 2>&1 || break; sleep 1; done
mv <plist> "$D"/ && echo "$(date '+%F %T') 挪走 <plist>：<原因>；挪回 ~/Library/LaunchAgents/ 再 bootstrap 即可恢复" >> "$D/说明.txt"
```

### 重新启用已停用的任务
```bash
launchctl enable gui/$(id -u)/<Label>
launchctl bootstrap gui/$(id -u) <plist>
```
回退：`launchctl bootout gui/$(id -u)/<Label>` 后 `launchctl disable gui/$(id -u)/<Label>`。

### 清理残留文件、多余的同名配置文件、断掉的软链接
先列清单给常浩一次确认。同名配置文件：以体检报告里写的「系统正在用的」为准（来自 `launchctl print` 的 `path =`），挪走另外的。
```bash
D=~/Library/LaunchAgents.retired/$(date +%Y%m%d); mkdir -p "$D"
mv ~/Library/LaunchAgents/<文件名> "$D"/ && echo "$(date '+%F %T') 挪走 <文件名>：<原因>" >> "$D/说明.txt"
```
断掉的软链接，如果常浩说任务还要、知道配置文件的新位置：`ln -sfn <新位置> ~/Library/LaunchAgents/<文件名>`，再 bootstrap。

### 程序没有执行权限
```bash
ls -l <程序>
chmod u+x <程序>
```
回退：`chmod u-x <程序>`。

### 工作目录或日志文件夹不存在
先确认项目是不是挪走了；挪走了就按「改了配置文件之后让它生效」改路径。只是日志文件夹没建：
```bash
mkdir -p <日志文件夹>
```

### 配置文件权限或属主不对
```bash
ls -l <plist>
chmod 644 <plist>
```
属主不是本人时（通常是用 sudo 拷过来的），改属主需要管理员密码，交给常浩自己在终端执行 `sudo chown $(whoami) <plist>`；agent 不代输密码。

### 配置文件坏了
```bash
plutil -lint <plist>
```
按报错修（先备份，见「改了配置文件之后让它生效」）；修不好又不用了，就挪走。

### 日志太大
默认留一份压缩备份再清空，不丢内容：
```bash
D=~/Library/LaunchAgents.retired/$(date +%Y%m%d); mkdir -p "$D"
cp <日志> "$D/" && gzip "$D/$(basename <日志>)" && : > <日志>
echo "$(date '+%F %T') 清空 <日志>，原内容在 $(basename <日志>).gz；回退：gunzip -c 这个文件 > <日志>" >> "$D/说明.txt"
```

### crontab 某条失效
```bash
D=~/Library/LaunchAgents.retired/$(date +%Y%m%d); mkdir -p "$D"
crontab -l > "$D/crontab.before"
grep -vxF '<要去掉的那一整行>' "$D/crontab.before" > "$D/crontab.after"
diff "$D/crontab.before" "$D/crontab.after"   # 应该只少这一行，给常浩看
crontab "$D/crontab.after"
```
回退：`crontab "$D/crontab.before"`。

### hermes 定时任务失败、暂停、过点没跑
- **过点没跑**：多半是 hermes 网关没在运行。先处理报告里「飞书网关 Hermes」那一项。
- **失败**：看报告里的失败原因。凭据过期、对方服务不通这类，要到对应项目或 hermes 配置里修（规矩 6）。
- **暂停**：先问常浩是不是故意的。

要用 hermes 自己的命令时（比如恢复暂停的任务），先告诉常浩：运行任何 hermes 命令都会触发它的启动维护，会写日志，可能迁移配置、拉起被暂停的网关。他同意后，先 `hermes cron --help` 看子命令，按帮助操作，不要猜参数。
