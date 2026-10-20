// AA 私有子 skill 保持本地；本脚本仅验证，不打印或公开其正文。
// node program/scripts/verify_marx_skills.mjs [--web <Web仓库根目录>]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const i=process.argv.indexOf('--web');
const roots=[root,...(i>=0?[path.resolve(process.argv[i+1])]:[])];
const names=['counseling','alienation','karma-diagnosis'];
const read=p=>fs.readFileSync(p,'utf8').replace(/\r\n/g,'\n');
const results=[];
for(const repo of roots){
 for(const platform of ['.claude','.codex']) for(const name of names){
  const p=path.join(repo,platform,'skills',name,'SKILL.md'),text=read(p);
  assert.ok(/^---\nname: ["']?[\w-]+["']?\ndescription: /.test(text),'Invalid frontmatter: '+name);
  if(name!=='counseling') assert.ok(text.includes('## 核心框架'),'Missing core: '+name);
  assert.ok(text.includes('认知不足')&&text.includes('自我疗愈不足')&&text.includes('严重错误'));
  assert.ok(text.includes('马克思主义和庄子哲学，是分析的指导思想。'));
  assert.ok(text.includes('你本来就无条件的存在，应得无条件的尊重，何况你的劳动对世界有正面贡献。'));
  assert.ok(text.includes('你可以没有改变愿望，仍然值得被好好对待。'));
  if(name==='counseling'){
   assert.ok(/定位到此维必须调 `karma-diagnosis` 和 `alienation`/.test(text),'Missing paired routing');
   assert.ok(text.includes('四维度是系统链接的，不是割裂的'));
   assert.ok(text.includes('社会归因、共同处境和人民链接'));
  }else if(name==='alienation'){
   assert.ok(text.includes('counseling 或 karma-diagnosis'));
   assert.ok(text.includes('普通阿富汗女孩、越南工人、美国蓝领'));
   for(const article of ['zhuangzi-series/普通人如何感受本自具足.md','link-series/我们身为小微资，如何链接无产阶级朴实真善美.md','link-series/拼多多评论区文学和菜市场疗愈.md']){
    assert.ok(text.includes(article));assert.ok(fs.existsSync(path.join(repo,'knowledge',article)),article);
   }
  }else{
   assert.ok(text.includes('分析外部业障时，必须调用 `alienation`'));
   assert.ok(text.includes('不必晚上再交一份成长成绩单'));
   assert.ok(text.includes('上进、改变、革命的力量'));
   assert.ok(text.includes('不能断言其动机'));
  }
  const start=name==='counseling'?text.indexOf('### 模型一：'):text.indexOf('## 核心框架');
  const route=text.indexOf('## 知识路由表',start);
  const core=text.slice(start,route<0?undefined:route).trim();
  if(name!=='counseling') assert.ok(core.length<=6000,'Web框架注入截断: '+name);
  const publicVersion=text.replaceAll('.codex/skills','.claude/skills');
  results.push({repo:path.basename(repo),platform,name,coreChars:core.length,sha256:createHash('sha256').update(publicVersion).digest('hex')});
 }
 for(const file of ['AGENTS.md','CLAUDE.md']){
  const text=read(path.join(repo,file));
  assert.ok(text.includes('主干是庄子和马克思哲学'));
  assert.ok(text.includes('认知不足')&&text.includes('严重错误'));
 }
}
// 比较本轮改造的共同框架，保留平台特定工具措辞和既有文件其余部分。
for(const name of ['alienation','karma-diagnosis']){
 const cores=roots.flatMap(repo=>['.claude','.codex'].map(platform=>{
  const s=read(path.join(repo,platform,'skills',name,'SKILL.md'));
  return s.slice(s.indexOf('## 核心框架'),s.indexOf('## 知识路由表')).replaceAll('.codex/skills','.claude/skills');
 }));
 for(const core of cores) assert.ok(core===cores[0],name+'共同框架不同步');
}
console.log(JSON.stringify({passed:true,checked:results.length,assets:results},null,2));
