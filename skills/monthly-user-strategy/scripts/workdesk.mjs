#!/usr/bin/env node
// 调用牛马之家的 workdesk 智能体工具（docs/API.md「智能体接入」）。会话里没有接 workdesk MCP 时用它；接了就直接用 MCP 工具，效果相同。
// 走的是工作台的智能体接口（授权、留痕都在服务端），不读数据库。
//
//   node workdesk.mjs <工具> [参数 JSON 文件 | -] [--out <结果文件>]
//     工具：strategy_facts / strategy_submit / strategy_submission
//     参数：JSON 文件路径，或 - 从标准输入读；strategy_facts 也可直接写 --month 2026-12
//
// 环境变量：WORKDESK_AGENT_TOKEN（必填；或 WORKDESK_ENV 指向写有 WORKDESK_AGENT_TOKEN= 的 .env 文件），WORKDESK_URL（默认 http://127.0.0.1:5280）。
// 退出码：0 成功；2 服务端明确拒绝（4xx，结果里有原因，内容未保存）；3 结果不明（网络错误、超时、5xx、返回不是 JSON）。
// 退出码 3 时不要重跑 strategy_submit：先按 SKILL.md「结果不明」一节核对。
import { readFileSync, writeFileSync } from 'node:fs';

const args = process.argv.slice(2);
const flag = name => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : undefined; };
const out = flag('--out'), month = flag('--month');
const [tool, input] = args;
const die = (code, message) => { process.stderr.write(`${message}\n`); process.exit(code); };
if (!tool) die(1, '用法：node workdesk.mjs <工具> [参数 JSON 文件 | -] [--month YYYY-MM] [--out 结果文件]');

let token = process.env.WORKDESK_AGENT_TOKEN || '';
if (!token && process.env.WORKDESK_ENV) token = (readFileSync(process.env.WORKDESK_ENV, 'utf8').match(/^WORKDESK_AGENT_TOKEN=(.+)$/m) || [])[1]?.trim() || '';
if (!token) die(1, '缺少 WORKDESK_AGENT_TOKEN（或 WORKDESK_ENV）。凭据由常浩用 niuma-home 的 scripts/agent-token.mjs 签发，不要自己签发正式凭据。');

let params = {};
if (month) params = { month };
else if (input) params = JSON.parse(input === '-' ? readFileSync(0, 'utf8') : readFileSync(input, 'utf8'));

const base = (process.env.WORKDESK_URL || 'http://127.0.0.1:5280').replace(/\/$/, '');
// 凭据只发给本机工作台（牛马之家只监听 127.0.0.1），防止 WORKDESK_URL 被设成别处把凭据带出去。
if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(base)) die(1, `WORKDESK_URL 只能是本机地址（http://127.0.0.1:<端口>），现在是 ${base}`);
// caller 是提问人：本 skill 只替常浩本人跑，固定写本机会话。
const body = { arguments: params, caller: { platform: 'local-session', chatType: 'p2p', userId: 'changhao' } };
let res, data;
try {
  res = await fetch(`${base}/api/v3/agent/tools/${encodeURIComponent(tool)}`, {
    method: 'POST', headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(120_000),
  });
  data = await res.json();
} catch (error) {
  die(3, `结果不明：${error.name === 'TimeoutError' ? '等待超时' : error.message}${res ? `（HTTP ${res.status}）` : ''}`);
}
if (!res.ok) die(res.status >= 500 ? 3 : 2, `${res.status >= 500 ? '结果不明' : '服务端拒绝'}（HTTP ${res.status}${data.code ? ` ${data.code}` : ''}）：${data.error ?? JSON.stringify(data)}`);
const text = JSON.stringify(data.result, null, 2);
if (out) { writeFileSync(out, `${text}\n`); process.stdout.write(`已写入 ${out}\n`); } else process.stdout.write(`${text}\n`);
