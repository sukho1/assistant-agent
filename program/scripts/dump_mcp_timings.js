// dump_mcp_timings.js —— 从 DSH 会话日志里还原每次 MCP 调用的真实往返耗时
//
// 用法：node program/scripts/dump_mcp_timings.js "<session.v4.jsonl.zstd 绝对路径>"
//   会话日志位置：~/.dsh/sessions/<工作区目录名>/<会话 id>/session.v4.jsonl.zstd
//
// 为什么不直接看 UI 面板：工具状态与耗时只由实测认定，面板显示与之是两回事。
//
// 两个必须知道的坑（2026-09-30 踩到）：
//   1. 会话日志是【多帧 zstd】。zlib.zstdDecompressSync 只会解出第一帧（结果里只有 1 条
//      session 记录），必须按帧魔数 28 B5 2F FD 逐帧切分后逐帧解，才能拿到全部记录。
//   2. toolCallId 嵌在 data.message.toolCallId，不是 data.toolCallId；写错会一行都匹配不上。
//
// 配对方式：tool/call 的 data.callId <-> tool/result 的 data.message.toolCallId，
// 两条记录各自的 time（epoch ms）之差 = 该次调用的真实往返耗时。

const fs = require('fs');
const zlib = require('zlib');

const file = process.argv[2];
if (!file) {
  console.error('用法: node program/scripts/dump_mcp_timings.js <session.v4.jsonl.zstd>');
  process.exit(1);
}

const buf = fs.readFileSync(file);
const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);

// 按帧魔数切分；某一段解不开就跳过，不影响其余帧
const magics = [];
let i = 0;
while ((i = buf.indexOf(MAGIC, i)) !== -1) { magics.push(i); i += 1; }

let start = magics.length ? magics[0] : 0;
let k = 1;
const parts = [];
while (k <= magics.length) {
  const end = k < magics.length ? magics[k] : buf.length;
  try {
    parts.push(zlib.zstdDecompressSync(buf.subarray(start, end)).toString('utf8'));
    start = end;
    k++;
  } catch (e) {
    k++;
  }
}

const parsed = [];
for (const line of parts.join('').split('\n').filter(Boolean)) {
  try { parsed.push(JSON.parse(line)); } catch (e) {}
}

const first = parsed.find((o) => o.type === 'session');
if (first) {
  console.log('session id: ' + first.id + '  | createdAt: ' + new Date(first.createdAt).toLocaleString('sv-SE'));
}

const calls = new Map();
for (const o of parsed) {
  if (o.type === 'tool/call') {
    calls.set(o.data.callId, { name: o.data.name, t: o.time, args: String(o.data.arguments || '') });
  }
}

const rows = [];
const seen = new Set();
for (const o of parsed) {
  if (o.type !== 'tool/result') continue;
  const id = (o.data.message && o.data.message.toolCallId) || o.data.toolCallId;
  const c = calls.get(id);
  if (!c || seen.has(id)) continue;
  seen.add(id);
  rows.push({ name: c.name, ms: o.time - c.t, args: c.args, t: c.t });
}

const mcp = rows.filter((r) => r.name.startsWith('mcp__'));
console.log('\n=== MCP calls (' + mcp.length + ') ===');
for (const r of mcp) {
  let q = '';
  const m = r.args.match(/"(?:query|queries)"\s*:\s*("(?:[^"\\]|\\.)*"|\[[^\]]*\])/);
  if (m) q = m[1];
  console.log(String(r.ms).padStart(7) + ' ms  ' + new Date(r.t).toLocaleTimeString('sv-SE') + '  ' + r.name + '  ' + q);
}

// 每次请求实际发给模型的工具清单（request/header.data.header.tools）。
// 这是"工具到底注入了没有"的事后取证依据：坏配置期 total=34 且 mcp__* 为 0；
// 修好 cwd 后 total=36，多出的 2 个就是 mcp__diary-rag__search_diary / search_diary_batch。
const headers = parsed.filter((o) => o.type === 'request/header');
if (headers.length) {
  console.log('\n=== tool snapshot per request (' + headers.length + ') ===');
  for (const h of headers) {
    const names = (((h.data || {}).header || {}).tools || []).map((t) => t.name);
    const mcp = names.filter((n) => n.indexOf('mcp__') === 0);
    console.log('  ' + new Date(h.time).toLocaleTimeString('sv-SE') +
      '  total=' + names.length + '  mcp__*=' + mcp.length +
      (mcp.length ? '  [' + mcp.join(', ') + ']' : ''));
  }
}

const others = rows.filter((r) => !r.name.startsWith('mcp__'));
if (others.length) {
  console.log('\n=== other tool calls (' + others.length + ') ===');
  for (const r of others) {
    console.log(String(r.ms).padStart(7) + ' ms  ' + new Date(r.t).toLocaleTimeString('sv-SE') + '  ' + r.name);
  }
}
