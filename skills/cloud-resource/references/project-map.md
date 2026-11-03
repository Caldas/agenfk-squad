# Project map

> **Empty template; the repo wins.** Fill one row per project you run the skill
> against, reading only the files, with no credential. Date the reading. Before
> using a row, check it against the repo (`ls infra/ terraform/`, `backend`
> blocks, CLAUDE.md, `.claude/skills/`). Found a divergence? The code wins, and
> the fix to this page goes in a PR to the skill, not in the resource PR.
>
> Keep this file in your own install, not upstream: it describes your projects.

Reading of: `<YYYY-MM-DD>`

| Project | Cloud | State | Environments | Naming / conventions | Project's infra skill |
|---|---|---|---|---|---|
| `<project>` (`<infra/ or terraform/>`) | `<cloud, provider version, region>` | `<remote: backend and lock · local, by recorded choice · none declared>` | `<dev, uat, prod · what applies on merge>` | `<name prefix, repo language, approval rules>` | `<skill names, or —>` |

## What a row changes in the skill

Write the consequences next to the table, one bullet per project that departs
from the defaults. The kinds of departure worth writing down:

- **Local state by recorded choice.** Respect it, do not "fix" it in passing,
  and say so in the PR under Deviations. A remote backend stays the default
  for a new stack.
- **A merge that applies.** If merging into an environment folder applies, the
  PR is in practice an apply in that environment: say so under "Impact of
  applying".
- **A different provider major or lock.** The templates ask for `~> 6.23` and
  `use_lockfile`; in an existing repo, follow the repo's version and lock
  (e.g. a DynamoDB lock table).
- **Stacks that already read each other through `terraform_remote_state`.**
  This skill never generates that in a new project; inside such a repo, follow
  the existing pattern and do not swap it in passing.
- **A decommissioned project.** A new resource there is a question for the
  owner before anything else.
- **Project skills that win** for plan, cost quotes, PR order or PR format.
- **A non-AWS cloud.** The AWS examples here give the shape, not the
  attributes; pricing goes through `finops`.
