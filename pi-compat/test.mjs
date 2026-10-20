import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import http from 'node:http';
const base = process.env.PI_COMPAT_PI_ROOT;
if (!base) throw new Error('Set PI_COMPAT_PI_ROOT to the installed Pi package directory.');
const req = createRequire(path.join(base, 'package.json'));
const { createJiti } = req('jiti');
const jiti = createJiti(import.meta.url, { alias: {
  '@earendil-works/pi-coding-agent': path.join(base, 'dist/index.js'),
  '@earendil-works/pi-ai': path.join(base, 'node_modules/@earendil-works/pi-ai/dist/index.js'),
  'typebox': path.join(base, 'node_modules/typebox/build/index.mjs'),
} });
const dir = path.dirname(fileURLToPath(import.meta.url));
const r = await jiti.import(path.join(dir, 'resources.ts'));
const rt = await jiti.import(path.join(dir, 'runtime.ts'));
const ix = await jiti.import(path.join(dir, 'index.ts'));
const routing = await jiti.import(path.join(dir, 'routing.ts'));
function fixture(t) { const root=fs.mkdtempSync(path.join(os.tmpdir(),'pi-compat-test-')); t.after(()=>fs.rmSync(root,{recursive:true,force:true})); return root; }
function write(file, value) { fs.mkdirSync(path.dirname(file),{recursive:true}); fs.writeFileSync(file,typeof value==='string'?value:JSON.stringify(value)); }
function skill(file, name='example') { write(file,`---\nname: ${name}\ndescription: Example capability\n---\nRead references/example.md and ${'${CLAUDE_PLUGIN_ROOT}'}/scripts/run.py.\n`); }
function setup(t) {
 const root=fixture(t), home=path.join(root,'home'), cwd=path.join(root,'project'), plugin=path.join(root,'plugin');
 fs.mkdirSync(cwd,{recursive:true}); fs.mkdirSync(home,{recursive:true});
 write(path.join(home,'.claude/settings.json'),{enabledPlugins:{'sample@market':true,'disabled@market':false}});
 write(path.join(home,'.claude/plugins/installed_plugins.json'),{plugins:{'sample@market':[{scope:'user',installPath:plugin}]}});
 skill(path.join(plugin,'skills/example/SKILL.md')); write(path.join(plugin,'commands/review.md'),'---\ndescription: Review safely\n---\nReview $ARGUMENTS in ${CLAUDE_PLUGIN_ROOT}.');
 write(path.join(home,'.claude/agents/reviewer.md'),'---\nname: reviewer\ndescription: Review code\ntools: [Read, Grep, Bash]\nmodel: sonnet\n---\nReview without writing.');
 write(path.join(plugin,'.mcp.json'),{mcpServers:{sample:{command:'node',args:['${CLAUDE_PLUGIN_ROOT}/server.js'],env:{TOKEN:'private-fixture-value'}}}});
 return {root,home,cwd,plugin};
}
test('imports skills, namespaced commands and symlinked global agents',t=>{
 const f=setup(t); const agent=path.join(f.home,'.claude/agents/reviewer.md'); fs.renameSync(agent,agent+'.source'); fs.symlinkSync(agent+'.source',agent);
 const i=r.discover(f.cwd,true,f.home); assert.equal(i.resources.filter(x=>x.kind==='skill').length,1); assert(i.resources.some(x=>x.name==='sample:review')); assert.deepEqual(i.resources.find(x=>x.name==='reviewer').tools,['Read','Grep','Bash']);
});
test('standalone swarm source works with no Claude installation or configuration',t=>{
 const f=setup(t), swarm=path.join(f.root,'swarm'); fs.rmSync(path.join(f.home,'.claude'),{recursive:true,force:true});
 write(path.join(swarm,'agents/worker.md'),'---\nname: worker\ndescription: Native swarm worker\nmodel: sonnet\n---\nFollow project rules.'); skill(path.join(swarm,'skills/work/SKILL.md'),'work'); write(path.join(swarm,'CLAUDE.md'),'Swarm dispatch rules');
 const i=r.discover(f.cwd,true,f.home,swarm); assert(i.resources.some(x=>x.kind==='agent'&&x.name==='worker')); assert(i.resources.some(x=>x.kind==='skill'&&x.name==='work')); assert.deepEqual(i.guidance,[path.join(swarm,'CLAUDE.md')]);
});
test('standalone swarm preserves distinct user skills, agents and guidance',t=>{
 const f=setup(t), swarm=path.join(f.root,'swarm'); write(path.join(f.home,'.claude/CLAUDE.md'),'Independent user rules'); skill(path.join(f.home,'.claude/skills/work/SKILL.md'),'work');
 write(path.join(swarm,'agents/reviewer.md'),'---\nname: reviewer\ndescription: Packaged reviewer\n---\nSwarm instructions.'); skill(path.join(swarm,'skills/work/SKILL.md'),'work'); write(path.join(swarm,'CLAUDE.md'),'Packaged defaults');
 const i=r.discover(f.cwd,true,f.home,swarm); assert(i.resources.some(x=>x.name==='user-work')); assert(i.resources.some(x=>x.name==='swarm-work')); assert(i.resources.some(x=>x.name==='user-reviewer')); assert(i.resources.some(x=>x.name==='reviewer')); assert.equal(i.guidance.length,2);
});
test('three colliding swarm/user agent names retain all physical sources',t=>{
 const f=setup(t), swarm=path.join(f.root,'swarm'); write(path.join(f.home,'.claude/agents/user-reviewer.md'),'---\nname: user-reviewer\ndescription: Explicit user alias\n---\nIndependent role.'); write(path.join(swarm,'agents/reviewer.md'),'---\nname: reviewer\ndescription: Packaged role\n---\nSwarm role.');
 const agents=r.discover(f.cwd,true,f.home,swarm).resources.filter(x=>x.kind==='agent'); assert.equal(agents.length,3); assert.equal(new Set(agents.map(x=>x.name)).size,3); assert(agents.some(x=>x.name==='user-reviewer'&&x.description==='Explicit user alias')); assert(agents.some(x=>x.name==='reviewer'&&x.description==='Packaged role'));
});
test('project agent precedence keeps the displaced default available under an alias',t=>{
 const f=setup(t); write(path.join(f.cwd,'.claude/agents/reviewer.md'),'---\nname: reviewer\ndescription: Project specialist\n---\nProject rules.'); const agents=r.discover(f.cwd,true,f.home).resources.filter(x=>x.kind==='agent'); assert.equal(agents.length,2); assert.equal(agents.find(x=>x.name==='reviewer').description,'Project specialist');
});
test('untrusted project settings, skills and agents never load',t=>{
 const f=setup(t); skill(path.join(f.cwd,'.claude/skills/local/SKILL.md'),'local'); write(path.join(f.cwd,'.claude/settings.json'),{enabledPlugins:{'sample@market':false}});
 const i=r.discover(f.cwd,false,f.home); assert(!i.resources.some(x=>x.name==='local')); assert(i.resources.some(x=>x.name==='example'));
});
test('trusted project can disable a global plugin',t=>{
 const f=setup(t); write(path.join(f.cwd,'.claude/settings.local.json'),{enabledPlugins:{'sample@market':false}});
 assert(!r.discover(f.cwd,true,f.home).resources.some(x=>x.name==='sample:review'));
});
test('project-specific version overrides user version, without loading both',t=>{
 const f=setup(t), local=path.join(f.root,'new-plugin'); skill(path.join(local,'skills/new/SKILL.md'),'new');
 write(path.join(f.home,'.claude/plugins/installed_plugins.json'),{plugins:{'sample@market':[{scope:'user',installPath:f.plugin},{scope:'project',projectPath:f.cwd,installPath:local}]}});
 const i=r.discover(f.cwd,true,f.home); assert(i.resources.some(x=>x.name==='new')); assert(!i.resources.some(x=>x.name==='example'));
});
test('a sibling project does not inherit another project plugin installation',t=>{
 const f=setup(t); write(path.join(f.home,'.claude/plugins/installed_plugins.json'),{plugins:{'sample@market':[{scope:'project',projectPath:path.join(f.root,'other'),installPath:f.plugin}]}});
 assert.equal(r.discover(f.cwd,true,f.home).plugins[0].root,undefined);
});
test('walk follows shared skill symlinks but terminates cycles and skips inactive copies',t=>{
 const root=fixture(t); skill(path.join(root,'live/SKILL.md')); skill(path.join(root,'inactive-skills/old/SKILL.md'),'old'); fs.symlinkSync(root,path.join(root,'live/cycle'));
 assert.equal(r.walk(root,'SKILL.md').length,1);
});
test('native Agent Skills mirrors are not duplicated',t=>{
 const f=setup(t), native=path.join(f.home,'.agents/skills/example/SKILL.md'); fs.mkdirSync(path.dirname(native),{recursive:true}); fs.symlinkSync(path.join(f.plugin,'skills/example/SKILL.md'),native); assert(!r.discover(f.cwd,true,f.home).resources.some(x=>x.kind==='skill'&&x.name==='example'));
});
test('unquoted colon descriptions get private normalized copies, source is unchanged',t=>{
 const f=setup(t), source=path.join(f.plugin,'skills/example/SKILL.md'); const original='---\nname: example\ndescription: Use for CAD: printable models\n---\nUse references/tool.md.\n'; write(source,original);
 const i=r.discover(f.cwd,true,f.home); const files=ix.generateSkills(i,f.cwd,path.join(f.root,'cache'));
 assert.equal(files.length,1); assert.equal(fs.readFileSync(source,'utf8'),original); const parsed=r.frontmatter(fs.readFileSync(files[0],'utf8')); assert.equal(parsed.frontmatter.description,'Use for CAD: printable models'); assert(parsed.body.includes(path.dirname(source)));
});
test('generated prompts preserve arguments and original plugin-relative paths',t=>{
 const f=setup(t), i=r.discover(f.cwd,true,f.home); const [file]=ix.generatePrompts(i,f.cwd,path.join(f.root,'cache')); const text=fs.readFileSync(file,'utf8'); assert(file.endsWith('sample:review.md')); assert(text.includes('$ARGUMENTS')); assert(text.includes(f.plugin)); assert(!text.includes('${CLAUDE_PLUGIN_ROOT}'));
});
test('public catalog cannot serialize MCP credentials',t=>{
 const f=setup(t); assert(!JSON.stringify(r.publicInventory(r.discover(f.cwd,true,f.home))).includes('private-fixture-value'));
});
test('host MCP config stays lazy and roots are expanded',t=>{
 const f=setup(t); write(path.join(f.home,'.claude.json'),{mcpServers:{host:{url:'https://example.invalid/mcp'}}}); const i=r.discover(f.cwd,true,f.home);
 assert(i.servers.some(x=>x.name==='host')); assert.equal(i.servers.find(x=>x.name==='sample__sample').definition.args[0],f.plugin+'/server.js');
});
test('distinct project skills are retained when a native skill has the same name',t=>{
 const f=setup(t); skill(path.join(f.home,'.agents/skills/local/SKILL.md'),'local'); skill(path.join(f.cwd,'.claude/skills/local/SKILL.md'),'local'); fs.appendFileSync(path.join(f.cwd,'.claude/skills/local/SKILL.md'),'Distinct project instructions.');
 assert(r.discover(f.cwd,true,f.home).resources.some(x=>x.name==='claude-local'));
});
test('colliding plugin skills and MCP servers retain qualified identities',t=>{
 const f=setup(t), second=path.join(f.root,'second'); skill(path.join(second,'skills/example/SKILL.md'));
 write(path.join(second,'.mcp.json'),{mcpServers:{sample:{command:'node',args:['second.js']}}});
 write(path.join(f.home,'.claude/settings.json'),{enabledPlugins:{'sample@market':true,'second@market':true}});
 write(path.join(f.home,'.claude/plugins/installed_plugins.json'),{plugins:{'sample@market':[{scope:'user',installPath:f.plugin}],'second@market':[{scope:'user',installPath:second}]}});
 const i=r.discover(f.cwd,true,f.home); assert(i.resources.some(x=>x.name==='sample-example')); assert(i.resources.some(x=>x.name==='second-example')); assert.deepEqual(i.servers.map(x=>x.name),['sample__sample','second__sample']);
});
test('identical Markdown with distinct dependency directories is not treated as a mirror',t=>{
 const f=setup(t); skill(path.join(f.home,'.agents/skills/example/SKILL.md')); write(path.join(f.home,'.agents/skills/example/scripts/run.py'),'native script'); write(path.join(f.plugin,'skills/example/scripts/run.py'),'different plugin script');
 assert(r.discover(f.cwd,true,f.home).resources.some(x=>x.name==='sample-example'));
});
test('native collisions do not erase colliding plugin skills after qualification',t=>{
 const f=setup(t), second=path.join(f.root,'second'); skill(path.join(second,'skills/example/SKILL.md')); skill(path.join(f.home,'.agents/skills/example/SKILL.md'));
 write(path.join(f.home,'.claude/settings.json'),{enabledPlugins:{'sample@market':true,'second@market':true}}); write(path.join(f.home,'.claude/plugins/installed_plugins.json'),{plugins:{'sample@market':[{scope:'user',installPath:f.plugin}],'second@market':[{scope:'user',installPath:second}]}});
 const i=r.discover(f.cwd,true,f.home); assert(i.resources.some(x=>x.name==='sample-example')); assert(i.resources.some(x=>x.name==='second-example'));
});
test('project MCP files load only in trusted contexts and override host definitions',t=>{
 const f=setup(t); write(path.join(f.home,'.claude.json'),{mcpServers:{project:{url:'https://host.invalid'}}}); write(path.join(f.cwd,'.mcp.json'),{mcpServers:{project:{url:'https://project.invalid'}}});
 assert.equal(r.discover(f.cwd,true,f.home).servers.find(x=>x.name==='project').definition.url,'https://project.invalid'); assert.equal(r.discover(f.cwd,false,f.home).servers.find(x=>x.name==='project').definition.url,'https://host.invalid');
});
test('agent deny lists remove named, patterned and wildcard tools',()=>{
 assert.deepEqual(rt.agentTools({deniedTools:['Write','Bash(git *)','mcp__*']},['read','write','bash','mcp__github']).permitted,['read']);
});
test('native runtime forwarding preserves CLI-only permission extensions',()=>{
 const entry=path.join(base,'dist/bundle/cli.js'); const runtime=rt.nativeRuntime(['node',entry,'--no-extensions','-e','/guard.ts','--model','example/model','--','task']);
 assert.deepEqual(runtime.prefix,[entry,'--no-extensions','-e','/guard.ts']); assert.throws(()=>rt.nativeRuntime(['node',process.execPath]),/native Pi CLI/);
});
test('extension-defined backend flags are inherited, unknown flags fail closed',()=>{
 const entry=path.join(base,'dist/bundle/cli.js'); const args=['node',entry,'-e','ssh.ts','--ssh','user@host','--guard-enabled'];
 const runtime=rt.nativeRuntime(args,n=>n==='ssh'?'user@host':n==='guard-enabled'?true:undefined); assert.deepEqual(runtime.prefix,[entry,'-e','ssh.ts','--ssh','user@host','--guard-enabled']);
 assert.throws(()=>rt.nativeRuntime(['node',entry,'--unknown-backend','remote']),/unknown runtime flag/);
 assert.throws(()=>rt.nativeRuntime(['node',entry,'--api-key','private-fixture-value']),/Ephemeral CLI credentials/);
});
test('agent tools are the intersection, never widened for missing tools',()=>{
 const x=rt.agentTools({tools:['Read','WebSearch','Task']},['read','write','bash','subagent']); assert.deepEqual(x.permitted,['read']); assert.deepEqual(x.missing,['web_search']);
});
test('agents without a tool list still cannot delegate recursively',()=>{
 assert.deepEqual(rt.agentTools({},['read','subagent']).permitted,['read']);
});
test('agent dispatch rejects untrusted projects and unsupported execution controls',async t=>{
 const cwd=fixture(t); await assert.rejects(rt.runAgent({unsupported:[]},'task',{cwd,trusted:false}),/Trust/);
 await assert.rejects(rt.runAgent({name:'unsafe',unsupported:['isolation']},'task',{cwd,trusted:true}),/unsupported execution controls/);
});
test('agent process inherits selected provider/model and returns real usage',async t=>{
 const f=setup(t), bin=path.join(f.root,'bin'); fs.mkdirSync(bin); const fake=path.join(bin,'pi');
 write(fake,`#!${process.execPath}\nconsole.log(JSON.stringify({type:'message_end',message:{role:'assistant',content:[{type:'text',text:JSON.stringify({args:process.argv.slice(2),depth:process.env.PI_CLAUDE_CHILD_DEPTH})}],usage:{input:2,output:3,totalTokens:5,cost:{total:0.01}},stopReason:'stop'}}));\n`); fs.chmodSync(fake,0o700);
 const old=process.env.PATH; process.env.PATH=bin+path.delimiter+old;
 try { const a=r.discover(f.cwd,true,f.home).resources.find(x=>x.name==='reviewer'); const out=await rt.runAgent(a,'--malicious-flag',{cwd:f.cwd,trusted:true,model:'example/model',thinking:'low',tools:['read','grep','bash'],runtime:{command:'pi',prefix:[]}});
 const child=JSON.parse(out.answer); assert(child.args.includes('example/model')); assert(!child.args.includes('sonnet')); assert.equal(child.depth,'1'); assert.equal(out.usage.totalTokens,5); assert(child.args.at(-1).startsWith('Delegated task:')); }
 finally { process.env.PATH=old; }
});
test('process failures and cancellation propagate',async t=>{
 const cwd=fixture(t); const out=await rt.runProcess(process.execPath,['-e','process.exit(7)'],{cwd}); assert.equal(out.code,7);
 const control=new AbortController(); const run=rt.runProcess(process.execPath,['-e','setInterval(()=>{},1000)'],{cwd,signal:control.signal}); setTimeout(()=>control.abort(),30); await assert.rejects(run,/Cancelled/);
});
test('process deadlines terminate the child',async t=>{
 await assert.rejects(rt.runProcess(process.execPath,['-e','setInterval(()=>{},1000)'],{cwd:fixture(t),timeout:30}),/deadline/);
});
test('Pi tool inputs become Claude hook inputs without losing edit arrays',()=>{
 const x=rt.hookPayload('edit',{path:'file.ts',edits:[{oldText:'a',newText:'b'}]}); assert.equal(x.tool_name,'Edit'); assert.equal(x.tool_input.file_path,'file.ts'); assert.equal(x.tool_input.old_string,'a'); assert.equal(x.tool_input.edits.length,1);
});
test('safety hooks are selected narrowly, async hooks never auto-enable',()=>{
 assert(ix.portableSafetyHook({event:'PreToolUse',unsupported:[],command:'$HOME/.claude/hooks/bash-guard.sh'}));
 assert(ix.portableSafetyHook({event:'PreToolUse',unsupported:[],command:'bash "${CLAUDE_PROJECT_DIR:-.}/scripts/setup/agenfk-lock.sh" pre-tool'}));
 assert(!ix.portableSafetyHook({event:'SessionStart',unsupported:[],command:'install-paid-sdk'}));
 assert(!ix.portableSafetyHook({event:'PreToolUse',unsupported:['async'],command:'$HOME/.claude/hooks/bash-guard.sh'}));
});
test('safety hooks reject shell prefixes, comments and compound suffix spoofing',()=>{
 for(const command of ['arbitrary-command # .claude/hooks/bash-guard.sh','evil; $HOME/.claude/hooks/bash-guard.sh','$HOME/.claude/hooks/bash-guard.sh; evil']) assert(!ix.portableSafetyHook({event:'PreToolUse',unsupported:[],command}));
});
test('oversized or malformed hook JSON fails closed',async t=>{
 const cwd=fixture(t);
 await assert.rejects(rt.runHook({command:`${process.execPath} -e 'console.log(JSON.stringify({padding:"x".repeat(60000),hookSpecificOutput:{permissionDecision:"deny"}}))'`,unsupported:[],timeout:2},{},cwd),/byte limit/);
 await assert.rejects(rt.runHook({command:`printf '{broken-json'`,unsupported:[],timeout:2},{},cwd),/Malformed hook JSON/);
});
test('hook matching is anchored and invalid patterns fail safely',()=>{
 assert(rt.hookMatches({matcher:'Bash|Read'},'Bash')); assert(!rt.hookMatches({matcher:'Bash'},'NotBash')); assert(!rt.hookMatches({matcher:'['},'Bash'));
});
test('hook execution forwards JSON payload and structured deny',async t=>{
 const cwd=fixture(t), h={command:`${process.execPath} -e 'process.stdin.resume();process.stdin.on("end",()=>console.log(JSON.stringify({hookSpecificOutput:{permissionDecision:"deny"}})))'`,unsupported:[],timeout:2};
 const out=await rt.runHook(h,{tool_name:'Bash'},cwd); assert.equal(out.data.hookSpecificOutput.permissionDecision,'deny');
 await assert.rejects(rt.runHook({...h,unsupported:['async']},{},cwd),/Unsupported/);
});
test('LSP rejects a realpath outside the current worktree',async t=>{
 const root=fixture(t), cwd=path.join(root,'tree'); fs.mkdirSync(cwd); write(path.join(root,'outside.ts'),'export const x=1'); fs.symlinkSync(path.join(root,'outside.ts'),path.join(cwd,'escape.ts'));
 await assert.rejects(rt.lspRequest({definition:{command:'none'}},'escape.ts','hover',0,0,cwd),/inside/);
});
test('LSP framed initialization, didOpen and request work end to end',async t=>{
 const cwd=fixture(t); write(path.join(cwd,'test.ts'),'export const value = 1;'); const server=path.join(cwd,'server.cjs');
 write(server,`let b=Buffer.alloc(0),opened=false; process.stdin.on('data',d=>{b=Buffer.concat([b,d]);while(true){const h=b.indexOf('\\r\\n\\r\\n');if(h<0)return;const n=Number(/Content-Length:\\s*(\\d+)/i.exec(b.subarray(0,h).toString())[1]);if(b.length<h+4+n)return;const m=JSON.parse(b.subarray(h+4,h+4+n));b=b.subarray(h+4+n);if(m.method==='textDocument/didOpen')opened=true;if(m.id){const s=JSON.stringify({jsonrpc:'2.0',id:m.id,result:m.id===1?{capabilities:{}}:{opened,method:m.method}});process.stdout.write('Content-Length: '+Buffer.byteLength(s)+'\\r\\n\\r\\n'+s);}}});`);
 const out=await rt.lspRequest({definition:{command:process.execPath,args:[server]}},'test.ts','hover',0,0,cwd); assert.deepEqual(out,{opened:true,method:'textDocument/hover'});
});
test('web fetch is real, bounded and rejects credentials/non-HTTP schemes',async t=>{
 const server=http.createServer((_req,res)=>{res.setHeader('content-type','text/plain');res.end('fixture-web-response');}); await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve)); t.after(()=>server.close());
 assert.equal(await ix.fetchText(`http://127.0.0.1:${server.address().port}/`),'fixture-web-response'); await assert.rejects(ix.fetchText('file:///etc/passwd'),/HTTP/); await assert.rejects(ix.fetchText('https://user:secret@example.invalid/'),/credentials/);
});
test('search results preserve actual source URLs, titles and snippets',()=>{
 assert.deepEqual(ix.searchResults('<rss><item><title>A &amp; B</title><link>https://example.invalid/a</link><description>Real snippet</description></item></rss>'),[{title:'A & B',url:'https://example.invalid/a',snippet:'Real snippet'}]); assert.deepEqual(ix.searchResults('<html>blocked</html>'),[]);
});
test('worktrees inherit canonical project plugin settings only when trusted',t=>{
 const f=setup(t), main=path.join(f.root,'git-main'), work=path.join(f.root,'git-work'); fs.mkdirSync(main);
 const git=(...args)=>execFileSync('git',args,{cwd:main,stdio:'ignore'});
 git('init'); git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture'); git('worktree','add','-b','fixture',work);
 write(path.join(main,'.claude/settings.json'),{enabledPlugins:{'sample@market':false}});
 assert(!r.discover(work,true,f.home).resources.some(x=>x.name==='sample:review')); assert(r.discover(work,false,f.home).resources.some(x=>x.name==='sample:review'));
});
test('installer backs up the old bridge and leaves Claude sources untouched',t=>{
 const root=fixture(t), agentDir=path.join(root,'agent'); write(path.join(agentDir,'extensions/claude-skills.ts'),'original bridge');
 execFileSync('bash',[path.join(dir,'install.sh')],{env:{...process.env,PI_CODING_AGENT_DIR:agentDir},stdio:'pipe'});
 assert(fs.readFileSync(path.join(agentDir,'extensions/claude-skills.ts'),'utf8').includes(path.join(dir,'index.ts')));
 const backup=fs.readdirSync(path.join(agentDir,'backups'))[0]; assert.equal(fs.readFileSync(path.join(agentDir,'backups',backup,'claude-skills.ts'),'utf8'),'original bridge');
 assert.equal(JSON.parse(fs.readFileSync(path.join(agentDir,'claude-compat.json'),'utf8')).swarmRoot,path.dirname(dir));
 assert(fs.readFileSync(path.join(agentDir,'extensions/usage-dashboard.ts'),'utf8').includes('export * from'));
});
test('swarm input transforms into the normal guarded turn without reentrant dispatch',t=>{
 const root=fixture(t), agentDir=path.join(root,'agent'), swarm=path.join(root,'swarm'); write(path.join(agentDir,'claude-compat.json'),{swarmRoot:swarm}); write(path.join(swarm,'agents/compat-smoke-agent.md'),'---\nname: compat-smoke-agent\ndescription: Fixture role\n---\nFixture instructions.');
 const old=process.env.PI_CODING_AGENT_DIR; process.env.PI_CODING_AGENT_DIR=agentDir; const handlers=new Map(),messages=[];
 try {
  ix.default({on:(n,h)=>handlers.set(n,h),registerTool(){},registerCommand(){},events:{emit(){}},sendMessage:m=>messages.push(m),sendUserMessage:()=>{throw new Error('reentrant dispatch is forbidden');}});
  const ctx={cwd:root,isProjectTrusted:()=>false,model:{provider:'fixture',id:'model'}};
  const transformed=handlers.get('input')({text:'/swarm compat-smoke-agent first line\nsecond line'},ctx); assert.equal(transformed.action,'transform'); assert(transformed.text.includes('subagent')); assert(transformed.text.includes('first line\\nsecond line'));
  assert.equal(routing.routePrompt(transformed.text,r.discover(root,true,root,swarm)),undefined);
  assert.equal(handlers.get('input')({text:'/swarm'},ctx).action,'handled'); assert.equal(messages.at(-1).customType,'swarm-roster');
  assert.equal(handlers.get('input')({text:'/swarm missing-agent task'},ctx).action,'handled');
 } finally { if(old===undefined)delete process.env.PI_CODING_AGENT_DIR;else process.env.PI_CODING_AGENT_DIR=old; }
});
test('project guidance loads only after trust, in canonical then worktree order',t=>{
 const f=setup(t), main=path.join(f.root,'main'), work=path.join(f.root,'work'); fs.mkdirSync(main);
 const git=(...args)=>execFileSync('git',args,{cwd:main,stdio:'ignore'});
 git('init'); git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture'); git('worktree','add','-b','work',work);
 write(path.join(main,'.claude/CLAUDE.md'),'Canonical rules'); write(path.join(work,'.claude/CLAUDE.md'),'Local rules');
 assert.deepEqual(r.discover(work,true,f.home).guidance,[path.join(main,'.claude/CLAUDE.md'),path.join(work,'.claude/CLAUDE.md')]);
 assert.deepEqual(r.discover(work,false,f.home).guidance,[]);
 fs.unlinkSync(path.join(work,'.claude/CLAUDE.md')); fs.symlinkSync(path.join(main,'.claude/CLAUDE.md'),path.join(work,'.claude/CLAUDE.md'));
 assert.equal(r.discover(work,true,f.home).guidance.length,1);
});
test('native router handles accents, project specialists, skill provenance and bounded hints',t=>{
 const f=setup(t); write(path.join(f.home,'.claude/agents/verificador.md'),'---\nname: verificador\ndescription: Default\n---\nDefault'); write(path.join(f.cwd,'.claude/agents/sv-verifier.md'),'---\nname: sv-verifier\ndescription: Specialist\n---\nSpecialist');
 skill(path.join(f.cwd,'.claude/skills/escrita/SKILL.md'),'escrita'); const i=r.discover(f.cwd,true,f.home);
 assert(routing.routePrompt('Preciso de revisão independente',i).includes('sv-verifier'));
 assert(routing.routePrompt('modo enxuto',i).includes(path.join(f.cwd,'.claude/skills/escrita/SKILL.md')));
 assert.equal(routing.routePrompt('/swarm reviewer revisão independente',i),undefined); assert.equal(routing.routePrompt('olá',i),undefined);
 assert.equal(routing.routePrompt('terraform',i),undefined);
 assert(!routing.routePrompt('revisão independente',r.discover(f.cwd,false,f.home)).includes('sv-verifier'));
});
test('before_agent_start injects project rules and native routing without executing hooks',t=>{
 const root=fixture(t), ad=path.join(root,'ad'), swarm=path.join(root,'swarm'); write(path.join(ad,'claude-compat.json'),{swarmRoot:swarm}); write(path.join(swarm,'agents/infra.md'),'---\nname: infra\ndescription: Infra\n---\nInfra rules'); write(path.join(root,'.claude/CLAUDE.md'),'PROJECT_SENTINEL');
 const old=process.env.PI_CODING_AGENT_DIR; process.env.PI_CODING_AGENT_DIR=ad;
 try { const handlers=new Map(); ix.default({on:(n,h)=>handlers.set(n,h),registerTool(){},registerCommand(){},events:{emit(){}}});
 const ctx={cwd:root,isProjectTrusted:()=>true,model:{provider:'fixture',id:'model'}};
 handlers.get('resources_discover')({cwd:root},ctx);
 const out=handlers.get('before_agent_start')({systemPrompt:'BASE',prompt:'terraform',systemPromptOptions:{contextFiles:[]}},ctx); assert(out.systemPrompt.includes('PROJECT_SENTINEL')); assert(out.message.content.includes('agente infra'));
 const dedup=handlers.get('before_agent_start')({systemPrompt:'ALREADY_LOADED',prompt:'olá',systemPromptOptions:{contextFiles:[{path:path.join(root,'.claude/CLAUDE.md')}]}},ctx); assert(!dedup.systemPrompt.includes('PROJECT_SENTINEL')); assert.equal(dedup.message,undefined);
 } finally { if(old===undefined) delete process.env.PI_CODING_AGENT_DIR; else process.env.PI_CODING_AGENT_DIR=old; }
});
test('router prefers project skills and respects the winning manual-only declaration',t=>{
 const f=setup(t); skill(path.join(f.home,'.claude/skills/escrita/SKILL.md'),'escrita'); skill(path.join(f.cwd,'.claude/skills/escrita/SKILL.md'),'escrita'); skill(path.join(f.cwd,'.claude/skills/pull-request/SKILL.md'),'pull-request');
 const i=r.discover(f.cwd,true,f.home); for(const prompt of ['modo enxuto','revise este texto','compacta o CLAUDE.md']) assert(routing.routePrompt(prompt,i).includes(path.join(f.cwd,'.claude/skills/escrita/SKILL.md')));
 assert(routing.routePrompt('escreve a descrição da PR',i).includes('pull-request'));
 for(const s of i.resources.filter(x=>x.kind==='skill')) s.manualOnly=true;
 assert.equal(routing.routePrompt('modo enxuto',i),undefined); assert.equal(routing.routePrompt('abre o PR',i),undefined);
});
test('router prefers a worktree specialist over the canonical generic role',t=>{
 const f=setup(t), main=path.join(f.root,'main'), work=path.join(f.root,'work'); fs.mkdirSync(main);
 const git=(...args)=>execFileSync('git',args,{cwd:main,stdio:'ignore'}); git('init'); git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture'); git('worktree','add','-b','work',work);
 write(path.join(main,'.claude/agents/verificador.md'),'---\nname: verificador\ndescription: Canonical generic\n---\nRules'); write(path.join(work,'.claude/agents/sv-verifier.md'),'---\nname: sv-verifier\ndescription: Worktree specialist\n---\nRules');
 write(path.join(work,'.claude/agents/code-reviewer.md'),'---\nname: code-reviewer\ndescription: Not the verification gate\n---\nRules');
 write(path.join(work,'.claude/agents/verificador.md'),'---\nname: verificador\ndescription: Generic\n---\nRules');
 assert(routing.routePrompt('revisão independente',r.discover(work,true,f.home)).includes('sv-verifier'));
});
test('extension registers model-neutral tools and command entry points',()=>{
 const tools=new Map(), commands=new Map(), events=new Map(); const pi={registerTool:t=>tools.set(t.name,t),registerCommand:(n,c)=>commands.set(n,c),on:(n,h)=>events.set(n,h),events:{emit(){}},getActiveTools:()=>['read','bash']};
 ix.default(pi); for(const n of ['claude_resources','subagent','claude_hook','claude_lsp','web_fetch','web_search']) assert(tools.has(n)); assert(commands.has('claude-compat')); assert(commands.has('claude-skills')); assert(commands.has('swarm-list')); assert(events.has('resources_discover')); assert(events.has('tool_call'));
});
