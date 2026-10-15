// dump_cc_timings.js —— 从 Claude Code 会话 transcript 里还原工具调用耗时
//
// 用法：node program/scripts/dump_cc_timings.js ["<session.jsonl 路径>"]
//   会话日志位置：~/.claude/projects/<工作区目录名>/<会话 id>.jsonl
//   （<工作区目录名> 由 cwd 编码而来，把 \ / : 都换成 - ，例如
//    C:\Users\su35\Documents\assistant-agent -> C--Users-su35-Documents-assistant-agent）
//   省略参数时自动取当前项目目录下最新的 .jsonl。
//
// 与 dump_mcp_timings.js 的区别：那版解析 DSH（DeepSeek Harness）的多帧 zstd 日志，
// 这版解析 Claude Code 的明文 JSONL，两者格式不同、不通用。
//
// 数据模型（2026-10-15 实测）：
//   1. 每条记录带 ISO 时间戳 o.timestamp。
//   2. tool_use 在 assistant 记录的 message.content[] 里：{type:"tool_use", id, name, input}
//   3. tool_result 在 user 记录的 message.content[] 里：{type:"tool_result", tool_use_id, content}
//   4. 真实用户输入是 type:"user" 且 message.content 为【字符串】（不是数组）——据此切 turn。
//   配对 tool_use.id <-> tool_result.tool_use_id，两条记录时间差 = 该次调用的往返耗时。

const fs = require('fs');
const path = require('path');
const os = require('os');

function newestTranscript() {
  const cwd = process.cwd();
  const encoded = cwd.replace(/[\\/:]/g, '-');
  const dir = path.join(os.homedir(), '.claude', 'projects', encoded);
  const files = fs.readdirSync(dir)
    .filter((f) => f.endsWith('.jsonl'))
    .map((f) => ({ f, t: fs.statSync(path.join(dir, f)).mtimeMs }))
    .sort((a, b) => b.t - a.t);
  if (!files.length) throw new Error('no .jsonl in ' + dir);
  return path.join(dir, files[0].f);
}

const file = process.argv[2] || newestTranscript();
const lines = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean);

const events = [];
for (const l of lines) {
  let o;
  try { o = JSON.parse(l); } catch (e) { continue; }
  if (!o.timestamp) continue;
  const ts = Date.parse(o.timestamp);
  if (Number.isNaN(ts)) continue;
  const c = o.message && o.message.content;
  if (o.type === 'user' && typeof c === 'string') {
    events.push({ ts, kind: 'PROMPT', text: c.replace(/\s+/g, ' ').slice(0, 46) });
  } else if (Array.isArray(c)) {
    for (const b of c) {
      if (!b || typeof b !== 'object') continue;
      if (b.type === 'tool_use') events.push({ ts, kind: 'use', id: b.id, name: b.name, input: b.input || {} });
      else if (b.type === 'tool_result') events.push({ ts, kind: 'result', id: b.tool_use_id });
    }
  }
}
events.sort((a, b) => a.ts - b.ts);

const useTs = new Map();
const rows = [];
for (const e of events) {
  if (e.kind === 'use') useTs.set(e.id, e);
  else if (e.kind === 'result' && useTs.has(e.id)) {
    const u = useTs.get(e.id);
    rows.push({ ts: u.ts, ms: e.ts - u.ts, name: u.name, input: u.input });
  }
}

function shortArg(inp) {
  if (inp.queries) return 'queries=' + JSON.stringify(inp.queries).slice(0, 80);
  if (inp.query) return 'query=' + JSON.stringify(inp.query).slice(0, 56);
  if (inp.file_path) return String(inp.file_path).replace(/^.*[\\/]/, '');
  if (inp.pattern) return 'pattern=' + String(inp.pattern).slice(0, 40);
  if (inp.command) return String(inp.command).slice(0, 56);
  return Object.keys(inp).join(',');
}

console.log('file: ' + file);
console.log('\n=== tool calls (paired ' + rows.length + '/' + (events.filter(e => e.kind === 'use').length) + ') ===');
for (const r of rows) {
  console.log(String(r.ms).padStart(8) + ' ms  ' + new Date(r.ts).toLocaleTimeString('sv-SE') +
    '  ' + r.name.padEnd(34) + '  ' + shortArg(r.input));
}

const mcp = rows.filter((r) => r.name.startsWith('mcp__'));
if (mcp.length) {
  const tot = mcp.reduce((s, r) => s + r.ms, 0);
  console.log('\n=== MCP (' + mcp.length + ' calls, ' + (tot / 1000).toFixed(2) + 's total) ===');
  for (const r of mcp) console.log(String(r.ms).padStart(8) + ' ms  ' + shortArg(r.input));
}

const prompts = events.filter((e) => e.kind === 'PROMPT');
if (prompts.length) {
  console.log('\n=== per-turn wall vs tool ===');
  const fmt = (ms) => (ms / 1000).toFixed(1) + 's';
  for (let i = 0; i < prompts.length; i++) {
    const start = prompts[i].ts;
    const end = i + 1 < prompts.length ? prompts[i + 1].ts : events[events.length - 1].ts;
    const inTurn = rows.filter((r) => r.ts >= start && r.ts < end);
    const toolMs = inTurn.reduce((s, r) => s + r.ms, 0);
    const wall = end - start;
    if (wall <= 0) continue;
    console.log('  turn ' + (i + 1) + ' [' + new Date(start).toLocaleTimeString('sv-SE') + '] "' +
      prompts[i].text + '"  wall ' + fmt(wall) + ' | tool ' + fmt(toolMs) +
      ' (' + (100 * toolMs / wall).toFixed(1) + '%) | model ' + fmt(wall - toolMs));
  }
  console.log('  注：wall 含两次输入之间的用户思考/打字空档，故 model 为上界。');
}
