# Claude resources in Pi

A source-preserving, provider-neutral bridge extending the existing `claude-skills.ts`
installation. Original Claude plugins, agents, commands, skills and credentials are not
rewritten. The entry point uses Pi's extension API, not Anthropic inference APIs.

## Install and use

```sh
bash install.sh --pi
```

The installer records this project's `swarmRoot` in Pi's private configuration, so the
roster, skills and dispatch guidance work without a Claude installation. Use `/swarm`
to list agents or `/swarm <agent> <task>` to request real delegation with the selected
Pi model. It also installs the cockpit quota update.

Keep this source directory: the global shim imports it directly. In each existing Pi
session, finish the current step, then run `/reload`, `/claude-compat` and `/squad-status`.
The [native Pi supervisor](VIGIA.md) adds routing, dispatch/loop limits and verified
handoff/pickup without starting Claude lifecycle hooks. `/claude-skills` remains an alias. Repeat `/reload` after installing,
updating, enabling or disabling Claude plugins. Project resources require Pi project trust.
Linked Git worktrees inherit their canonical checkout's Claude settings, with local
worktree settings taking precedence; the root checkout itself is not edited.

- `/skill:name`: skills, including source-preserving normalized copies of malformed YAML
  descriptions. Descriptions longer than the skill standard are shortened only in the
  discovery header. Original full instructions remain available.
- `/plugin:command`: plugin commands, with Pi's positional and `$ARGUMENTS` expansion.
  Global and project Claude commands are also imported. Existing Pi extension commands
  take precedence when names overlap. Claude inline-shell `!` syntax is not pre-executed.
- `claude_resources`: discover or load resource instructions and inspect dependencies.
  Catalogs exclude MCP definitions, headers, environment values and credentials.
- `subagent`: real isolated Pi child processes, with the current provider/model/thinking,
  parent system guidance, CLI extension flags and their registered values, and the intersection of parent-active tools
  and declared agent tools, minus `disallowedTools`. Claude model aliases are not silently
  selected. Nested delegation is disabled; deadline is 180 seconds.
- `web_fetch` / `web_search`: HTTP text retrieval and public Bing RSS search. These are
  alternatives, not Claude's proprietary web tools. No browser sign-ins are inherited.
- `claude_lsp`: hover, definitions, references and document symbols, with zero-based positions.
- `/mcp`: normal MCP connection/authentication, including lazily imported host/plugin servers.
  Plugin MCP names are qualified (`plugin__server`) to prevent collisions. Existing Pi MCP
  configuration wins conflicts, including disabled servers. No startup server connection
  is performed by this bridge.

Distinct colliding plugin skills get qualified names such as `plugin-skill`; distinct
Claude/native skill collisions get `claude-skill`. Equivalent native skill mirrors are
suppressed only when they resolve to the same physical source file. Equal Markdown alone
is insufficient because scripts and assets can differ. Generated resources preserve original base
directories and expand `${CLAUDE_PLUGIN_ROOT}` without moving references or scripts.

## Dependencies and boundaries

The installed `pi-mcp-adapter` package provides MCP runtime registration. Remote servers
can require OAuth, environment variables, network access or local executables; discovery
is not proof that authentication or every tool call works. Use `/mcp` for authoritative
runtime status. Missing enabled plugin installations remain visible as warnings.

The built-in TypeScript plugin has no on-disk LSP manifest, so its documented
`typescript-language-server --stdio` mapping is supplied explicitly. For this machine,
free dependencies were installed privately, without lifecycle scripts:

```sh
npm install --prefix ~/.pi/agent/claude-compat/tools --ignore-scripts \
  --no-audit --no-fund --save-exact typescript-language-server@6.0.2 typescript@5.9.3
```

The bridge prefers executables in that private `.bin` directory, then the server's
configured executable. It never installs dependencies during a model/tool request.

**Delegation is process/context isolation, not an OS sandbox.** A declared Bash tool can
still mutate files. Native Pi CLI extension flags, registered extension flag values (including remote backend
settings) and the selected tool names are carried to the child. Unknown runtime flags and
ephemeral CLI API keys fail closed rather than selecting a different backend or identity. SDK-only hosts/tools are refused rather than pretending their implementations
or permission gates were inherited. Stateful runtime-only policies cannot be serialized by
this subprocess bridge: hosts needing shared, mutable policy state must supply a broker.
Agents declaring Claude-only isolation, permission modes, memory, background or per-agent
hooks remain available as instructions, but execution fails explicitly until adapted.

Claude Desktop's built-in browser, computer-use, document connectors and other private
runtime services are not recreated. Configured Playwright or other MCP servers can provide
alternatives, with their own permissions and authentication. Models still differ in tool
calling, context size, vision and instruction following; cross-provider availability is
not a guarantee of identical results from every model.

## Hooks and safety

All discovered hooks appear in `claude_resources`. Automatic execution is deliberately
limited to exact reviewed `PreToolUse` invocations of the existing Bash guard and project
root-checkout/AgenFK guards. Command prefixes, comments and compound commands cannot obtain
auto-approval through suffix matching. Hook overflow, malformed JSON, execution failure,
explicit denial and unapproved `ask` decisions fail closed.

Other synchronous command hooks are available through `claude_hook`, which requires UI
approval, or through explicit global opt-in in `~/.pi/agent/claude-compat.json`:

```json
{ "enabledHookCommands": ["an exact command you reviewed"] }
```

Only enabled imported `PreToolUse` hooks are automatically attached to Pi tool execution;
other imported lifecycle hooks can be invoked explicitly. The native Pi supervisor is
separate from this legacy-hook catalog; disabled `squad-vigia.py` entries do not mean
the native supervisor is disabled. Inspect `/squad-status` for its authoritative status. Async/rewake/conditional, prompt and agent
hooks are catalogued as unsupported, not silently converted. In particular, legacy hooks
reading Claude-specific transcript/state formats or launching paid Claude SDK reviews are
not automatically started. Claude permission settings and command `allowed-tools` are not
advertised as Pi sandbox policies; Pi's actual active tools and configured gates govern.

## Cockpit five-hour usage

A dedicated `cockpit-quota` widget below the editor displays provider-reported five-hour
consumption, a gauge and reset countdown. It stays visible even when another extension
owns the footer. OpenAI Codex subscriptions and Anthropic OAuth are supported; other
providers show N/A rather than an invented percentage. `/cockpit-quota` refreshes the
query and reports the current state. Provider responses can trigger a throttled refresh,
but unattributed response headers are never assigned to whichever model is now selected.
Late responses from an old provider/request cannot overwrite newer state, and null
usage is not misrepresented as zero. A weekly-only Codex primary window is shown as
weekly usage, never labeled five-hour consumption. The widget owns its render callback
and refreshes its countdown independently of competing footers. Existing cost/cache/handoff dashboard behavior is
preserved. This does not launch the Claude CLI to obtain a quota.

## Validation

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_pi_compat.py
```

The Python entry point runs the Node contract suite using the installed Pi package's loader.
It verifies trust boundaries, worktree precedence, symlinks/cycles, disabled plugins,
malformed YAML normalization, argument/source preservation, namespaced collisions, native
mirrors, secret-free catalogs, process failures/cancellation/deadlines, tool allow/deny
lists, CLI gate forwarding, hook injection/overflow, real local HTTP, RSS parsing, and LSP
framing/file containment. No provider requests are made by these contract tests.

Real provider, MCP and language-server smoke-test results are recorded separately; tests
using a fake child/provider are never represented as cross-model live validation.

## Rollback

Installation prints the timestamped backup directory. Restore its `claude-skills.ts`
and `usage-dashboard.ts` into `~/.pi/agent/extensions/`, and restore its
`claude-compat.json` when present (or remove the new file if none existed), then run `/reload`. Private generated wrappers and
language-server packages live under `~/.pi/agent/claude-compat`; they can be removed after
rollback if no longer needed. Original Claude resources and authentication are untouched.
