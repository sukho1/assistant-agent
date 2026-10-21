import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
const argv=process.argv.slice(2),value=key=>{const i=argv.indexOf(key);return i<0?null:argv[i+1];};
const web=path.resolve(value("--web")??process.cwd()),aa=value("--aa")?path.resolve(value("--aa")):null;
const read=p=>fs.readFileSync(p,"utf8").replaceAll("\r\n","\n");
const module=read(path.join(web,"apps/api/src/pipeline/guardrails.ts"));
const stages=JSON.parse(module.slice(module.indexOf("= {")+2,module.indexOf(" as const;")));
const spec=JSON.parse(read(path.join(web,"docs/operations/guardrails-content-v3-20261021.json")));
assert.deepEqual(stages,spec.stageReminders);
const allowed=new Set([...spec.rules,...spec.checkerRules].map(r=>r.id));
const locations=new Set([...allowed,...spec.guidance.map(r=>r.id),...spec.systems.map(r=>r.id)]);
const old=JSON.parse(read(path.join(web,"docs/operations/error-patterns-and-guardrails-20261020.json")));
assert.deepEqual(spec.legacyDisposition.map(d=>d.id).sort(),old.patterns.map(p=>p.id).sort());
for(const d of spec.legacyDisposition){assert.ok(d.destinations.length&&d.reason,d.id);for(const target of d.destinations)assert.ok(locations.has(target),target);}
for(const [key,s] of Object.entries(stages)){for(const id of s.ids)assert.ok(allowed.has(id),key+" invalid runtime ID "+id);}
for(const key of ["selfcheck","recheck"])for(const r of spec.rules){assert.ok(stages[key].ids.includes(r.id));assert.ok(stages[key].text.includes(r.text),key+" missing boundary "+r.id);}
const covered=new Set(Object.values(stages).flatMap(s=>s.ids));for(const id of allowed)assert.ok(covered.has(id),id);
const names=["counseling","alienation","karma-diagnosis","innate-wholeness","deep-psychology","self-healing","link-rebuild","profile-update","diary-process","link-past-self"];
const findings=[];
for(const repo of [web,...aa?[aa]:[]])for(const platform of [".claude",".codex"])for(const name of names){
 const text=read(path.join(repo,platform,"skills",name,"SKILL.md"));
 assert.match(text,/^---\nname: /);assert.match(text,/\ndescription: /);
 assert.ok(!text.includes("stage-guardrails:"+"selfcheck:v2"),"stale checklist");
 const keys=name==="counseling"?["input","strategy","scan","integration","compose","selfcheck","revision","recheck"]:[name==="profile-update"||name==="diary-process"?"memory":name==="link-past-self"?"pastSelf":"specialist"];
 for(const key of keys){const start="<!-- stage-guardrails:"+key+":v3 -->",end="<!-- /stage-guardrails:"+key+":v3 -->";assert.equal(text.split(start).length-1,1,name+" "+key);assert.equal(text.slice(text.indexOf(start)+start.length,text.indexOf(end)).trim(),stages[key].text);}
 if(name==="counseling"){const check=text.slice(text.indexOf("### 输出前自检"),text.indexOf("## 子skill路由表"));assert.ok(check.includes(stages.selfcheck.text)&&check.includes(stages.recheck.text));assert.ok(!check.includes("至少一处能笑"));}
 findings.push({repo:repo===web?"web":"aa",platform,name,sha256:createHash("sha256").update(text).digest("hex")});
}
if(aa){for(const f of ["AGENTS.md","CLAUDE.md"])assert.ok(read(path.join(aa,f)).includes(stages.core.text));assert.deepEqual(JSON.parse(read(path.join(aa,"docs/guardrails-content-v3-20261021.json"))),spec);}
console.log(JSON.stringify({passed:true,stageGroups:Object.keys(stages).length,responseRules:spec.rules.length,checkerRules:spec.checkerRules.length,mappedLegacyItems:spec.legacyDisposition.length,systems:spec.systems.length,skillFiles:findings.length,findings},null,2));
