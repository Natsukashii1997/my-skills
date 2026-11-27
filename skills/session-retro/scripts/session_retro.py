#!/usr/bin/env python3
"""session-retro：只读扫描本机 Claude Code / Codex 会话记录，用规则抽出复盘信号。

- 只用 Python 标准库，不联网、不调用任何外部服务或模型。
- 只读会话文件，不修改、不复制原始记录；输出只含截断后的片段，并统一脱敏。
- 三个子命令：scan（抽信号）、context（看某条出处的上下文）、match（拿提案草稿对照现有规则）。
兼容 macOS 自带的 Python 3.9。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time as clock
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    sys.exit("需要 Python 3.9 或更新版本")

SCHEMA_VERSION = 1
MAX_LINE_BYTES = 8 * 1024 * 1024
TEXT_LIMIT = 300
CONTEXT_LIMIT = 160
HOME = str(Path.home())

# ---------------------------------------------------------------- 脱敏

_R = "[已脱敏]"
REDACTIONS = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)", re.S), "[已脱敏:私钥]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"), "[已脱敏:密钥]"),
    (re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_\-]{16,}"), "[已脱敏:密钥]"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), "[已脱敏:GitHub令牌]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[已脱敏:GitHub令牌]"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"), "[已脱敏:令牌]"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"), "[已脱敏:Slack令牌]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[已脱敏:AWS密钥]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[已脱敏:Google密钥]"),
    (re.compile(r"\bgk_(?:live|test)_[A-Za-z0-9._\-]{6,}"), "[已脱敏:密钥]"),
    (re.compile(r"\b(?:t|u)-[a-z0-9]{2}[A-Za-z0-9_\-]{30,}"), "[已脱敏:飞书令牌]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{6,}"), "[已脱敏:JWT]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-~+/]{12,}=*"), r"\1 " + _R),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s@/]+@"), r"\1:" + _R + "@"),
    (re.compile(r"(?i)([?&](?:token|access_token|refresh_token|key|api_key|apikey|sig|signature|secret|auth|code|password)=)[^&\s#\"']+"), r"\1" + _R),
    (re.compile(r"(?i)\b((?:[a-z0-9]+[_\-])*(?:api[_\-]?key|apikey|secret|token|password|passwd|pwd|access[_\-]?key|private[_\-]?key|client[_\-]?secret|app[_\-]?secret|auth)[\"']?\s*[:=]\s*[\"']?)([^\s\"',;&}]{6,})"), r"\1" + _R),
    (re.compile(r"((?:密码|口令|密钥|令牌|秘钥|验证码)\s*(?:是|为|:|：|=)\s*)\S{4,}"), r"\1" + _R),
    (re.compile(r"\b[\w.+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}\b"), "[已脱敏:邮箱]"),
    (re.compile(r"(?<![\d])(?:\+?86[\- ]?)?1[3-9]\d{9}(?![\d])"), "[已脱敏:手机号]"),
]
_OPAQUE = re.compile(r"(?<![A-Za-z0-9_\-+])[A-Za-z0-9_\-+]{40,}={0,2}")


def _opaque(match):
    token = match.group(0)
    if re.search(r"[a-z]", token) and re.search(r"[A-Z]", token) and re.search(r"\d", token):
        return "[已脱敏:疑似密钥]"
    return token


def redact(value):
    """递归脱敏：字符串里的密钥、令牌、口令、邮箱、手机号。"""
    if isinstance(value, str):
        for pattern, replacement in REDACTIONS:
            value = pattern.sub(replacement, value)
        return _OPAQUE.sub(_opaque, value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        # 出处路径是脚本自己生成的，不脱敏（会话文件名里的长 ID 会被误判成密钥）
        return {key: (item if key in PATH_KEYS else redact(item)) for key, item in value.items()}
    return value


PATH_KEYS = ("file", "rules_files_read")


# ---------------------------------------------------------------- 信号规则

CORRECTION_STRONG = [
    r"不对", r"错了", r"搞错", r"弄错", r"理解错", r"看错", r"重来", r"重新来", r"重做",
    r"我说的是", r"我的意思是", r"不是让你", r"没让你", r"谁让你", r"不是我要的",
    r"不是这个意思", r"别再", r"又错", r"又忘", r"又漏", r"还是不对", r"还是不行", r"还是错",
    r"撤回", r"回滚", r"改回", r"你漏了", r"漏掉了", r"答非所问", r"跑偏", r"擅自",
    r"说了多少次", r"跟你说过", r"我说过", r"前面说过", r"不要自作主张", r"为什么又",
    r"(?i)\bthat'?s (?:wrong|not (?:what|right|it))", r"(?i)\bnot what I (?:asked|wanted|meant)",
    r"(?i)\bI (?:said|told you|meant)\b", r"(?i)\byou (?:missed|forgot|ignored)\b",
    r"(?i)\brevert\b", r"(?i)\bstart over\b",
]
# 弱词只在两种情况下算：出现在句首；或整句很短（≤25 字）且命中「短句也算」那一组。单字「别」「停」只认句首，避免「特别」「不错」误报。
CORRECTION_WEAK = [
    r"不是", r"别", r"不要", r"不用", r"停", r"等等", r"等一下",
    r"(?i)no\b", r"(?i)nope\b", r"(?i)stop\b", r"(?i)don'?t\b", r"(?i)wait\b", r"(?i)actually\b", r"(?i)wrong\b",
]
CORRECTION_WEAK_SHORT = [r"不是这", r"不是那", r"不要这", r"不用了", r"别这样", r"别动", r"(?i)\bdon'?t\b", r"(?i)\bwrong\b"]
DECISION_STRONG = [
    r"定了", r"就按", r"就这么", r"以后都", r"以后一律", r"以后不要", r"以后别", r"以后(?:统一|默认|都用|就用)",
    r"今后", r"一律", r"统一用", r"统一改", r"默认用", r"我决定", r"决定了", r"拍板", r"按这个来",
    r"记住", r"记下来", r"永远不要", r"每次都要", r"(?i)from now on", r"(?i)going forward",
    r"(?i)let'?s go with", r"(?i)\bI(?:'ve)? decided\b",
]
DECISION_WEAK = [r"(?i)\balways\b", r"(?i)\bnever\b", r"就用", r"选\s*[A-Da-d1-4](?![A-Za-z0-9])", r"方案\s*[A-Da-d1-4一二三](?![A-Za-z0-9])"]

_C_STRONG = [re.compile(p) for p in CORRECTION_STRONG]
_C_WEAK = [re.compile(p) for p in CORRECTION_WEAK]
_D_STRONG = [re.compile(p) for p in DECISION_STRONG]
_D_WEAK = [re.compile(p) for p in DECISION_WEAK]
_C_WEAK_SHORT = [re.compile(p) for p in CORRECTION_WEAK_SHORT]
_D_WEAK_SHORT = _D_WEAK
_LEAD_JUNK = re.compile(r"^[\s，。,.!！?？:：;；、\-—~…\"'“”‘’（）()\[\]【】>]+")
WEAK_SHORT_LIMIT = 25

SYSTEM_PREFIXES = (
    "<command-name>", "<command-message>", "<command-args>", "<local-command-stdout>", "<local-command-stderr>",
    "<local-command-caveat>", "<system-reminder>", "<environment_context>", "<user_instructions>",
    "<user_shell_command>", "<task-notification>", "<bash-stdout>", "<bash-stderr>", "<turn_aborted>",
    "caveat: the messages below", "# agents.md instructions", "this session is being continued from a previous conversation",
)
INTERRUPT_RE = re.compile(r"^\[Request interrupted by user")
CLAUDE_REJECT_RE = re.compile(r"(?i)doesn'?t want to (?:proceed|take this action)|tool use was rejected|user rejected|permission (?:was )?denied by (?:the )?user")
CLAUDE_REASON_RE = re.compile(r"(?is)the user said:\s*(.+)$")
CODEX_REJECT_RE = re.compile(r"(?i)rejected by (?:the )?user|denied by (?:the )?user|user (?:rejected|denied|declined)|aborted by (?:the )?user|not approved by (?:the )?user")
STRIP_FOR_MATCH = [
    re.compile(r"```.*?(?:```|$)", re.S),
    re.compile(r"<pasted_content[^>]*>.*?(?:</pasted_content[^>]*>|$)", re.S),
    re.compile(r"<system-reminder>.*?(?:</system-reminder>|$)", re.S),
    re.compile(r"[「“\"‘][^」”\"’\n]{1,20}[」”\"’]"),  # 引号里的短词多是在引用，不是在纠正
]
LONG_MESSAGE = 800
# 「重复」信号：短话 ≤ SHORT_LIMIT 字、出现 ≥ SHORT_MIN 次列出；长消息按空行切段，段落归一化后 ≥ PARA_MIN 字、
# 在 ≥ PASTE_MIN 条消息里出现的列出
SHORT_LIMIT = 20
SHORT_MIN = 5
PARA_MIN = 20
PASTE_MIN = 3
CHANNEL_NAMES = {"input": "输入框", "agent-hud": "驿窗侧栏", "codex": "Codex"}


def _search(patterns, text):
    hits = []
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            hits.append(found.group(0).strip())
    return hits


def classify_user_text(text):
    """返回 (tags, strength, keywords)。tags 里可有「纠正」「决定」。规则偏召回，最终由 agent 判断。"""
    body = text
    for pattern in STRIP_FOR_MATCH:
        body = pattern.sub(" ", body)
    body = body.strip()
    head = _LEAD_JUNK.sub("", body)
    short = len(head) <= WEAK_SHORT_LIMIT
    tags, keywords, strong = [], [], False

    def weak_hits(lead_patterns, short_patterns):
        found = []
        for pattern in lead_patterns:
            lead = pattern.match(head)
            if lead:
                found.append(lead.group(0).strip())
        if short and not found:
            found = _search(short_patterns, head)
        return found

    for tag, strong_patterns, weak_patterns, short_patterns in (
            ("纠正", _C_STRONG, _C_WEAK, _C_WEAK_SHORT), ("决定", _D_STRONG, _D_WEAK, _D_WEAK_SHORT)):
        hits = _search(strong_patterns, body)
        if hits:
            strong = True
        else:
            hits = weak_hits(weak_patterns, short_patterns)
        if hits:
            tags.append(tag)
            keywords.extend(hits)
    strength = "强" if strong else ("弱" if tags else None)
    return tags, strength, list(dict.fromkeys(keywords))


# ---------------------------------------------------------------- 通用工具

def parse_ts(value):
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    text = re.sub(r"\.(\d{1,5})(?=[+-]|$)", lambda m: "." + m.group(1).ljust(6, "0"), text)
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def short_path(path):
    text = str(path)
    return "~" + text[len(HOME):] if HOME and text.startswith(HOME + os.sep) else text


def clip(text, limit=TEXT_LIMIT, focus=None):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    if focus:
        index = text.find(focus)
        if index > limit - 40:
            head = text[: limit // 2].rstrip()
            start = max(index - limit // 4, len(head))
            return head + " …… " + text[start:start + limit // 2].strip() + " ……"
    return text[:limit].rstrip() + " ……"


def norm_text(text):
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def flatten_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text") and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                parts.append(flatten_content(block.get("content")))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "output", "content", "message"):
            if isinstance(content.get(key), str):
                return content[key]
    return ""


def is_system_text(text):
    head = (text or "").lstrip().lower()
    return not head or head.startswith(SYSTEM_PREFIXES)


# 新版 Codex（2026-11 本机实测）不再写 event_msg/user_message，用户的话只能从 role=user 的消息里取，
# 而这类消息里混着大量注入：应用状态、心跳、技能正文、别的 agent 的历史、计划模式的「开始实施」等。
# 整条以这些开头的都不算用户的话。依据见 references/session-formats.md。
CODEX_INJECTED_PREFIXES = (
    "<external_codex_apps", "<in-app-browser-context", "<heartbeat", "<skill", "<recommended_plugins",
    "<codex_delegation",
    "the following is the codex agent history", "you are working inside orca", "please implement this plan:",
)
CODEX_HISTORY_LINE = re.compile(r"^\[\d+\]\s+(?:assistant|user|tool|system)\b")
# IDE / 引用对话附带的上下文：前面是文件清单或对话摘录，用户的话在「## My request:」之后
CODEX_CONTEXT_HEADS = ("# files mentioned by the user", "# files pasted by the user", "# context from my ide",
                       "## referenced chatgpt conversation")
CODEX_REQUEST_HEAD = re.compile(r"(?m)^##\s*My request(?: for Codex)?:[ \t]*$")
# 用户回答 agent 提问时，原话包在这个标签里
CODEX_WRAPPED_REPLY = re.compile(
    r"(?s)^<send_user_message_question_reply\b[^>]*>(.*)</send_user_message_question_reply>\s*$")


def codex_user_text(text):
    """从 Codex 的 user 消息里取出用户真正说的话；整条都是注入的返回空串。"""
    t = (text or "").strip()
    wrapped = CODEX_WRAPPED_REPLY.match(t)
    if wrapped:
        t = wrapped.group(1).strip()
    head = t.lower()
    if head.startswith(CODEX_CONTEXT_HEADS):
        parts = CODEX_REQUEST_HEAD.split(t, maxsplit=1)
        return parts[1].strip() if len(parts) == 2 else ""
    if head.startswith(CODEX_INJECTED_PREFIXES) or CODEX_HISTORY_LINE.match(t) or is_system_text(t):
        return ""
    return t


def _command_key(command):
    if isinstance(command, list):
        parts = [str(part) for part in command]
        if len(parts) >= 3 and parts[0].endswith(("bash", "sh", "zsh")) and parts[1] in ("-lc", "-c"):
            command = parts[2]
        else:
            command = " ".join(parts)
    command = str(command or "").strip()
    segments = [seg.strip() for seg in re.split(r"&&|;|\|\|", command) if seg.strip()]
    segments = [seg for seg in segments if not re.match(r"^(?:cd|export|source|set)\b", seg)] or segments
    tokens = []
    for token in (segments[0] if segments else "").split():
        if re.match(r"^[A-Z_][A-Z0-9_]*=", token) or token in ("sudo", "time", "env"):
            continue
        if token.startswith("-"):
            continue
        tokens.append(token.strip("'\""))
        if len(tokens) == 3:
            break
    return " ".join(tokens)[:80]


def tool_key(name, args):
    name = str(name or "tool")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, TypeError):
            args = {"input": args}
    if not isinstance(args, dict):
        args = {}
    command = args.get("command") or args.get("cmd")
    if command:
        return "%s: %s" % (name, _command_key(command))
    for field in ("file_path", "path", "notebook_path"):
        if isinstance(args.get(field), str):
            return "%s: %s" % (name, os.path.basename(args[field].rstrip("/")))
    patch = args.get("input")
    if isinstance(patch, str):
        found = re.search(r"\*\*\* (?:Update|Add|Delete) File: (\S+)", patch)
        if found:
            return "%s: %s" % (name, os.path.basename(found.group(1)))
    return name


def iter_jsonl(path, coverage, skip_hint=None):
    with open(path, "rb") as stream:
        for number, raw in enumerate(stream, 1):
            if len(raw) > MAX_LINE_BYTES:
                coverage["oversized_lines_skipped"] += 1
                continue
            if skip_hint and skip_hint(raw):
                continue
            try:
                record = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                if raw.strip():
                    coverage["malformed_lines"] += 1
                continue
            if isinstance(record, dict):
                yield number, record


class Event(object):
    __slots__ = ("kind", "ts", "line", "text", "tool", "key", "ok", "call_id", "uid", "reason", "fallback", "channel", "labels")

    def __init__(self, kind, ts, line, text="", tool=None, key=None, ok=None, call_id=None, uid=None, reason=None, fallback=False,
                 channel=None, labels=None):
        self.kind, self.ts, self.line, self.text = kind, ts, line, text
        self.tool, self.key, self.ok, self.call_id = tool, key, ok, call_id
        self.uid, self.reason, self.fallback = uid, reason, fallback
        self.channel, self.labels = channel, labels  # channel：用户的话从哪来；labels：wrap_up 给的按钮文字


# ---------------------------------------------------------------- 谁说的话（依据见 references/session-formats.md「用户原话的来源」）

# 桌面应用会把提醒（关联会话状态、钩子注入等）作为文字块拼在真人消息前后
SYSTEM_REMINDER_BLOCK = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
AGENT_HUD_WRAPPER = re.compile(r"(?s)^The agent-hud plugin sent a message:\n(.*?)\n\nThis is how Claude Code surfaces")
# 驿窗侧栏这一路里不是常浩打的：ChatGPT 回送（审核意见、思维评审回信）、接力出错通知、别的 agent 经驿窗发来的消息
AGENT_HUD_RELAYS = re.compile(r"(?s)^(?:ChatGPT 对「.*?」的|驿窗接力「.*?」出错|\[Agent HUD · 来自 )")


def claude_channel(record):
    """这条 user 记录是不是常浩亲手发的：返回 "input"（桌面输入框）、"agent-hud"（驿窗侧栏）或 None（不是）。

    新版记录用 origin 标来源；没有 origin 的看 turnOrigin（host_synthetic 是应用代发的 side-session 任务和事件，
    sdk 是 claude -p 派单）。两个字段都没有的是旧版记录，按真人处理。
    """
    if record.get("entrypoint") == "sdk-cli":
        return None
    origin = record.get("origin")
    if isinstance(origin, dict):
        kind = origin.get("kind")
        if kind == "human":
            return "input"
        if kind == "plugin" and origin.get("name") == "agent-hud":
            return "agent-hud"
        return None
    if origin is not None:
        return None
    return "input" if record.get("turnOrigin") in (None, "human") else None


def agent_hud_text(record, text):
    prompt = record.get("pluginPrompt")
    if isinstance(prompt, dict) and isinstance(prompt.get("text"), str):
        return prompt["text"].strip()
    wrapped = AGENT_HUD_WRAPPER.match(text)
    return wrapped.group(1).strip() if wrapped else ""


def wrap_up_labels(block):
    """wrap_up 的按钮文字，按给出顺序（第一个是 AI 的推荐）。"""
    data = block.get("input") if isinstance(block.get("input"), dict) else {}
    actions = data.get("actions") if isinstance(data.get("actions"), list) else []
    return [a["label"].strip() for a in actions if isinstance(a, dict) and isinstance(a.get("label"), str) and a["label"].strip()]


# ---------------------------------------------------------------- Claude Code

def parse_claude(path, coverage):
    """~/.claude/projects/<编码后的目录>/<会话>.jsonl。字段依据见 references/session-formats.md。"""
    session = {"source": "claude", "path": str(path), "session_id": path.stem, "cwd": None, "events": []}
    events = session["events"]
    calls = {}
    for number, record in iter_jsonl(path, coverage):
        kind = record.get("type")
        if kind not in ("user", "assistant"):
            continue
        if record.get("isSidechain"):
            coverage["sidechain_records_skipped"] += 1
            continue
        if isinstance(record.get("sessionId"), str):
            session["session_id"] = record["sessionId"]
        if isinstance(record.get("cwd"), str) and not session["cwd"]:
            session["cwd"] = record["cwd"]
        stamp = parse_ts(record.get("timestamp"))
        if stamp is None:
            coverage["records_without_timestamp"] += 1
            continue
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content")
        uid = record.get("uuid") if isinstance(record.get("uuid"), str) else None
        if kind == "assistant":
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    events.append(Event("assistant", stamp, number, block["text"]))
                elif block.get("type") == "tool_use":
                    key = tool_key(block.get("name"), block.get("input"))
                    calls[block.get("id")] = (block.get("name"), key)
                    labels = wrap_up_labels(block) if str(block.get("name", "")).endswith("__wrap_up") else None
                    events.append(Event("tool_call", stamp, number, tool=block.get("name"), key=key, call_id=block.get("id"), labels=labels))
            continue
        # user 记录：真人输入，或工具结果
        texts = []
        blocks = content if isinstance(content, list) else ([content] if isinstance(content, str) else [])
        decision = record.get("permissionDecision")
        denied_by_permission = isinstance(decision, dict) and str(decision.get("decision", "")).lower() in ("reject", "rejected", "deny", "denied", "block", "blocked")
        for block in blocks:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text") or "")
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                output = flatten_content(block.get("content"))
                name, key = calls.get(block.get("tool_use_id"), (None, None))
                result_meta = record.get("toolUseResult")
                # 只认报错结果开头的拒绝文案，避免把「grep 到 rejected 字样」的普通输出当成被拒
                rejected = bool(block.get("is_error") and CLAUDE_REJECT_RE.search(output[:300])) or denied_by_permission or (
                    isinstance(result_meta, str) and "reject" in result_meta.lower())
                if rejected:
                    reason_match = CLAUDE_REASON_RE.search(output)
                    events.append(Event("rejection", stamp, number, output, tool=name, key=key, call_id=block.get("tool_use_id"),
                                        uid=block.get("tool_use_id"), reason=reason_match.group(1).strip() if reason_match else None))
                elif INTERRUPT_RE.match(output.strip()):
                    events.append(Event("interrupt", stamp, number, output, tool=name, key=key, uid=block.get("tool_use_id")))
                else:
                    events.append(Event("tool_result", stamp, number, output, tool=name, key=key,
                                        ok=not bool(block.get("is_error")), call_id=block.get("tool_use_id"), uid=block.get("tool_use_id")))
        text = "\n".join(t for t in texts if t).strip()
        if not text:
            continue
        if record.get("isMeta") or record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly"):
            continue
        channel = claude_channel(record)
        if channel == "agent-hud":
            text = agent_hud_text(record, text)
            if not text or AGENT_HUD_RELAYS.match(text):
                coverage["agent_hud_relays_skipped"] += 1
                continue
        else:
            # 先剥掉注入的提醒再判断：首块是提醒的真人消息以前整条被当成系统文字丢掉
            text = SYSTEM_REMINDER_BLOCK.sub("", text).strip()
            if not text:
                continue
        if channel is None:
            if not is_system_text(text) and not INTERRUPT_RE.match(text):
                coverage["non_human_messages_skipped"] += 1
            continue
        if INTERRUPT_RE.match(text):
            events.append(Event("interrupt", stamp, number, text, uid=uid))
        elif not is_system_text(text):
            events.append(Event("user", stamp, number, text, uid=uid, channel=channel))
    return session


# ---------------------------------------------------------------- Codex

CODEX_ITEM_TYPES = {"message", "function_call", "function_call_output", "custom_tool_call",
                    "custom_tool_call_output", "local_shell_call", "reasoning"}


def _codex_skip(raw):
    head = raw[:200]
    return b'"token_count"' in head or b'"type":"reasoning"' in head


def _codex_output(output):
    """返回 (文本, 退出码或 None, success 或 None)。兼容 JSON 包装和纯文本两种写法。"""
    success = None
    if isinstance(output, str):
        stripped = output.strip()
        if stripped.startswith("{"):
            try:
                output = json.loads(stripped)
            except ValueError:
                pass
    if isinstance(output, dict):
        success = output.get("success") if isinstance(output.get("success"), bool) else None
        meta = output.get("metadata") if isinstance(output.get("metadata"), dict) else {}
        code = meta.get("exit_code", output.get("exit_code"))
        text = flatten_content(output.get("output") if "output" in output else output.get("content"))
        return text, code if isinstance(code, int) else None, success
    text = output if isinstance(output, str) else flatten_content(output)
    # 新版 Codex 的 exec 工具（2026-11 本机实测占工具输出的大多数）：首行是脚本本身的结果。
    # 先看它，不让 Output 里内层命令的退出码盖过脚本级结论。
    first = (text or "").lstrip().split("\n", 1)[0]
    if first.startswith("Script failed"):
        return text, None, False
    if first.startswith("Script completed"):
        return text, None, True
    found = re.search(r"(?m)^(?:Exit code:\s*|Process exited with code\s+)(-?\d+)", text or "")
    return text or "", int(found.group(1)) if found else None, success


def parse_codex(path, coverage):
    """~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl。字段依据见 references/session-formats.md。"""
    session = {"source": "codex", "path": str(path), "session_id": path.stem, "cwd": None, "events": [], "subagent": False}
    events = session["events"]
    calls, pending, exit_codes = {}, {}, {}
    meta_ts = None
    has_event_user = False
    for number, record in iter_jsonl(path, coverage, _codex_skip):
        kind = record.get("type")
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else None
        if kind == "session_meta" and payload is not None:
            session["session_id"] = payload.get("id") or session["session_id"]
            session["cwd"] = payload.get("cwd") or session["cwd"]
            meta_ts = parse_ts(payload.get("timestamp")) or parse_ts(record.get("timestamp"))
            source = payload.get("source")
            if (isinstance(source, dict) and "subagent" in source) or payload.get("agent_path") not in (None, "/root"):
                session["subagent"] = True
                return session
            # codex exec 是脚本或别的 agent 派单，「用户消息」是派单内容；工具调用照常统计
            session["dispatched"] = payload.get("originator") == "codex_exec" or source == "exec"
            continue
        if number == 1 and payload is None and "id" in record and "type" not in record:  # 旧版首行
            session["session_id"] = record.get("id") or session["session_id"]
            meta_ts = parse_ts(record.get("timestamp"))
            continue
        if kind == "turn_context" and payload is not None:
            if isinstance(payload.get("cwd"), str) and not session["cwd"]:
                session["cwd"] = payload["cwd"]
            continue
        stamp = parse_ts(record.get("timestamp")) or meta_ts
        if stamp is None:
            coverage["records_without_timestamp"] += 1
            continue
        if kind == "event_msg" and payload is not None:
            sub = payload.get("type")
            if sub == "user_message":
                has_event_user = True
                text = codex_user_text(payload.get("message") if isinstance(payload.get("message"), str) else "")
                if text:
                    events.append(Event("user", stamp, number, text, channel="codex"))
            elif sub == "turn_aborted":
                events.append(Event("interrupt", stamp, number, "turn_aborted: %s" % payload.get("reason", "")))
            elif sub == "exec_command_end" and isinstance(payload.get("exit_code"), int):
                exit_codes[payload.get("call_id")] = payload["exit_code"]
            continue
        if kind == "response_item" and payload is not None:
            item = payload
        elif payload is None and kind in CODEX_ITEM_TYPES:  # 旧版：条目直接成行
            item = record
        else:
            continue
        item_type = item.get("type")
        if item_type == "message":
            text = flatten_content(item.get("content")).strip()
            if item.get("role") == "assistant" and text:
                events.append(Event("assistant", stamp, number, text))
            elif item.get("role") == "user":
                text = codex_user_text(text)
                if text:
                    events.append(Event("user", stamp, number, text, fallback=True, channel="codex"))
        elif item_type in ("function_call", "custom_tool_call", "local_shell_call"):
            name = item.get("name") or ("shell" if item_type == "local_shell_call" else "tool")
            args = item.get("arguments") if item_type == "function_call" else (
                item.get("input") if item_type == "custom_tool_call" else (item.get("action") or {}))
            key = tool_key(name, args)
            call_id = item.get("call_id") or item.get("id")
            calls[call_id] = (name, key)
            events.append(Event("tool_call", stamp, number, tool=name, key=key, call_id=call_id))
        elif item_type in ("function_call_output", "custom_tool_call_output"):
            call_id = item.get("call_id")
            name, key = calls.get(call_id, (None, None))
            text, code, success = _codex_output(item.get("output"))
            if len(text) < 400 and CODEX_REJECT_RE.search(text):  # 拒绝回执很短；长输出里出现这些字样多半是普通内容
                events.append(Event("rejection", stamp, number, text, tool=name, key=key, call_id=call_id, uid=call_id))
                continue
            if code is not None:
                ok = code == 0
            elif success is not None:
                ok = success
            elif re.search(r"(?i)^\s*(?:error|failed|fatal)\b|verification failed", text or ""):
                ok = False
            else:
                ok = None
            event = Event("tool_result", stamp, number, text, tool=name, key=key, ok=ok, call_id=call_id, uid=call_id)
            events.append(event)
            if ok is None:
                pending[call_id] = event
    for call_id, event in pending.items():
        if call_id in exit_codes:
            event.ok = exit_codes[call_id] == 0
    if has_event_user:
        session["events"] = [e for e in events if not (e.kind == "user" and e.fallback)]
    if session.get("dispatched"):
        dropped = sum(1 for e in session["events"] if e.kind == "user")
        coverage["dispatch_messages_skipped"] += dropped
        session["events"] = [e for e in session["events"] if e.kind != "user"]
    return session


# ---------------------------------------------------------------- 文件发现

ROLLOUT_DATE = re.compile(r"rollout-(\d{4})-(\d{2})-(\d{2})T")


def discover(args, start, end, coverage):
    """按修改时间和文件名日期剪枝：最后修改早于窗口起点的文件不可能有窗口内事件。"""
    start_epoch = start.timestamp()
    found = []
    if args.source in ("all", "claude"):
        for root in args.claude_root:
            root = Path(root).expanduser()
            if not root.is_dir():
                coverage["roots_missing"].append(short_path(root))
                continue
            for project in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
                for path in sorted(project.glob("*.jsonl")):  # 只取一层，子代理目录不进入
                    found.append(("claude", path))
    if args.source in ("all", "codex"):
        for root in args.codex_root:
            root = Path(root).expanduser()
            if not root.is_dir():
                coverage["roots_missing"].append(short_path(root))
                continue
            for folder, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(names):
                    if name.startswith("rollout-") and name.endswith(".jsonl"):
                        found.append(("codex", Path(folder) / name))
    kept = []
    latest_start_date = (end + timedelta(days=1)).date()
    for source, path in found:
        coverage["files_found"] += 1
        try:
            if path.is_symlink():
                coverage["symlinks_skipped"] += 1
                continue
            if path.stat().st_mtime < start_epoch:
                coverage["files_skipped_older_than_window"] += 1
                continue
        except OSError:
            coverage["files_unreadable"] += 1
            continue
        named = ROLLOUT_DATE.search(path.name)
        if named:
            try:
                if date(int(named.group(1)), int(named.group(2)), int(named.group(3))) > latest_start_date:
                    coverage["files_skipped_started_after_window"] += 1
                    continue
            except ValueError:
                pass
        kept.append((source, path))
    return kept


# ---------------------------------------------------------------- 规则对照

def grams(text):
    lowered = (text or "").lower()
    out = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    for word in re.findall(r"[a-z0-9_]{3,}", lowered):
        if word not in ("the", "and", "you", "for", "this", "that", "with", "not", "are"):
            out.add(word)
    return out


def load_rule_units(paths, coverage=None, max_files=3000, max_bytes=30 * 1024 * 1024):
    units, used, total = [], [], 0
    files = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*.md") if not any(part.startswith(".") for part in p.parts[len(path.parts):])))
        elif path.is_file():
            files.append(path)
    for path in files[:max_files]:
        try:
            size = path.stat().st_size
            if total + size > max_bytes:
                break
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += size
        used.append(short_path(path))
        block, block_line = [], None

        def flush():
            if block:
                joined = " ".join(block).strip()
                for piece in re.split(r"(?<=[。；!?！？])", joined) if len(joined) > 300 else [joined]:
                    if len(piece.strip()) >= 6:
                        units.append({"file": short_path(path), "line": block_line, "text": piece.strip(), "grams": grams(piece)})
            del block[:]

        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("```"):
                flush()
                continue
            if re.match(r"^(#{1,6}\s|[-*+]\s|\d+[.)]\s|\|)", stripped):
                flush()
            if not block:
                block_line = number
            block.append(stripped)
        flush()
    if coverage is not None:
        coverage["rules_files_read"] = used
    return units


def build_index(units):
    index = defaultdict(list)
    for number, unit in enumerate(units):
        for gram in unit["grams"]:
            index[gram].append(number)
    return index


def match_rules(text, units, index, top=3, threshold=0.35):
    query = grams(text)
    if len(query) < 4:
        return []
    hits = Counter()
    for gram in query:
        for number in index.get(gram, ()):
            hits[number] += 1
    results = []
    for number, count in hits.most_common(top * 4):
        score = count / float(len(query))
        if score >= threshold:
            unit = units[number]
            results.append({"file": unit["file"], "line": unit["line"], "score": round(score, 2),
                            "level": "很可能已有" if score >= 0.6 else "可能相关", "text": clip(unit["text"], 120)})
    results.sort(key=lambda item: -item["score"])
    return results[:top]


def default_rule_paths(cwds):
    paths = [Path.home() / ".claude" / "CLAUDE.md", Path.home() / ".codex" / "AGENTS.md",
             Path.home() / "Documents" / "ChatGPT" / "个人" / "work" / "agent-kit" / "LESSONS.md"]
    for cwd in sorted(c for c in cwds if c):
        base = Path(cwd)
        paths += [base / "CLAUDE.md", base / "AGENTS.md", base / "docs" / "LESSONS.md"]
    return paths


# ---------------------------------------------------------------- 扫描主体

class Scanner(object):
    def __init__(self, args, start, end, zone):
        self.args, self.start, self.end, self.zone = args, start, end, zone
        self.coverage = Counter()
        self.coverage["roots_missing"] = []
        self.user_signals, self.rejections, self.failures = [], [], []
        self.seen_text_time, self.repeat_index = set(), {}
        self.seen_tool_ids = set()
        self.seen_user_uids = set()
        self.short_index, self.paste_index = {}, {}
        self.short_total = Counter()
        self.projects = Counter()
        self.cwds = set()
        projects = [p.lower() for p in (args.project or [])]
        self.project_filter = projects
        self.exclude = set(s.lower() for s in (args.exclude_session or []))

    def local(self, stamp):
        return stamp.astimezone(self.zone).strftime("%Y-%m-%d %H:%M")

    def cite(self, session, event):
        return {"file": short_path(session["path"]), "line": event.line, "time": self.local(event.ts)}

    def in_window(self, stamp):
        return self.start <= stamp < self.end

    def wanted(self, session):
        if str(session["session_id"]).lower() in self.exclude:
            self.coverage["sessions_excluded"] += 1
            return False
        if self.project_filter:
            haystack = ((session["cwd"] or "") + " " + Path(session["path"]).parent.name).lower()
            if not any(p in haystack for p in self.project_filter):
                self.coverage["sessions_filtered_by_project"] += 1
                return False
        return True

    def run(self):
        files = discover(self.args, self.start, self.end, self.coverage)
        started = clock.monotonic()
        for number, (source, path) in enumerate(files, 1):
            if number % 200 == 0:
                sys.stderr.write("已扫描 %d/%d 个文件，用时 %.0f 秒\n" % (number, len(files), clock.monotonic() - started))
            try:
                session = parse_claude(path, self.coverage) if source == "claude" else parse_codex(path, self.coverage)
            except OSError:
                self.coverage["files_unreadable"] += 1
                continue
            self.coverage["files_scanned"] += 1
            if session.get("subagent"):
                self.coverage["subagent_sessions_skipped"] += 1
                continue
            if not self.wanted(session):
                continue
            if not any(self.in_window(e.ts) for e in session["events"]):
                continue
            self.coverage["sessions_in_window_" + source] += 1
            self.projects[session["cwd"] or "(未知目录)"] += 1
            self.cwds.add(session["cwd"])
            self.analyze(session)
        return self.report()

    def analyze(self, session):
        last_assistant, last_user, after_break = "", "", False
        buttons = []
        key_of_call = {}
        streaks = defaultdict(list)
        project = session["cwd"] or "(未知目录)"
        for event in session["events"]:
            inside = self.in_window(event.ts)
            if event.kind == "assistant":
                last_assistant = event.text
                continue
            if event.kind == "tool_call":
                key_of_call[event.call_id] = event.key
                if event.labels is not None:
                    buttons = event.labels
                continue
            if event.kind in ("rejection", "interrupt"):
                after_break = True
                if inside:
                    self.add_rejection(session, event, last_user, project)
                continue
            if event.kind == "tool_result":
                if not inside or event.ok is None:
                    continue
                if event.uid and (session["source"], event.uid) in self.seen_tool_ids:
                    continue
                if event.uid:
                    self.seen_tool_ids.add((session["source"], event.uid))
                key = event.key or key_of_call.get(event.call_id) or (event.tool or "tool")
                if event.ok:
                    self.close_streak(session, project, key, streaks.pop(key, []), resolved=True)
                else:
                    streaks[key].append(event)
                continue
            if event.kind == "user":
                # 分叉、续接的会话会把旧记录连同 uuid 复制进新文件，跨文件只算一次
                duplicate = bool(event.uid) and (session["source"], event.uid) in self.seen_user_uids
                if event.uid:
                    self.seen_user_uids.add((session["source"], event.uid))
                if duplicate:
                    if inside:
                        self.coverage["duplicate_messages_removed"] += 1
                elif inside:
                    self.add_user(session, event, last_assistant, after_break, project)
                    self.add_repeat(session, event, buttons, project)
                last_user, after_break, buttons = event.text, False, []
        for key, failed in streaks.items():
            self.close_streak(session, project, key, failed, resolved=False)

    def add_user(self, session, event, last_assistant, after_break, project):
        tags, strength, keywords = classify_user_text(event.text)
        if not tags:
            return
        normalized = norm_text(event.text)
        stamp_key = (normalized, event.ts.replace(microsecond=0))
        if stamp_key in self.seen_text_time:
            self.coverage["duplicate_messages_removed"] += 1
            return
        self.seen_text_time.add(stamp_key)
        citation = self.cite(session, event)
        if len(normalized) >= 12 and normalized in self.repeat_index:
            first = self.repeat_index[normalized]
            first["repeats"].append(citation)
            self.coverage["repeated_messages_merged"] += 1
            return
        signal = {
            "tags": tags, "strength": strength, "keywords": keywords,
            "text": clip(event.text, focus=keywords[0] if keywords else None),
            "source": session["source"], "channel": event.channel, "project": project, "session": session["session_id"],
            "citation": citation, "prev_assistant": clip(last_assistant, CONTEXT_LIMIT),
            "after_interrupt": after_break, "long_message": len(event.text) > LONG_MESSAGE, "repeats": [],
        }
        if len(normalized) >= 12:
            self.repeat_index[normalized] = signal
        self.user_signals.append(signal)

    def add_repeat(self, session, event, buttons, project):
        """第五类信号「重复」的原料：亲手短话按归一化文本聚类，长消息按段落聚类。"""
        text = event.text.strip()
        key = norm_text(text)
        if not key:
            return
        citation = self.cite(session, event)
        if len(text) <= SHORT_LIMIT:
            hit_button = any(norm_text(label) == key for label in buttons)
            hit_first = bool(buttons) and norm_text(buttons[0]) == key
            self.short_total["messages"] += 1
            self.short_total["equal_button"] += hit_button
            self.short_total["equal_recommended"] += hit_first
            item = self.short_index.setdefault(key, {
                "texts": Counter(), "count": 0, "equal_button": 0, "equal_recommended": 0,
                "channels": Counter(), "sessions": set(), "projects": Counter(), "citations": []})
            item["texts"][text] += 1
            item["count"] += 1
            item["equal_button"] += hit_button
            item["equal_recommended"] += hit_first
            item["channels"][CHANNEL_NAMES.get(event.channel, event.channel or session["source"])] += 1
            item["sessions"].add(session["session_id"])
            item["projects"][_project_name(project)] += 1
            if len(item["citations"]) < 5:
                item["citations"].append(citation)
            return
        seen = set()
        for para in re.split(r"\n\s*\n", text):
            pkey = norm_text(para)
            if len(pkey) < PARA_MIN or pkey in seen:
                continue
            seen.add(pkey)
            item = self.paste_index.setdefault(pkey, {"text": clip(para.strip(), 200), "count": 0, "sessions": set(), "citations": []})
            item["count"] += 1
            item["sessions"].add(session["session_id"])
            if len(item["citations"]) < 5:
                item["citations"].append(citation)

    def repeats(self):
        shorts = []
        for item in self.short_index.values():
            if item["count"] < self.args.short_min:
                continue
            shorts.append({
                "text": item["texts"].most_common(1)[0][0], "variants": [t for t, _ in item["texts"].most_common(5)],
                "count": item["count"], "equal_button": item["equal_button"], "equal_recommended": item["equal_recommended"],
                "channels": dict(item["channels"].most_common()), "sessions": len(item["sessions"]),
                "projects": dict(item["projects"].most_common(5)),
                "project_names": sorted(item["projects"]),  # 完整名单，check 判「按项目拆分」时用
                "citations": item["citations"]})
        shorts.sort(key=lambda x: (-x["count"], x["text"]))
        pastes = [{"text": item["text"], "count": item["count"], "sessions": len(item["sessions"]), "citations": item["citations"]}
                  for item in self.paste_index.values() if item["count"] >= PASTE_MIN]
        pastes.sort(key=lambda x: (-x["count"], x["text"]))
        for prefix, items in (("S", shorts), ("L", pastes)):
            for number, item in enumerate(items, 1):
                item["id"] = "%s%d" % (prefix, number)
        return {"short_limit": SHORT_LIMIT, "short_min": self.args.short_min, "paste_min": PASTE_MIN,
                "short_messages_total": self.short_total["messages"],
                "short_equal_button_total": self.short_total["equal_button"],
                "short_equal_recommended_total": self.short_total["equal_recommended"],
                "short_messages": shorts, "long_paragraphs": pastes}

    def add_rejection(self, session, event, last_user, project):
        uid = (session["source"], event.uid) if event.uid else (session["source"], event.kind, event.ts, event.key)
        if uid in self.seen_tool_ids:
            self.coverage["duplicate_rejections_removed"] += 1
            return
        self.seen_tool_ids.add(uid)
        self.rejections.append({
            "kind": "拒绝" if event.kind == "rejection" else "中断",
            "tool": event.key or event.tool or "", "reason": clip(event.reason or "", 200),
            "source": session["source"], "project": project, "session": session["session_id"],
            "citation": self.cite(session, event), "prev_user": clip(last_user, CONTEXT_LIMIT),
        })

    def close_streak(self, session, project, key, failed, resolved):
        if len(failed) < self.args.min_streak:
            return
        first, last = failed[0], failed[-1]
        error = next((line.strip() for line in (last.text or "").splitlines()
                      if re.search(r"(?i)error|fail|denied|not found|exception|traceback|错误|失败", line)), "")
        self.failures.append({
            "key": key, "count": len(failed), "resolved": resolved,
            "error": clip(error or last.text, 200), "source": session["source"], "project": project,
            "session": session["session_id"], "first": self.cite(session, first), "last": self.cite(session, last),
        })

    def report(self):
        coverage = self.coverage
        rule_paths = list(self.args.rules or [])
        if not self.args.no_default_rules:
            rule_paths = [str(p) for p in default_rule_paths(self.cwds)] + rule_paths
        units = load_rule_units(rule_paths, coverage)
        index = build_index(units)
        for signal in self.user_signals:
            signal["rule_matches"] = match_rules(signal["text"], units, index)
        for item in self.rejections:
            item["rule_matches"] = match_rules(item["reason"], units, index) if item["reason"] else []

        users = self.user_signals
        # 超上限时优先保留强信号和被重复说过的话，之后再按时间排回去
        users.sort(key=lambda s: (0 if s["strength"] == "强" else 1, -len(s["repeats"]), s["citation"]["time"]))
        cap = self.args.max_items
        truncated = {}
        for name, items in (("user_messages", users), ("rejections", self.rejections), ("repeated_failures", self.failures)):
            if len(items) > cap:
                truncated[name] = len(items) - cap
                del items[cap:]
        users.sort(key=lambda s: s["citation"]["time"])
        self.rejections.sort(key=lambda s: s["citation"]["time"])
        self.failures.sort(key=lambda s: s["first"]["time"])
        for prefix, items in (("U", users), ("R", self.rejections), ("F", self.failures)):
            for number, item in enumerate(items, 1):
                item["id"] = "%s%d" % (prefix, number)
        problems = [k for k in ("malformed_lines", "oversized_lines_skipped", "files_unreadable", "records_without_timestamp") if coverage.get(k)]
        result = {
            "schema_version": SCHEMA_VERSION,
            "tool": "session-retro",
            "generated_at": datetime.now(self.zone).isoformat(timespec="seconds"),
            "window": {"timezone": self.zone.key, "start": self.start.astimezone(self.zone).isoformat(),
                       "end_exclusive": self.end.astimezone(self.zone).isoformat()},
            "filters": {"source": self.args.source, "projects": self.args.project or [],
                        "exclude_sessions": self.args.exclude_session or [], "min_streak": self.args.min_streak},
            "coverage": dict((k, v) for k, v in coverage.items()),
            "coverage_status": "partial" if (problems or truncated) else "complete_for_found_files",
            "projects": dict(self.projects.most_common()),
            "truncated": truncated,
            "signals": {"user_messages": users, "rejections": self.rejections, "repeated_failures": self.failures,
                        "repeats": self.repeats()},
        }
        return redact(result)


# ---------------------------------------------------------------- 输出

def _cite_text(citation):
    return "%s:%s（%s）" % (citation["file"], citation["line"], citation["time"])


def _project_name(path):
    return os.path.basename(str(path).rstrip("/")) or str(path)


def render_markdown(result):
    lines = []
    window = result["window"]
    signals = result["signals"]
    cov = result["coverage"]
    lines.append("# 会话复盘信号（规则初筛，未经判断）")
    lines.append("")
    lines.append("- 时间窗口：%s 至 %s（不含），时区 %s" % (window["start"][:16].replace("T", " "), window["end_exclusive"][:16].replace("T", " "), window["timezone"]))
    lines.append("- 覆盖：找到 %d 个会话文件，按时间跳过 %d 个，实际解析 %d 个；窗口内有活动的会话 Claude %d 个、Codex %d 个；状态 %s" % (
        cov.get("files_found", 0), cov.get("files_skipped_older_than_window", 0) + cov.get("files_skipped_started_after_window", 0),
        cov.get("files_scanned", 0), cov.get("sessions_in_window_claude", 0), cov.get("sessions_in_window_codex", 0), result["coverage_status"]))
    gaps = ["%s %s" % (k, v) for k, v in sorted(cov.items()) if k in (
        "malformed_lines", "oversized_lines_skipped", "files_unreadable", "records_without_timestamp", "subagent_sessions_skipped",
        "sidechain_records_skipped", "duplicate_messages_removed", "repeated_messages_merged", "duplicate_rejections_removed",
        "non_human_messages_skipped", "agent_hud_relays_skipped", "dispatch_messages_skipped") and v]
    if cov.get("roots_missing"):
        gaps.append("目录不存在：" + "、".join(cov["roots_missing"]))
    if gaps:
        lines.append("- 跳过与去重：" + "；".join(gaps))
    lines.append("- 已对照的规则文件：" + ("、".join(cov.get("rules_files_read", [])) or "无（没找到）"))
    if result["truncated"]:
        lines.append("- 注意：条目超出上限被截断 %s，可缩小窗口或按项目分批" % result["truncated"])
    if result["projects"]:
        lines.append("- 项目：" + "；".join("%s %d 个会话" % (_project_name(k), v) for k, v in list(result["projects"].items())[:15]))
    lines.append("")
    lines.append("## 一、用户原话：纠正 / 决定（%d 条）" % len(signals["user_messages"]))
    lines.append("")
    lines.append("强 = 命中明确词（如「不对」「以后都」）；弱 = 只在句首或短句里命中「不是」「别」等，误报多。")
    lines.append("")
    for item in signals["user_messages"]:
        flags = "/".join(item["tags"]) + "·" + item["strength"]
        extra = []
        if item["repeats"]:
            extra.append("同样的话又说了 %d 次：%s" % (len(item["repeats"]), "；".join(_cite_text(c) for c in item["repeats"][:5])))
        if item["after_interrupt"]:
            extra.append("紧跟在拒绝/中断之后")
        if item.get("long_message"):
            extra.append("长消息（可能是粘贴的材料或任务说明），命中词可能来自引用，需看上下文")
        lines.append("- **%s** [%s] %s · %s · 命中：%s" % (item["id"], flags, item["source"], _project_name(item["project"]), "、".join(item["keywords"])))
        lines.append("  - 原话：「%s」" % item["text"])
        if item["prev_assistant"]:
            lines.append("  - AI 上一句：%s" % item["prev_assistant"])
        lines.append("  - 出处：%s" % _cite_text(item["citation"]))
        for note in extra:
            lines.append("  - %s" % note)
        for match in item.get("rule_matches", []):
            lines.append("  - 现有规则%s（%.2f）：%s:%s「%s」" % (match["level"], match["score"], match["file"], match["line"], match["text"]))
    lines.append("")
    lines.append("## 二、被拒绝或被打断的工具调用（%d 条）" % len(signals["rejections"]))
    lines.append("")
    for item in signals["rejections"]:
        lines.append("- **%s** [%s] %s · %s · %s" % (item["id"], item["kind"], item["source"], _project_name(item["project"]), item["tool"] or "（整轮中断）"))
        if item["reason"]:
            lines.append("  - 用户给的理由：「%s」" % item["reason"])
        if item["prev_user"]:
            lines.append("  - 此前用户的要求：%s" % item["prev_user"])
        lines.append("  - 出处：%s" % _cite_text(item["citation"]))
    lines.append("")
    lines.append("## 三、同一操作连续失败（%d 组）" % len(signals["repeated_failures"]))
    lines.append("")
    for item in signals["repeated_failures"]:
        lines.append("- **%s** %s · %s · `%s` 连续失败 %d 次，%s" % (
            item["id"], item["source"], _project_name(item["project"]), item["key"], item["count"], "之后成功" if item["resolved"] else "窗口内未见成功"))
        lines.append("  - 末次报错：%s" % item["error"])
        lines.append("  - 出处：%s 至 %s" % (_cite_text(item["first"]), _cite_text(item["last"])))
    lines.append("")
    rep = signals.get("repeats") or {}
    shorts, pastes = rep.get("short_messages", []), rep.get("long_paragraphs", [])
    lines.append("## 四、重复（短话 %d 组，长段 %d 段）" % (len(shorts), len(pastes)))
    lines.append("")
    lines.append("只算用户亲手发的话（输入框、驿窗侧栏、Codex 桌面）。短话 ≤ %d 字，归一化（去空白和标点、不分大小写）后出现 ≥ %d 次的列出。"
                 "「等于按钮」= 和 AI 上一轮 wrap_up 给的按钮文字一致，「等于推荐」= 和第一个按钮（AI 的推荐）一致。" % (rep.get("short_limit", SHORT_LIMIT), rep.get("short_min", SHORT_MIN)))
    lines.append("")
    total = rep.get("short_messages_total", 0)
    if total:
        lines.append("- 窗口内短话共 %d 条，等于按钮 %d 条（%.0f%%），等于推荐 %d 条" % (
            total, rep.get("short_equal_button_total", 0), 100.0 * rep.get("short_equal_button_total", 0) / total,
            rep.get("short_equal_recommended_total", 0)))
    for item in shorts:
        channels = "、".join("%s %d" % (k, v) for k, v in item["channels"].items())
        lines.append("- **%s** 「%s」%d 次（%s），等于按钮 %d、等于推荐 %d，%d 个会话" % (
            item["id"], item["text"], item["count"], channels, item["equal_button"], item["equal_recommended"], item["sessions"]))
        if len(item["variants"]) > 1:
            lines.append("  - 写法：" + "、".join("「%s」" % v for v in item["variants"]))
        lines.append("  - 项目：" + "；".join("%s %d" % (k, v) for k, v in item["projects"].items()))
        lines.append("  - 出处（前 %d 条）：%s" % (len(item["citations"]), "；".join(_cite_text(c) for c in item["citations"])))
    lines.append("")
    lines.append("长消息按空行切段，同一段（归一化后 ≥ %d 字）出现在 ≥ %d 条消息里的列出，多半是在会话之间搬运。" % (PARA_MIN, rep.get("paste_min", PASTE_MIN)))
    lines.append("")
    for item in pastes:
        lines.append("- **%s** %d 条消息、%d 个会话：「%s」" % (item["id"], item["count"], item["sessions"], item["text"]))
        lines.append("  - 出处（前 %d 条）：%s" % (len(item["citations"]), "；".join(_cite_text(c) for c in item["citations"])))
    lines.append("")
    return "\n".join(lines)


def inside_git_repo(path):
    current = Path(path).resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def write_private(path, text):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)


# ---------------------------------------------------------------- 命令行

def resolve_window(args, zone):
    if args.start:
        start_day = date.fromisoformat(args.start)
        end_day = date.fromisoformat(args.end) if args.end else datetime.now(zone).date() + timedelta(days=1)
    else:
        end_day = datetime.now(zone).date() + timedelta(days=1)
        start_day = end_day - timedelta(days=args.days)
    start = datetime.combine(start_day, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(end_day, time.min, zone).astimezone(timezone.utc)
    if start >= end:
        raise ValueError("结束日期必须晚于开始日期")
    return start, end, start_day, end_day


def add_rule_args(parser):
    parser.add_argument("--rules", action="append", help="额外对照的规则文件或目录（目录读其中 .md），可重复；例如 Obsidian Vault 的决定目录")
    parser.add_argument("--no-default-rules", action="store_true", help="不读默认规则文件（~/.claude/CLAUDE.md、~/.codex/AGENTS.md、agent-kit/LESSONS.md、各项目 CLAUDE.md/AGENTS.md/docs/LESSONS.md）")


RESERVE_MARK = ".session-retro-scanning"


def reserve_out_dir(base):
    """从 base、base-2、base-3……里选第一个没有上次结果、也没被别的扫描占着的目录，独占创建占位文件。"""
    number = 1
    while True:
        out = base if number == 1 else base.with_name("%s-%d" % (base.name, number))
        number += 1
        if (out / "signals.json").exists():
            continue
        out.mkdir(parents=True, exist_ok=True)
        mark = out / RESERVE_MARK
        try:
            with open(str(mark), "x"):
                pass
        except FileExistsError:
            continue
        if (out / "signals.json").exists():  # 别的扫描刚写完、刚交还占位
            mark.unlink()
            continue
        return out, mark


def cmd_scan(args):
    try:
        zone = ZoneInfo(args.timezone)
        start, end, start_day, end_day = resolve_window(args, zone)
        if args.min_streak < 2 or args.max_items < 1 or args.short_min < 1 or (args.days is not None and args.days < 1):
            raise ValueError("--min-streak 至少 2，--max-items、--short-min、--days 至少 1")
    except (ValueError, ZoneInfoNotFoundError) as error:
        sys.stderr.write("参数错误：%s\n" % error)
        return 2
    reserved = None  # 默认目录的占位文件，写完结果再交还
    if args.out:
        out = Path(args.out).expanduser()
    else:
        suffix = ("_" + re.sub(r"[^\w\-]+", "-", "-".join(args.project))) if args.project else ""
        base = Path.home() / "session-retro" / ("%s_%s%s" % (start_day.isoformat(), end_day.isoformat(), suffix))
        # 同一窗口复盘过的目录里有上次的信号和据此写的提案（引用行号），默认不覆盖，另起一个目录；
        # 用独占创建的占位文件预留目录，两个扫描同时跑也不会选中同一个
        out, reserved = reserve_out_dir(base)
        if out != base:
            sys.stderr.write("%s 里已有上次的扫描结果（或别的扫描正在写），这次写到 %s（要覆盖请用 --out 指定）\n" % (short_path(base), short_path(out)))
    repo = inside_git_repo(out.parent if not out.exists() else out)
    if repo and not args.allow_in_repo:
        sys.stderr.write("拒绝写入：%s 在 git 仓库 %s 里，结果可能被误提交。换一个目录，或加 --allow-in-repo。\n" % (out, repo))
        if reserved:
            reserved.unlink()
        return 2
    try:
        result = Scanner(args, start, end, zone).run()
        out.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(str(out), 0o700)
        except OSError:
            pass
        write_private(out / "signals.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        write_private(out / "signals.md", render_markdown(result))
    finally:
        if reserved and reserved.exists():
            reserved.unlink()  # 不管写没写成，都交还占位
    signals = result["signals"]
    sys.stdout.write("已写入 %s\n用户原话 %d 条，拒绝/中断 %d 条，连续失败 %d 组；覆盖状态 %s\n" % (
        short_path(out), len(signals["user_messages"]), len(signals["rejections"]), len(signals["repeated_failures"]), result["coverage_status"]))
    return 3 if result["coverage_status"] == "partial" else 0


def cmd_context(args):
    path = Path(args.file).expanduser()
    coverage = Counter()
    if not path.is_file():
        sys.stderr.write("找不到文件：%s\n" % path)
        return 2
    if path.name.startswith("rollout-"):
        session = parse_codex(path, coverage)
    else:
        session = parse_claude(path, coverage)
    zone = ZoneInfo(args.timezone)
    events = session["events"]
    if not events:
        sys.stdout.write("这个文件里没有可显示的对话。\n")
        return 0
    anchor = next((i for i, e in enumerate(events) if e.line >= args.line), len(events) - 1)
    users = [i for i, e in enumerate(events) if e.kind in ("user", "assistant")]
    before = [i for i in users if i < anchor][-args.before:] if args.before else []
    after = [i for i in users if i > anchor][:args.after] if args.after else []
    lo = min(before + [anchor])
    hi = max(after + [anchor])
    labels = {"user": "用户", "assistant": "AI", "tool_call": "工具调用", "tool_result": "工具结果",
              "rejection": "被拒绝", "interrupt": "被中断"}
    out = []
    for index in range(lo, hi + 1):
        event = events[index]
        mark = " ←" if index == anchor else ""
        if event.kind == "tool_call":
            body = event.key or event.tool or ""
        elif event.kind == "tool_result":
            body = ("成功" if event.ok else "失败" if event.ok is False else "结果未知") + "：" + clip(event.text, 160)
        else:
            body = clip(event.text, args.width)
        out.append("- [%s 行%d %s]%s %s" % (labels.get(event.kind, event.kind), event.line,
                                          event.ts.astimezone(zone).strftime("%m-%d %H:%M"), mark, body))
    header = "# %s 第 %d 行附近（已脱敏）\n\n" % (short_path(path), args.line)
    sys.stdout.write(header + redact("\n".join(out)) + "\n")
    return 0


def cmd_match(args):
    texts = list(args.text or [])
    if args.file:
        content = Path(args.file).expanduser().read_text(encoding="utf-8")
        texts += [line.strip() for line in content.splitlines() if line.strip()]
    if not texts:
        sys.stderr.write("请用 --text 或 --file 给出要对照的提案文字\n")
        return 2
    paths = list(args.rules or [])
    if not args.no_default_rules:
        paths = [str(p) for p in default_rule_paths(set(args.project_dir or []))] + paths
    coverage = {}
    units = load_rule_units(paths, coverage)
    index = build_index(units)
    out = {"rules_files_read": coverage.get("rules_files_read", []), "results": []}
    for text in texts:
        out["results"].append({"text": text, "matches": match_rules(text, units, index, top=args.top, threshold=args.threshold)})
    sys.stdout.write(json.dumps(redact(out), ensure_ascii=False, indent=2) + "\n")
    return 0


SPLIT_PART = re.compile(r"(输入框|驿窗侧栏|Codex)\s*(\d+)")
SPLIT_ITEM = re.compile(r"(输入框|驿窗侧栏|Codex)\s*(\d+)\s*次?")


SPLIT_LIKE = re.compile(r"([^\d\s（）()]+?)\s*(\d+)\s*次?")
STAT_LABELS = ("等于按钮", "等于推荐")  # 统计说明，不是来源；只认这两个确切的词


def parse_split(paren, item=None):
    """括号里的来源拆分 → ({来源: 次数}, 问题)。不是拆分的说明（「（20 次等于推荐）」）返回 (None, None)。

    有三个合法来源名之一的，逐项解析，重复、认不出的都报。一个合法来源都没有时，只有同时满足这几条才当成写错的拆分：
    每一项都是「叫法 + 数字」、数字加起来正好等于这一组的全窗口次数、至少一个叫法既不是这一组出现过的项目名
    （完整名单 project_names）、也不是「等于按钮」「等于推荐」这两个统计说明（「（侧栏 5）」「（ChatGPT 3、网页端 2）」）；
    按项目拆的、和次数对不上的说明都不报。"""
    if not paren:
        return None, None
    parts = [x.strip() for x in re.split(r"[、，,；;]", paren.strip("（）() ")) if x.strip()]
    if not SPLIT_PART.search(paren):
        labels = [SPLIT_LIKE.fullmatch(x) for x in parts]
        if item and parts and all(labels) and sum(int(m.group(2)) for m in labels) == item["count"]:
            names = item.get("project_names")
            if names is None:  # 旧版 signals 只存了前 5 个项目，名单可能不全，不据此判
                names = list(item.get("projects", {}))
                if len(names) >= 5:
                    return None, None
            # 「等于按钮 2、等于推荐 3」是统计说明，不是来源；「等于浏览器」这类照样报
            if any(m.group(1) not in names and m.group(1) not in STAT_LABELS for m in labels):
                return None, "来源拆分里有认不出的来源「%s」" % "、".join(parts)
        return None, None
    got = {}
    for part in parts:
        m = SPLIT_ITEM.fullmatch(part)
        if not m:
            return None, "来源拆分里有认不出的部分「%s」" % part
        if m.group(1) in got:
            return None, "来源拆分里「%s」写了两次" % m.group(1)
        got[m.group(1)] = int(m.group(2))
    return got, None


def check_proposal(text, shorts):
    """查提案里 S 组的全窗口次数有没有带来源拆分：每组第一次写到全窗口次数的地方要带，带了的要和 signals 一致。
    只认「名字」紧跟次数的写法（中间只许空格、冒号、「共」）；次数和全窗口数不同的（分段次数、写错的总数）不查。"""
    problems, seen = [], []
    for item in shorts:
        names = [item["text"]] + [v for v in item.get("variants", []) if v != item["text"]]
        alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        # 名字和次数之间只许空格、冒号和「共 / 合计」；数字（或「次」）后面要紧跟空白、标点、括号或行尾，
        # 「5 个会话」「5 条消息」「5 %」「5次以上」「5次/周」这类别的计量不是全窗口次数
        edge = "(?=[ \\t]|[（(，,、。；;:：|)）\\]\n]|$)"
        tail = "(?:共|合计|总共)?\\s*(\\d+)(?:\\s*次%s|(?=\\s*(?:[（(，,、。；;|)）\\]\n]|$)))\\s*([（(][^）)\n]*[）)])?" % edge
        quoted = re.compile("[「“\"『](?:%s)[」”\"』][ \\t：:]{0,2}" % alt + tail)
        bare = re.compile("(?<![\\w\u4e00-\u9fff])(?:%s)[ \\t：:]{0,2}" % alt + tail)  # 「合并 40」这种不加引号的写法
        hits = sorted(list(quoted.finditer(text)) + list(bare.finditer(text)), key=lambda m: m.start())
        if not hits:
            continue
        seen.append(item["id"])
        full = [m for m in hits if int(m.group(1)) == item["count"]]
        canon = "「%s」%d 次（%s）" % (item["text"], item["count"], "、".join("%s %d" % (k, v) for k, v in item["channels"].items()))
        line_of = lambda m: text.count("\n", 0, m.start()) + 1
        if not full:
            continue  # 只提到、没写全窗口次数（比如只写分段次数），不强求
        first = full[0]
        if parse_split(first.group(2), item) == (None, None):  # 「（20 次等于推荐）」这种括号不算拆分
            problems.append({"id": item["id"], "line": line_of(first), "problem": "第一次写全窗口次数没带来源拆分", "expected": canon})
        for m in full:
            got, problem = parse_split(m.group(2), item)
            if problem:
                problems.append({"id": item["id"], "line": line_of(m), "problem": problem, "expected": canon})
            elif got is not None and got != item["channels"]:
                problems.append({"id": item["id"], "line": line_of(m), "problem": "来源拆分和 signals 对不上：%s" % m.group(2), "expected": canon})
    return seen, problems


D_FIELDS = ("重复信号", "常浩在替 AI 做什么", "建议做法", "落点", "怎么量")
D_HEADING = re.compile(r"(?m)^#{2,4}\s*(D\d+)\b")


def check_d_items(text):
    """D 类每条要有五项；重复信号要列 S / L 编号，有 S 组的，等于按钮、等于推荐都要写出次数（为 0 也写）。"""
    problems = []
    heads = list(D_HEADING.finditer(text))
    for m in heads:
        end = re.compile(r"(?m)^#{1,4}\s").search(text, m.end())
        body = text[m.end():end.start() if end else len(text)]
        line = text.count("\n", 0, m.start()) + 1
        fields = {}
        # 只认没有缩进的顶层字段；缩进子项里的「- 落点：」是说明，不算主字段
        found = list(re.finditer(r"(?m)^[-*][ \t]*\**(%s)\**[ \t]*[：:]" % "|".join(re.escape(x) for x in D_FIELDS), body))
        for i, f in enumerate(found):
            # 一项的内容含它下面缩进的子项，到下一个顶层字段为止（各组编号常分行列在子项里）
            fields.setdefault(f.group(1), body[f.end():found[i + 1].start() if i + 1 < len(found) else len(body)])
        missing = [x for x in D_FIELDS if x not in fields]
        if missing:
            problems.append({"id": m.group(1), "line": line, "problem": "缺「%s」" % "」「".join(missing),
                             "expected": "五项都写：" + "、".join(D_FIELDS)})
        signal = fields.get("重复信号")
        if signal is None:
            continue
        if not re.search(r"\b[SL]\d+", signal):
            problems.append({"id": m.group(1), "line": line, "problem": "重复信号没列 S / L 编号",
                             "expected": "列出涉及的每个 S / L 编号"})
        elif re.search(r"\bS\d+", signal):
            # 等于按钮、等于推荐后面（或前面）要有数字，为 0 也写
            lack = [x for x in ("等于按钮", "等于推荐")
                    if not re.search(r"%s\s*[:：]?\s*\d+|\d+\s*次?\s*%s" % (x, x), signal)]
            if lack:
                problems.append({"id": m.group(1), "line": line, "problem": "重复信号没写「%s」几次" % "」「".join(lack),
                                 "expected": "重复信号里写等于按钮几次、等于推荐几次，为 0 也写"})
    return problems


def cmd_check(args):
    proposal = Path(args.proposal).expanduser()
    signals = Path(args.signals).expanduser() if args.signals else proposal.parent / "signals.json"
    try:
        text = proposal.read_text(encoding="utf-8")
        shorts = json.loads(signals.read_text(encoding="utf-8"))["signals"]["repeats"]["short_messages"]
    except (OSError, ValueError, KeyError) as error:
        sys.stderr.write("读不了提案或 signals.json：%s\n" % error)
        return 2
    seen, problems = check_proposal(text, shorts)
    problems += check_d_items(text)
    lines = ["提到的 S 组：%s" % ("、".join(seen) or "无")]
    for item in problems:
        lines.append("- 第 %d 行 %s：%s。应写成：%s" % (item["line"], item["id"], item["problem"], item["expected"]))
    lines.append("通过" if not problems else "共 %d 处要改" % len(problems))
    sys.stdout.write("\n".join(lines) + "\n")
    return 1 if problems else 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="session_retro.py",
        description="只读扫描本机 Claude Code / Codex 会话记录，抽出复盘信号；不联网、不改会话、不写规则文件。",
    )
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="按时间窗口和项目抽取信号，写 signals.json 与 signals.md")
    scan.add_argument("--days", type=int, default=7, help="最近几天（含今天），默认 7")
    scan.add_argument("--start", help="开始日期 YYYY-MM-DD（含），与 --days 二选一")
    scan.add_argument("--end", help="结束日期 YYYY-MM-DD（不含），默认明天")
    scan.add_argument("--timezone", default="Asia/Shanghai", help="IANA 时区，默认 Asia/Shanghai")
    scan.add_argument("--source", choices=("all", "claude", "codex"), default="all")
    scan.add_argument("--project", action="append", help="只看工作目录包含这段文字的会话，可重复，不区分大小写")
    scan.add_argument("--claude-root", action="append", help="Claude Code 会话根目录，默认 ~/.claude/projects")
    scan.add_argument("--codex-root", action="append", help="Codex 会话根目录，默认 ~/.codex/sessions 和 ~/.codex/archived_sessions")
    scan.add_argument("--exclude-session", action="append", help="排除的会话 ID（比如正在做复盘的这个会话），可重复")
    scan.add_argument("--min-streak", type=int, default=3, help="同一操作失败几次算「连续失败」，默认 3")
    scan.add_argument("--max-items", type=int, default=300, help="每类信号最多保留几条，默认 300")
    scan.add_argument("--short-min", type=int, default=SHORT_MIN, help="短话出现几次才列进「重复」，默认 %d；窗口短或想看长尾时调低" % SHORT_MIN)
    scan.add_argument("--out", help="输出目录，默认 ~/session-retro/<开始>_<结束>/")
    scan.add_argument("--allow-in-repo", action="store_true", help="允许输出到 git 仓库里（默认拒绝，防止误提交）")
    add_rule_args(scan)
    scan.set_defaults(func=cmd_scan)

    context = sub.add_parser("context", help="查看某条出处前后几轮对话（已脱敏），用于核实信号")
    context.add_argument("file", help="会话文件路径（信号里的出处）")
    context.add_argument("--line", type=int, required=True, help="出处行号")
    context.add_argument("--before", type=int, default=3, help="往前看几条用户/AI 消息，默认 3")
    context.add_argument("--after", type=int, default=2, help="往后看几条，默认 2")
    context.add_argument("--width", type=int, default=500, help="每条消息最多显示几个字，默认 500")
    context.add_argument("--timezone", default="Asia/Shanghai")
    context.set_defaults(func=cmd_context)

    match = sub.add_parser("match", help="拿提案草稿对照现有规则，看是否已经写过")
    match.add_argument("--text", action="append", help="一条提案文字，可重复")
    match.add_argument("--file", help="文本文件，每行一条提案")
    match.add_argument("--project-dir", action="append", help="一并对照这个项目的 CLAUDE.md、AGENTS.md、docs/LESSONS.md，可重复")
    match.add_argument("--top", type=int, default=3)
    match.add_argument("--threshold", type=float, default=0.35, help="相似度下限，默认 0.35")
    add_rule_args(match)
    match.set_defaults(func=cmd_match)

    check = sub.add_parser("check", help="查提案：「重复」各组第一次写全窗口次数时有没有带来源拆分、拆分数对不对（次数本身写错的查不出）；D 类五项和等于按钮、等于推荐写全没有")
    check.add_argument("proposal", help="提案.md 路径")
    check.add_argument("--signals", help="signals.json 路径，默认和提案同目录")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    if args.command == "scan":
        if args.start and "--days" in (argv if argv is not None else sys.argv):
            sys.stderr.write("参数错误：--days 和 --start 只能用一个\n")
            return 2
        if args.start:
            args.days = None
        args.claude_root = args.claude_root or [str(Path.home() / ".claude" / "projects")]
        args.codex_root = args.codex_root or [str(Path.home() / ".codex" / "sessions"), str(Path.home() / ".codex" / "archived_sessions")]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
