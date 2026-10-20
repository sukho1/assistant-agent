import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
const argv=process.argv.slice(2),value=(key)=>{const i=argv.indexOf(key);return i<0?null:argv[i+1];};
const web=path.resolve(value("--web")??process.cwd()),aa=value("--aa")?path.resolve(value("--aa")):null;
const read=p=>fs.readFileSync(p,"utf8").replaceAll("\r\n","\n");
const module=read(path.join(web,"apps/api/src/pipeline/guardrails.ts"));
const stages=JSON.parse(module.slice(module.indexOf("= {")+2,module.indexOf(" as const;")));
const spec=JSON.parse(read(path.join(web,"docs/operations/error-patterns-and-guardrails-20261020.json")));
const oldKeys=["core","input","strategy","scan","specialist","integration","compose","selfcheck","revision","recheck"];
for(let i=0;i<oldKeys.length;i++)assert.deepEqual(stages[oldKeys[i]],{ids:spec.stageReminders[i].ids,text:spec.stageReminders[i].prompt});
const covered=new Set(Object.values(stages).flatMap(s=>s.ids));
for(const p of spec.patterns)assert.ok(covered.has(p.id),p.id+" missing stage binding");
const names=["counseling","alienation","karma-diagnosis","innate-wholeness","deep-psychology","self-healing","link-rebuild","profile-update","diary-process","link-past-self"];
const findings=[];
for(const repo of [web,...aa?[aa]:[]])for(const platform of [".claude",".codex"])for(const name of names){
 const text=read(path.join(repo,platform,"skills",name,"SKILL.md"));
 assert.match(text,/^---\nname: /);assert.match(text,/\ndescription: /);
 const keys=name==="counseling"?["input","strategy","scan","integration","compose","selfcheck","revision","recheck"]:[name==="profile-update"||name==="diary-process"?"memory":name==="link-past-self"?"pastSelf":"specialist"];
 for(const key of keys){
  const start="<!-- stage-guardrails:"+key+":v2 -->",end="<!-- /stage-guardrails:"+key+":v2 -->";
  assert.equal(text.split(start).length-1,1,name+" duplicate/missing "+key);
  const actual=text.slice(text.indexOf(start)+start.length,text.indexOf(end)).trim();assert.equal(actual,stages[key].text,name+" "+key);
 }
 if(name==="counseling"){
  const check=text.slice(text.indexOf("### 输出前自检"),text.indexOf("## 子skill路由表"));
  assert.ok(check.includes(stages.selfcheck.text)&&check.includes(stages.recheck.text));
 }
 findings.push({repo:path.basename(path.dirname(repo)),platform,name,sha256:createHash("sha256").update(text).digest("hex")});
}
if(aa)for(const name of ["AGENTS.md","CLAUDE.md"])assert.ok(read(path.join(aa,name)).includes(stages.core.text));
console.log(JSON.stringify({passed:true,stageGroups:Object.keys(stages).length,ruleIds:covered.size,skillFiles:findings.length,findings},null,2));
