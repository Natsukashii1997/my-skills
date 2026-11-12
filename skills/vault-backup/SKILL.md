---
name: vault-backup
description: 「知识库备份」：给常浩的 Obsidian 知识库和只在本机的 Git 项目做加密、增量、可异地的备份（restic），并能检查完整性、演练恢复。用户说「备份一下」「检查备份」「演练恢复」「备份状态」「设置备份」「定时备份」，或问知识库有没有备份、坏了怎么找回时使用。只备份和演练，不覆盖原文件；密码只放钥匙串或环境变量。
metadata:
  version: "0.2.0"
  governance:
    network: optional
    external-writes: required
    destructive-actions: guarded
    credentials: required
    dependencies:
      - python3
      - restic
      - git
---

# 知识库备份

目标：知识库和本地项目坏了、丢了、电脑没了，都能从别处完整取回；而且平时就证明过「真能取回」，不是只看到「备份成功」。

做法：restic 把选定目录加密、去重后存到一个或多个「备份位置」（外置盘、iCloud 云盘、S3/B2 云存储）。每次只存变化的部分，旧版本都留着。为什么选 restic、备选方案是什么，见 [references/approach.md](references/approach.md)。

## 用户说什么，做什么

| 用户说 | 运行 | 看什么 |
|---|---|---|
| 备份一下 | `backup` | 每个位置每个目录一行 ✓ / ✗；最后「结果」一行 |
| 备份一下，顺便提交 git | `backup --git-commit` | 有未提交改动的目录会多一条「已提交一次快照」 |
| 检查备份 | `check` | 完整性校验是否通过；每个目录最近一次备份时间、版本数、大小；备份库占用 |
| 演练恢复 | `restore-drill`（默认用第一个位置；别的位置加 `--target 名字`） | 「对不上 N 项」必须是 0；结论行 |
| 备份怎么样了 / 备份状态 | `status`（不需要密码，几秒出结果） | 末尾「要处理的事」 |
| 设置备份 | 按下面「第一次设置」走 | |
| 定时备份 | 见 [references/schedule.md](references/schedule.md) | |
| 知识库坏了 / 要找回某个旧文件 | 见 [references/restore.md](references/restore.md) | |
| 备份太大了 | `prune`（只预演），用户确认后 `prune --apply` | |

```bash
VB=~/.claude/skills/vault-backup/scripts/vault_backup.py   # Codex 用 ~/.agents/skills/vault-backup/scripts/vault_backup.py
python3 "$VB" status
python3 "$VB" backup
python3 "$VB" check            # 加 --full 读取全部数据校验（慢；云端会产生下载流量）
python3 "$VB" restore-drill    # 可加 --target 名字、--source 文件夹名、--keep
```

配置文件在 `~/.config/vault-backup/config.txt`（模板 [assets/config.example.txt](assets/config.example.txt)）。运行记录在 `~/.local/state/vault-backup/state.json`，只记时间和结果。

把结果转述给用户时：先说结论（成功 / 有问题），再说要他做什么；不要整段贴输出。

## 第一次设置（每一步等用户确认再做）

1. **装 restic**：`brew install restic`。这是在用户电脑上装软件，先问；Codex 按 `~/.codex/contracts/skill-admission.md` 审查。
2. **让用户定备份存哪**：把 [references/targets.md](references/targets.md) 的对比讲给他听，由他选。本 skill 默认不选任何付费存储。建议至少「一个本地 + 一个异地」。
3. **写配置**：`mkdir -p ~/.config/vault-backup && cp <本 skill>/assets/config.example.txt ~/.config/vault-backup/config.txt`，按用户的选择改 `source` 和 `target` 两类行。改完跑 `status`，确认能读懂配置。
4. **设密码**：请用户**自己**在终端运行下面这行，按提示输入两次密码。不要让用户把密码发到对话里，也不要替他编一个。
   ```bash
   security add-generic-password -s vault-backup -a restic-password -w
   ```
   用 S3/B2 时再存两项：`-a s3-access-key-id -w` 和 `-a s3-secret-access-key -w`（同一个 `-s vault-backup`）。
   **然后提醒他把密码另存一份在电脑以外**（见 targets.md「密码怎么保管」）。这一步不做，电脑丢了备份也打不开。
5. **建库**：`init`。
6. **第一次备份**：`backup`。2 GB 左右首次要几分钟到几十分钟（云端看网速），之后每次只传改动。
7. **第一次演练**：`restore-drill`，每个位置各做一次（`--target 名字`）。演练过的备份才算数。
8. **定时**（可选，用户确认后单独做）：见 schedule.md。脚本不会自己装定时任务。

## 底线

1. **密码不落地**：只放钥匙串或环境变量 `VAULT_BACKUP_PASSWORD`；不写进配置、文件、日志、对话、提交。配置文件里出现 password / secret 一类的行，脚本会拒绝运行。
2. **不覆盖原文件**：演练只恢复到临时目录，比对完就删。真要找回文件，先恢复到新文件夹，用户看过再由他自己挪回去（restore.md）。
3. **不替用户提交 git**：默认只报告未提交数。未提交的改动照样会被备份，不提交不影响安全。用户说「顺便提交」或配置里开了才提交。
4. **会删东西的操作先预演**：`prune` 默认只预演；`--apply` 要用户看过预演结果并同意。
5. **装东西、装定时任务都是单独一步**，用户同意才做。

## 结果怎么读、出问题怎么办

| 看到 | 意思 | 怎么办 |
|---|---|---|
| 没找到备份密码 | 钥匙串里没有这一项 | 第一次设置第 4 步 |
| 密码不对 | 钥匙串里的密码和这个备份库不匹配 | 让用户找出当初另存的密码，用 `security add-generic-password -U -s vault-backup -a restic-password -w` 改回来。密码找不回，这个备份库就打不开了：只能新建一个库重新备份 |
| 外置盘「X」没有连接 | 盘没插 | 插上再跑；不影响其他位置 |
| 有些文件没读到 | 多半是 macOS 隐私权限没给 | 手动运行时：看 系统设置 → 隐私与安全性 → 文件和文件夹 里，运行它的程序有没有「文稿」权限，没有就在弹窗时点允许。定时任务见 schedule.md：先只开「文稿」，不行再在用户同意后考虑完全磁盘访问权限（范围很大，要先讲清代价） |
| 备份库被别的进程锁住了 | 另一次备份正在跑，或上次被强行中断 | 等几分钟再跑；确认没有别的备份在跑时，`restic -r <位置> unlock` |
| 恢复演练「对不上 N 项」不为 0 | 有文件备份之后没动过，恢复出来却不一样 | 先 `check --full`；把 ✗ 行原样给用户看，别自己下结论说没事 |
| N 天没成功备份 | 定时没跑，或一直失败 | `status` 看最近一次尝试的结果 |

## 测试

```bash
python3 -m unittest discover -s skills/vault-backup/tests -v
```

只在临时目录里造数据（中文和空格路径、符号链接、40 MB 大文件、git 仓库），覆盖：备份 → 改动 → 再备份 → 旧版本可取回 → 恢复比对 → 密码错误时全部失败 → 备份库损坏能查出 → 外置盘没插时跳过 → 密码不出现在任何输出和记录里。没装 restic 时端到端部分自动跳过并写明原因。
