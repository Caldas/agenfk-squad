import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync, spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
const base=process.env.PI_COMPAT_PI_ROOT;
const req=createRequire(path.join(base,'package.json'));
const {createJiti}=req('jiti');
const jiti=createJiti(import.meta.url,{alias:{'@earendil-works/pi-coding-agent':path.join(base,'dist/index.js'),'@earendil-works/pi-ai':path.join(base,'node_modules/@earendil-works/pi-ai/dist/index.js'),'typebox':path.join(base,'node_modules/typebox/build/index.mjs')}});
const dir=path.dirname(fileURLToPath(import.meta.url));
const v=await jiti.import(path.join(dir,'vigia.ts'));
const card='10000000-1111-2222-3333-444444444444';
function harness(t, raw={}, restored=[]) {
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'pi-vigia-test-')), cwd=path.join(root,'repo'), ad=path.join(root,'agent'); fs.mkdirSync(cwd); fs.mkdirSync(ad);
 const old=process.env.PI_CODING_AGENT_DIR; process.env.PI_CODING_AGENT_DIR=ad;
 execFileSync('git',['init','-q'],{cwd}); execFileSync('git',['-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-q','--allow-empty','-m','fixture'],{cwd});
 const handlers=new Map(), tools=new Map(), commands=new Map(), messages=[], queued=[], entries=structuredClone(restored), switches=[], compactions=[];
 let usage={tokens:100,contextWindow:1000}, idle=false, pending=false, thinking='high', active=['read','squad_handoff'];
 const ctx={cwd,mode:'rpc',model:{provider:'fixture',id:'selected',contextWindow:1000},modelRegistry:{find:(provider,id)=>({provider,id})},hasUI:false,compact:options=>compactions.push(options),isProjectTrusted:()=>true,isIdle:()=>idle,hasPendingMessages:()=>pending,getContextUsage:()=>usage,waitForIdle:async()=>{idle=true;},sessionManager:{getEntries:()=>entries,getBranch:()=>entries,getSessionId:()=> 'fixture-session',getLeafId:()=>entries.at(-1)?.id??null,getSessionFile:()=>path.join(root,'session.jsonl')},newSession:async opts=>{switches.push(opts);await opts.setup({appendCustomEntry:(type,data)=>pi.appendEntry(type,data)}); await opts.withSession({sessionManager:ctx.sessionManager,sendUserMessage:async(s,options)=>{if(s.startsWith('/squad-restore-runtime ')){await commands.get('squad-restore-runtime').handler(s.split(' ')[1],ctx);}else switches.at(-1).kickoff=s;}}); return {cancelled:false};}};
 const pi={getThinkingLevel:()=>thinking,setThinkingLevel:x=>thinking=x,getActiveTools:()=>active,getAllTools:()=>[{name:'read'},{name:'squad_handoff'}],setActiveTools:x=>active=x,setModel:async m=>{ctx.model=m;return true;},on:(n,h)=>handlers.set(n,[...(handlers.get(n)??[]),h]),registerTool:x=>tools.set(x.name,x),registerCommand:(n,x)=>commands.set(n,x),appendEntry:(customType,data)=>entries.push({type:'custom',customType,data:structuredClone(data),id:String(entries.length)}),sendMessage:(message,opts)=>messages.push({message,opts}),sendUserMessage:(text,opts)=>queued.push({text,opts}),exec:async(command,args,options)=>{try{return {code:0,killed:false,stdout:execFileSync(command,args,{cwd:options.cwd,encoding:'utf8',stdio:['ignore','pipe','pipe']}),stderr:''};}catch(e){return {code:1,killed:false,stdout:'',stderr:''};}}};
 v.attachVigia(pi,()=>raw);
 const emit=async(name,event={})=>{const results=[]; for(const h of handlers.get(name)??[]) results.push(await h(event,ctx)); return results.find(x=>x!==undefined);};
 const start=()=>emit('session_start');
 const call=async(name,input={},id=String(Math.random()))=>{await emit('tool_execution_start',{toolCallId:id,toolName:name,args:input}); const out=await emit('tool_call',{toolCallId:id,toolName:name,input}); return {out,id,end:()=>emit('tool_execution_end',{toolCallId:id,toolName:name})};};
 const handoff=async(signal)=>{const c=await call('squad_handoff'); assert.equal(c.out,undefined); const out=await tools.get('squad_handoff').execute(c.id,{summary:'Implemented a focused change. Test/review status is still pending.',nextStep:'Inspect the card and run the targeted regression suite.',card},signal,undefined,ctx); await c.end(); return out;};
 t.after(async()=>{await emit('session_shutdown');if(old===undefined)delete process.env.PI_CODING_AGENT_DIR;else process.env.PI_CODING_AGENT_DIR=old;fs.rmSync(root,{recursive:true,force:true});});
 return {root,cwd,ad,pi,ctx,handlers,tools,commands,messages,queued,entries,switches,compactions,start,emit,call,handoff,setUsage:x=>usage=x,setPending:x=>pending=x,setIdle:x=>idle=x};
}
test('vigia validates limits and uses the actual model window, never a fixed 1M',()=>{
 const c=v.vigiaConfig({handoffPercent:NaN,maxDispatches:0,maxChildren:99}); assert.equal(c.handoffPercent,80);assert.equal(c.maxDispatches,40);assert.equal(c.maxChildren,4);assert.equal(c.maxOrchestrators,3);
 assert.equal(v.contextLevel(180000,1000000,c),'ok'); assert.equal(v.contextLevel(180000,200000,c),'handoff'); assert.equal(v.contextLevel(70000,100000,c),'prepare');
 assert.equal(v.contextLevel(null,100000,c),'unknown');assert.equal(v.contextLevel(0,0,c),'unknown');assert.equal(v.contextLevel(180000,1000000,c,true),'handoff');
});
test('vigia emits an actionable one-shot model message, not just a UI notification',async t=>{
 const h=harness(t);await h.start();h.setUsage({tokens:900,contextWindow:1000});await h.emit('tool_execution_end',{toolCallId:'none'});await h.emit('tool_execution_end',{toolCallId:'none'});
 assert.equal(h.messages.length,1);assert(h.messages[0].message.content.includes('PROACTIVE HANDOFF'));assert.equal(h.messages[0].opts.deliverAs,'steer');
 const e={entries:[],outcome:'completed'};assert.equal((await h.emit('agent_before_settle',e)).continue,true);assert.equal(await h.emit('agent_before_settle',e),undefined);
 h.setUsage({tokens:100,contextWindow:1000});await h.emit('session_compact');assert.equal((await h.emit('before_agent_start')).message.content.includes('handoff 80%'),true);
});
test('vigia does not wake an idle session or continue an error/aborted boundary',async t=>{
 const h=harness(t);h.setUsage({tokens:950,contextWindow:1000});h.setIdle(true);await h.start();assert.equal(h.messages.length,0);
 assert.equal(await h.emit('agent_before_settle',{entries:[],outcome:'error'}),undefined);assert.equal(await h.emit('agent_before_settle',{entries:[],outcome:'aborted'}),undefined);
});
test('dispatch caps persist across reload and denied briefs are private',async t=>{
 const h=harness(t,{maxDispatches:1});await h.start();const first=await h.call('subagent',{agent:'worker',task:'card '+card});assert.equal(first.out,undefined);await first.end();
 await h.emit('session_shutdown');await h.start();const second=await h.call('subagent',{agent:'worker',task:'next card '+card});assert(second.out.block);assert(second.out.reason.includes('Dispatch cap'));await second.end();
 const notes=fs.readdirSync(path.join(h.ad,'squad/handoffs')).flatMap(d=>fs.readdirSync(path.join(h.ad,'squad/handoffs',d)).map(f=>path.join(h.ad,'squad/handoffs',d,f)));assert.equal(notes.length,1);assert.equal(fs.statSync(notes[0]).mode&0o777,0o600);assert(fs.readFileSync(notes[0],'utf8').includes('next card '+card));
});
test('review count is per card and does not silently approve or spawn a seventh',async t=>{
 const h=harness(t,{maxReviews:1});await h.start();let c=await h.call('subagent',{agent:'verifier',task:'Review '+card});assert.equal(c.out,undefined);await c.end();
 c=await h.call('subagent',{agent:'project-verifier',task:'Review again '+card});assert(c.out.reason.includes('Review cap'));await c.end();
 c=await h.call('subagent',{agent:'project-verifier',task:'Review without card'});assert(c.out.reason.includes('UUID'));await c.end();
 c=await h.call('subagent',{agent:'project-verifier',task:'Review 20000000-1111-2222-3333-444444444444'});assert.equal(c.out,undefined);await c.end();
});
test('high context refuses new dispatch but leaves completion/handoff tools usable',async t=>{
 const h=harness(t);await h.start();h.setUsage({tokens:950,contextWindow:1000});const c=await h.call('subagent',{agent:'worker',task:'work'});assert(c.out.reason.includes('HANDOFF'));await c.end();
 const read=await h.call('read',{path:'file'});assert.equal(read.out,undefined);await read.end();
});
test('loop warning and terminating denial are bounded and persist on reload',async t=>{
 const h=harness(t);await h.start();for(let n=1;n<=7;n++){const c=await h.call('read',{path:'same'});assert.equal(c.out,undefined);await c.end();}
 assert.equal(h.messages.filter(x=>x.message.content.includes('LOOP WARNING')).length,1);await h.emit('session_shutdown');await h.start();const eighth=await h.call('read',{path:'same'});assert.equal(eighth.out.terminate,true);await eighth.end();
 const different=await h.call('read',{path:'other'});assert.equal(different.out,undefined);await different.end();
});
test('global reservation prevents excess children/orchestrators and releases cancelled work',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'pi-vigia-reserve-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const c=v.vigiaConfig({maxChildren:1,maxOrchestrators:1});const release=v.reserveDispatch(root,'one',c);
 assert.throws(()=>v.reserveDispatch(root,'one',c),/Concurrent child cap/);assert.throws(()=>v.reserveDispatch(root,'two',c),/orchestrator slot/);release();release();const r=v.reserveDispatch(root,'two',c);r();assert.equal(fs.readdirSync(root).length,0);
});
test('an existing live reservation lock is never stolen',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'pi-vigia-lock-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));fs.writeFileSync(path.join(root,'dispatch.lock'),String(process.pid));assert.throws(()=>v.reserveDispatch(root,'one',v.vigiaConfig({})),/reserving/);assert.equal(fs.readFileSync(path.join(root,'dispatch.lock'),'utf8'),String(process.pid));
});
test('orchestrator cap is shared with a real competing Pi-side process',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'pi-vigia-cross-process-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const release=v.reserveDispatch(root,'parent',v.vigiaConfig({maxOrchestrators:1}));t.after(release);
 const script=`const {createJiti}=require(${JSON.stringify(req.resolve('jiti'))}); const jiti=createJiti(process.cwd()+'/fixture.cjs',{alias:${JSON.stringify({'@earendil-works/pi-coding-agent':path.join(base,'dist/index.js'),'typebox':path.join(base,'node_modules/typebox/build/index.mjs')})}}); jiti.import(${JSON.stringify(path.join(dir,'vigia.ts'))}).then(v=>{try{v.reserveDispatch(${JSON.stringify(root)},'competing',v.vigiaConfig({maxOrchestrators:1}));process.stdout.write('ALLOWED');}catch(e){process.stdout.write(String(e));}});`;
 const out=execFileSync(process.execPath,['-e',script],{encoding:'utf8'});assert(out.includes('No orchestrator slot'));assert(!out.includes('ALLOWED'));
});
test('review caps follow a card across replacement sessions',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'pi-vigia-review-card-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const c=v.vigiaConfig({maxReviews:1});const release=v.reserveDispatch(root,'old',c,card);release();assert.throws(()=>v.reserveDispatch(root,'new',c,card),/Cross-session review cap/);
});
test('monitor persistence failures fail closed instead of crashing or silently going green',async t=>{
 const h=harness(t);await h.start();h.pi.appendEntry=()=>{throw new Error('disk unavailable');};h.setUsage({tokens:950,contextWindow:1000});await h.emit('tool_execution_end',{toolCallId:'none'});const c=await h.call('read',{path:'file'});assert(c.out.block);assert(c.out.reason.includes('unavailable'));await c.end();
});
test('disabled vigia does not monitor, persist, block or trigger pickup',async t=>{
 const h=harness(t,{enabled:false});await h.start();h.setUsage({tokens:999,contextWindow:1000});await h.emit('before_agent_start');const c=await h.call('subagent',{agent:'worker',task:'work'});assert.equal(c.out,undefined);await c.end();assert.equal(h.messages.length,0);assert.equal(h.entries.length,0);
 await assert.rejects(h.handoff(),/requires an active supervisor/);
});
test('handoff captures git, persists privately and safely switches using the replacement context',async t=>{
 const h=harness(t);await h.start();h.entries.push({type:'message',message:{role:'user',content:'Finish this owner request.'}});const note=await h.handoff();assert.equal(h.queued.length,0);assert.equal(fs.statSync(note.details.file).mode&0o777,0o600);assert(fs.readFileSync(note.details.file,'utf8').includes('Finish this owner request.'));
 await h.commands.get('squad-pickup').handler('',h.ctx);assert.equal(h.switches.length,1);assert(h.switches[0].kickoff.includes('Next step'));assert.equal(h.switches[0].parentSession,h.ctx.sessionManager.getSessionFile());
});
test('automatic pickup is queued only after a vigia order and a complete saved handoff',async t=>{
 const h=harness(t);await h.start();h.setUsage({tokens:950,contextWindow:1000});const note=await h.handoff();assert.equal(note.terminate,true);assert(h.queued[0].text.startsWith('/squad-pickup auto:'));assert.deepEqual(h.queued[0].opts,{deliverAs:'followUp',expandPromptTemplates:true});assert.equal(h.switches.length,0);
 await h.emit('agent_before_settle',{entries:[],outcome:'completed'});
 await h.commands.get('squad-pickup').handler(h.queued[0].text.split(' ')[1],h.ctx);assert.equal(h.switches.length,1);
});
test('missing or modified note never destroys the old session',async t=>{
 const h=harness(t);await h.start();await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Pickup refused/);const note=await h.handoff();fs.appendFileSync(note.details.file,'tampered');await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Handoff changed/);assert.equal(h.switches.length,0);
});
test('git changes, including same-status untracked edits, invalidate pickup',async t=>{
 const h=harness(t);await h.start();fs.writeFileSync(path.join(h.cwd,'untracked.txt'),'old');await h.handoff();fs.writeFileSync(path.join(h.cwd,'untracked.txt'),'new');await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Git changed/);assert.equal(h.switches.length,0);
});
test('pickup from a subdirectory fingerprints untracked files outside that directory',async t=>{
 const h=harness(t);await h.start();fs.mkdirSync(path.join(h.cwd,'sub'));h.ctx.cwd=path.join(h.cwd,'sub');fs.writeFileSync(path.join(h.cwd,'outside.txt'),'old');await h.handoff();fs.writeFileSync(path.join(h.cwd,'outside.txt'),'new');await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Git changed/);assert.equal(h.switches.length,0);
});
test('pickup refuses to resume if original model or original tool set cannot be restored',async t=>{
 const h=harness(t);await h.start();await h.handoff();h.pi.setModel=async()=>false;await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Original model/);assert.equal(h.switches[0].kickoff,undefined);
 h.pi.setModel=async()=>true;h.pi.getAllTools=()=>[];await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Original tool/);assert.equal(h.switches.at(-1).kickoff,undefined);
});
test('subsequent tool calls, user prompts and pending work invalidate a saved handoff',async t=>{
 const h=harness(t);await h.start();await h.handoff();const c=await h.call('read',{path:'other'});await c.end();await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Pickup refused/);
 await h.handoff();await h.emit('before_agent_start');await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Pickup refused/);
 h.setPending(true);await assert.rejects(h.handoff(),/pending/);assert.equal(h.switches.length,0);
});
test('a concurrently preflighted sibling prevents handoff and cancellation releases its reservation',async t=>{
 const h=harness(t);await h.start();const worker=await h.call('subagent',{agent:'worker',task:'work'});await assert.rejects(h.handoff(),/pending/);await worker.end();assert.equal(fs.readdirSync(path.join(h.ad,'squad/sessions')).length,0);
});
test('tree navigation discards a ready handoff and compaction re-arms monitoring',async t=>{
 const h=harness(t);await h.start();await h.handoff();await h.emit('session_tree');await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Pickup refused/);h.setUsage({tokens:950,contextWindow:1000});await h.emit('session_compact');assert(h.messages.at(-1).message.content.includes('PROACTIVE HANDOFF'));
});
test('child monitoring returns evidence to parent rather than swapping or nesting',async t=>{
 const old=process.env.PI_CLAUDE_CHILD_DEPTH;process.env.PI_CLAUDE_CHILD_DEPTH='1';t.after(()=>{if(old===undefined)delete process.env.PI_CLAUDE_CHILD_DEPTH;else process.env.PI_CLAUDE_CHILD_DEPTH=old;});
 const h=harness(t);await h.start();h.setUsage({tokens:850,contextWindow:1000});await h.emit('tool_execution_end',{toolCallId:'none'});assert(h.messages[0].message.content.includes('CHILD HANDOFF'));assert.equal(await h.emit('agent_before_settle',{entries:[],outcome:'completed'}),undefined);await assert.rejects(h.handoff(),/parent session/);const c=await h.call('subagent',{agent:'worker',task:'work'});assert(c.out.block);await c.end();
});
test('streaming user input invalidates handoff without before_agent_start',async t=>{
 const h=harness(t);await h.start();await h.handoff();await h.emit('message_start',{message:{role:'user',content:'New requirement during streaming'}});await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Pickup refused/);assert.equal(h.switches.length,0);
});
test('pickup fingerprints consumed user history even if the input event is missed',async t=>{
 const h=harness(t);await h.start();await h.handoff();h.entries.push({type:'message',message:{role:'user',content:'New requirement already consumed'}});await assert.rejects(h.commands.get('squad-pickup').handler('',h.ctx),/Pickup refused/);assert.equal(h.switches.length,0);
});
test('automatic pickup requires successful settlement and never resumes after abort or error',async t=>{
 const h=harness(t);await h.start();h.setUsage({tokens:950,contextWindow:1000});const controller=new AbortController();await h.handoff(controller.signal);const args=h.queued[0].text.split(' ')[1];
 await assert.rejects(h.commands.get('squad-pickup').handler(args,h.ctx),/the run failed/);
 controller.abort();await h.emit('agent_before_settle',{entries:[],outcome:'aborted'});await assert.rejects(h.commands.get('squad-pickup').handler(args,h.ctx),/cancelled/);assert.equal(h.switches.length,0);
 await h.handoff();const next=h.queued.at(-1).text.split(' ')[1];await h.emit('agent_before_settle',{entries:[],outcome:'error'});await assert.rejects(h.commands.get('squad-pickup').handler(next,h.ctx),/cancelled/);assert.equal(h.switches.length,0);
});
test('native RPC CLI completes automatic handoff and replacement with a local fixture provider',async t=>{
 const h=harness(t), extension=path.join(h.root,'native-fixture.ts'), count=path.join(h.root,'requests');
 fs.writeFileSync(path.join(h.ad,'settings.json'),JSON.stringify({defaultProvider:'vigia-fixture',defaultModel:'unit',compaction:{enabled:false},enableInstallTelemetry:false}));
 fs.writeFileSync(extension,`import fs from 'node:fs'; import {createAssistantMessageEventStream} from '@earendil-works/pi-ai'; import {attachVigia} from ${JSON.stringify(path.join(dir,'vigia.ts'))}; export default function(pi){ attachVigia(pi,()=>({})); pi.registerCommand('fixture-set-tools',{handler:async()=>pi.setActiveTools(['squad_handoff'])});pi.registerProvider('vigia-fixture',{baseUrl:'http://127.0.0.1:1',apiKey:'fixture-not-a-secret',api:'openai-completions',models:['unit','selected'].map(id=>({id,name:id,reasoning:true,input:['text'],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:1000000,maxTokens:1024})),streamSimple(model){ const stream=createAssistantMessageEventStream(); const n=fs.existsSync(${JSON.stringify(count)})?Number(fs.readFileSync(${JSON.stringify(count)},'utf8')):0; fs.writeFileSync(${JSON.stringify(count)},String(n+1));fs.appendFileSync(${JSON.stringify(count)}+'.models',model.id+'\\n');fs.appendFileSync(${JSON.stringify(count)}+'.runtime',JSON.stringify({thinking:pi.getThinkingLevel(),tools:pi.getActiveTools()})+'\\n'); const message={role:'assistant',api:'openai-completions',provider:model.provider,model:model.id,timestamp:Date.now(),content:n===0?[{type:'toolCall',id:'fixture-handoff',name:'squad_handoff',arguments:{summary:'Fixture implementation has a verified next step, with no real code modified.',nextStep:'Continue the fixture verification in the replacement session.'}}]:[{type:'text',text:'NATIVE_PICKUP_OK'}],usage:{input:n===0?950000:100,output:10,cacheRead:0,cacheWrite:0,totalTokens:n===0?950010:110,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason:n===0?'toolUse':'stop'}; queueMicrotask(()=>{stream.push({type:'start',partial:message});stream.push({type:'done',reason:message.stopReason,message});stream.end();});return stream;}}); }`);
 const child=spawn(process.execPath,[path.join(base,'dist/cli.js'),'--offline','--no-extensions','-e',extension,'--approve','--mode','rpc'],{cwd:h.cwd,env:{...process.env,PI_CODING_AGENT_DIR:h.ad,PI_CLAUDE_CHILD_DEPTH:'0'},stdio:['pipe','pipe','pipe']});
 t.after(()=>{if(child.exitCode===null)child.kill('SIGTERM');});let out='',stderr='',buffer='',seen=false;
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error('Native RPC pickup timed out: '+stderr+' '+out.slice(-6000)));},20000);child.stderr.setEncoding('utf8');child.stderr.on('data',c=>stderr+=c);child.stdout.setEncoding('utf8');child.stdout.on('data',chunk=>{out+=chunk;buffer+=chunk;let at;while((at=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);let e;try{e=JSON.parse(line);}catch{continue;}if(e.type==='response'&&e.id==='select'){assert.equal(e.success,true);child.stdin.write(JSON.stringify({id:'thinking',type:'set_thinking_level',level:'high'})+'\n');}if(e.type==='response'&&e.id==='thinking'){assert.equal(e.success,true);child.stdin.write(JSON.stringify({id:'tools',type:'prompt',message:'/fixture-set-tools'})+'\n');}if(e.type==='response'&&e.id==='tools'){assert.equal(e.success,true);child.stdin.write(JSON.stringify({type:'prompt',message:'Continue this fixture task.'})+'\n');}if(e.type==='message_end'&&JSON.stringify(e.message?.content).includes('NATIVE_PICKUP_OK'))seen=true;if(seen&&e.type==='agent_settled'){clearTimeout(timer);resolve();}}});child.on('error',e=>{clearTimeout(timer);reject(e);});child.on('exit',code=>{clearTimeout(timer);if(!seen)reject(new Error('Native RPC exited '+code+': '+stderr+' '+out.slice(-4000)));});child.stdin.write(JSON.stringify({id:'select',type:'set_model',provider:'vigia-fixture',modelId:'selected'})+'\n');});
 const closed=new Promise(resolve=>child.once('close',resolve));child.kill('SIGTERM');await closed;
 assert(out.includes('NATIVE_PICKUP_OK'),out.split('\n').filter(line=>!line.includes('"type":"agent_end"')).join('\n').slice(-8000));assert.equal(fs.readFileSync(count,'utf8'),'2');assert.equal(fs.readFileSync(count+'.models','utf8'),'selected\nselected\n');assert.deepEqual(fs.readFileSync(count+'.runtime','utf8').trim().split('\n').map(JSON.parse),[{thinking:'high',tools:['squad_handoff']},{thinking:'high',tools:['squad_handoff']}]);
 const sessions=fs.readdirSync(path.join(h.ad,'sessions')).flatMap(d=>fs.readdirSync(path.join(h.ad,'sessions',d)).filter(f=>f.endsWith('.jsonl')));assert.equal(sessions.length,2,out.slice(-12000));
});
async function cacheIdle(h, {cache=true, payload={model:'selected'}, outcome='completed'}={}) {
 h.ctx.model.promptCache={short:300,long:3600};h.setUsage({tokens:200000,contextWindow:1000000});h.setIdle(false);
 await h.emit('agent_start');await h.emit('before_provider_request',{payload});
 await h.emit('message_end',{message:{role:'assistant',provider:'fixture',model:'selected',stopReason:outcome==='completed'?'stop':outcome,usage:{cacheRead:cache?200000:0,cacheWrite:0}}});
 await h.emit('agent_before_settle',{entries:[],outcome});h.setIdle(true);await h.emit('agent_settled');
}
function fakeClock(t){t.mock.timers.enable({apis:['Date','setTimeout'],now:new Date('2026-10-19T12:00:00Z')});}
test('pre-cache TTL uses request/catalog evidence and never invents unknown lifetimes',()=>{
 assert.deepEqual(v.preCacheTtl({},{}),undefined);assert.deepEqual(v.preCacheTtl({promptCache:{short:300,long:3600}},{}),{ms:300000,source:'model.promptCache conservative minimum'});
 assert.equal(v.preCacheTtl({promptCache:{short:300}},{system:[{cache_control:{type:'ephemeral',ttl:'1h'}}]}).ms,3600000);
 assert.equal(v.preCacheTtl({},{messages:[{content:[{cache_control:{type:'ephemeral'}}]}]}).ms,300000);
 assert.equal(v.preCacheTtl({},{prompt_cache_options:{ttl:'30m'}}).ms,1800000);assert.equal(v.preCacheTtl({},{prompt_cache_retention:'24h'}).ms,86400000);
 assert.equal(v.preCacheTtl({promptCache:{short:300}},{cacheRetention:'none'}),undefined);assert.equal(v.preCacheTtl({promptCache:{short:300}},{cache_control:{type:'ephemeral',ttl:'unknown'}}),undefined);
 assert.equal(v.preCacheTtl({}, {messages:[{content:[{type:'tool_use',input:{cache_control:{type:'ephemeral',ttl:'1h'}}}]}]}),undefined);
 assert.equal(v.preCacheTtl({}, {metadata:{cache_control:{type:'ephemeral',ttl:'1h'}}}),undefined);
 assert.equal(v.preCacheTtl({promptCache:{short:NaN,long:-1}},{}),undefined);
 assert.equal(v.preCacheTtl({promptCache:{long:3600}},{}),undefined);
 assert.equal(v.preCacheTtl({promptCache:{short:300}},{prompt_cache_options:{ttl:'unknown'}}),undefined);
 assert.equal(v.preCacheTtl({promptCache:{short:300}},{prompt_cache_retention:'unknown'}),undefined);assert.equal(v.vigiaConfig({preCache:{minTokens:0,beforeSeconds:NaN}}).preCache.minTokens,150000);
});
test('pre-cache refuses cache TTL attribution to a provider fallback model',async t=>{
 fakeClock(t);const h=harness(t);await h.start();h.ctx.model.promptCache={short:300};h.setUsage({tokens:200000,contextWindow:1000000});await h.emit('agent_start');await h.emit('before_provider_request',{payload:{model:'selected'}});await h.emit('message_end',{message:{role:'assistant',provider:'fixture',model:'selected',responseModel:'different-upstream',stopReason:'stop',usage:{cacheRead:200000}}});await h.emit('agent_before_settle',{entries:[],outcome:'completed'});h.setIdle(true);await h.emit('agent_settled');t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
});
test('pre-cache fires once 120 seconds before expiry through native compact with preservation instructions',async t=>{
 fakeClock(t);const h=harness(t);await h.start();await cacheIdle(h);t.mock.timers.tick(179999);assert.equal(h.compactions.length,0);t.mock.timers.tick(1);assert.equal(h.compactions.length,1);
 const options=h.compactions[0];for(const term of ["owner's latest request",'AgenFK','branch/worktree/PR','decisions','completed/remaining work','live tasks'])assert(options.customInstructions.includes(term));
 assert.equal(await h.emit('session_before_compact',{customInstructions:options.customInstructions}),undefined);
 await h.emit('session_compact');options.onComplete({});t.mock.timers.tick(3600000);assert.equal(h.compactions.length,1);assert.equal(h.queued.length,0);
 assert(h.entries.some(e=>e.customType==='squad-precache-v1'&&e.data.state==='completed'));
});
test('pre-cache never compacts without cache confirmation, known TTL or successful settlement',async t=>{
 fakeClock(t);const h=harness(t);await h.start();await cacheIdle(h,{cache:false});t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
 await cacheIdle(h,{payload:{cache_control:{type:'ephemeral',ttl:'unknown'}}});t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
 await cacheIdle(h,{outcome:'aborted'});t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
});
for(const [name,action] of [
 ['input',async h=>h.emit('input')],['steering',async h=>h.emit('message_start',{message:{role:'user'}})],
 ['model switch',async h=>h.emit('model_select')],['branch navigation',async h=>h.emit('session_before_tree')],
 ['session replacement',async h=>h.emit('session_before_switch')],['reload',async h=>{await h.emit('session_shutdown');await h.start();}],
 ['UI dialog',async h=>h.emit('ui_prompt_start')],['shell',async h=>h.emit('user_bash')],
 ['tool',async h=>h.emit('tool_execution_start',{toolCallId:'active'})],['queued message',async h=>h.setPending(true)],
 ['busy session',async h=>h.setIdle(false)],['lost trust',async h=>h.ctx.isProjectTrusted=()=>false],
 ['handoff threshold',async h=>h.setUsage({tokens:950000,contextWindow:1000000})],
 ['native compaction',async h=>h.emit('session_before_compact',{customInstructions:'owner manual compaction'})],
 ['context edit',async h=>h.pi.appendEntry('external-context-change',{})],
]) test('pre-cache cancels or rechecks '+name+' before spending',async t=>{
 fakeClock(t);const h=harness(t);await h.start();await cacheIdle(h);await action(h);t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
});
test('pre-cache skips late timers and never retries a native failure',async t=>{
 fakeClock(t);const h=harness(t);await h.start();await cacheIdle(h);t.mock.timers.tick(300001);assert.equal(h.compactions.length,0);
 await cacheIdle(h);t.mock.timers.tick(180000);assert.equal(h.compactions.length,1);h.compactions[0].onError(new Error('fixture secret must not be logged'));
 await h.emit('agent_settled');t.mock.timers.tick(3600000);assert.equal(h.compactions.length,1);assert(!JSON.stringify(h.entries).includes('fixture secret'));
});
test('pre-cache respects native auto-compaction disabled and explicit supervisor opt-out',async t=>{
 fakeClock(t);const raw={};const h=harness(t,raw);await h.start();fs.writeFileSync(path.join(h.ad,'settings.json'),JSON.stringify({compaction:{enabled:false}}));await cacheIdle(h);t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
 fs.writeFileSync(path.join(h.ad,'settings.json'),'{}');raw.preCache={enabled:false};await cacheIdle(h);t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
 raw.preCache={enabled:true};h.ctx.mode='json';await cacheIdle(h);t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
});
test('pre-cache yields to warming, and rechecks own native dispatch for late activity',async t=>{
 fakeClock(t);const h=harness(t);await h.start();await cacheIdle(h);assert.equal(await h.emit('cache_warming_decision',{action:'warm'}),undefined);t.mock.timers.tick(180000);assert.equal(h.compactions.length,0);
 await cacheIdle(h);t.mock.timers.tick(180000);assert.equal(h.compactions.length,1);assert.deepEqual(await h.emit('cache_warming_decision',{action:'warm'}),{action:'stop'});
 await h.emit('input');assert.deepEqual(await h.emit('session_before_compact',{customInstructions:h.compactions[0].customInstructions}),{cancel:true});
});
test('native RPC idle timer performs a real compaction using only a local fixture provider',async t=>{
 const h=harness(t), extension=path.join(h.root,'precache-fixture.ts'), count=path.join(h.root,'precache-requests');
 fs.writeFileSync(path.join(h.ad,'settings.json'),JSON.stringify({defaultProvider:'precache-fixture',defaultModel:'unit',compaction:{enabled:true,keepRecentTokens:0,reserveTokens:1024},cacheWarming:'off',enableInstallTelemetry:false}));
 fs.writeFileSync(extension,`import fs from 'node:fs';import {createAssistantMessageEventStream} from '@earendil-works/pi-ai';import {attachVigia} from ${JSON.stringify(path.join(dir,'vigia.ts'))};export default function(pi){attachVigia(pi,()=>({preCache:{minTokens:1,beforeSeconds:1}}));pi.registerProvider('precache-fixture',{baseUrl:'http://127.0.0.1:1',apiKey:'fixture-not-secret',api:'openai-completions',models:[{id:'unit',name:'Unit',reasoning:false,input:['text'],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:1000000,maxTokens:2048,promptCache:{short:3}}],streamSimple(model,context,options){const stream=createAssistantMessageEventStream();const n=fs.existsSync(${JSON.stringify(count)})?Number(fs.readFileSync(${JSON.stringify(count)},'utf8')):0;fs.writeFileSync(${JSON.stringify(count)},String(n+1));const message={role:'assistant',api:'openai-completions',provider:model.provider,model:model.id,timestamp:Date.now(),content:[{type:'text',text:n===0?'FIXTURE_WORK_DONE':'## Goal\\nPreserve fixture task.\\n## Progress\\nFixture work finished.\\n## Next Steps\\nWait for owner.'}],usage:{input:10,output:20,cacheRead:200000,cacheWrite:0,totalTokens:200030,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}},stopReason:'stop'};queueMicrotask(async()=>{await options?.onPayload?.({model:model.id},model);stream.push({type:'start',partial:message});stream.push({type:'done',reason:'stop',message});stream.end();});return stream;}});}`);
 const child=spawn(process.execPath,[path.join(base,'dist/cli.js'),'--offline','--no-extensions','-e',extension,'--approve','--mode','rpc'],{cwd:h.cwd,env:{...process.env,PI_CODING_AGENT_DIR:h.ad,PI_CLAUDE_CHILD_DEPTH:'0'},stdio:['pipe','pipe','pipe']});t.after(()=>{if(child.exitCode===null)child.kill('SIGTERM');});
 let out='',buffer='',stderr='';await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{child.kill('SIGTERM');reject(new Error('Precache RPC timeout: '+stderr+' '+out.slice(-6000)));},15000);child.stderr.setEncoding('utf8');child.stderr.on('data',c=>stderr+=c);child.stdout.setEncoding('utf8');child.stdout.on('data',c=>{out+=c;buffer+=c;let at;while((at=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);let e;try{e=JSON.parse(line);}catch{continue;}if(e.type==='compaction_end'){clearTimeout(timer);if(!e.result||e.aborted||e.errorMessage)reject(new Error(JSON.stringify(e)));else resolve();}}});child.on('error',reject);child.stdin.write(JSON.stringify({type:'prompt',message:'Carry out the fixture task and preserve the next step.'})+'\n');});
 await new Promise(resolve=>setTimeout(resolve,100));const closed=new Promise(resolve=>child.once('close',resolve));child.kill('SIGTERM');await closed;
 // Native split-turn compaction may make separate history and turn-prefix summaries.
 assert([2,3].includes(Number(fs.readFileSync(count,'utf8'))));
 const files=fs.readdirSync(path.join(h.ad,'sessions')).flatMap(d=>fs.readdirSync(path.join(h.ad,'sessions',d)).filter(f=>f.endsWith('.jsonl')).map(f=>path.join(h.ad,'sessions',d,f)));assert.equal(files.length,1);const entries=fs.readFileSync(files[0],'utf8').trim().split('\n').map(JSON.parse);
 assert.equal(entries.filter(e=>e.type==='compaction').length,1);assert.equal(entries.filter(e=>e.type==='custom'&&e.customType==='squad-precache-v1'&&e.data.state==='started').length,1);assert(entries.some(e=>e.type==='custom'&&e.customType==='squad-precache-v1'&&e.data.state==='completed'));assert.equal(entries.filter(e=>e.type==='message'&&e.message.role==='user').length,1);
});
test('native Pi loader registers the vigia lifecycle, tools and commands',async()=>{
 const {loadExtensions}=await import(path.join(base,'dist/core/extensions/loader.js'));const out=await loadExtensions([path.join(dir,'index.ts')],'/tmp');assert.deepEqual(out.errors,[]);const ext=out.extensions[0];assert(ext.commands.has('squad-status'));assert(ext.commands.has('squad-pickup'));assert(ext.tools.has('squad_handoff'));assert(ext.handlers.has('agent_before_settle'));
});
