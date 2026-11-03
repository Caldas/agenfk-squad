# Modules: first, but only the ones that exist

Most projects have no shared module repository. The question "which module do
I use?" almost always answers **none yet**, and the question that matters is
the next one: will this shape repeat?

## The order

1. **A published, pinned module.** If the project already consumes a module
   (`git::` with `?ref=`, a private registry, a local module in `modules/` with
   more than one consumer), use it, pinned by tag.
   `grep -rn 'source *=' infra/ terraform/` shows what exists.
2. **Create a module when reuse is a fact.** The request says reuse ("one per
   environment in three accounts", "one per service") or the same shape
   already exists in two stacks. A vague forecast of reuse does not count.
3. **Plain HCL in the stack, with a note.** The common case. Write the
   resources in the stack and put in the PR: "Module candidate: `<name>`: this
   is the Nth place this shape appears", citing the other places if you found
   them.

Do not create a local module "to share later": a module with one consumer is
indirection. A public registry module (`terraform-aws-modules/...`) is a
supply-chain dependency: only with the owner aware, stated in the PR.

## Consuming

Always by tag, never a branch, never "latest":

```hcl
module "queue" {
  source = "git::https://github.com/<owner>/<modules-repo>.git//aws-queue?ref=aws-queue/v1.2.0"
  # ...
}
```

Tags `<module>/vX.Y.Z`: releasing one module does not move users of another.

## Creating a module

Ask the owner where the module lives before writing (it is a shared resource:
triage, destination 1). Inside the project, `infra/modules/<module>/`:

```
<module>/
├── README.md          # inputs/outputs table and a usage example
├── main.tf
├── variables.tf       # typed and described; validation where it is cheap
├── outputs.tf         # names and ARNs the consumer needs
├── versions.tf        # required_version and providers, NO backend
├── examples/basic/    # a root that validate runs with no credential
└── tests/*.tftest.hcl # mocked provider, one assertion per promise
```

Module rules, on top of `patterns.md`:

- **No backend block and no provider block.** The consumer owns both. A
  module with a backend cannot be consumed.
- **No account literal**: account id, VPC, AZ and ARN come in by variable.
- **Naming through a `name_prefix`** received from the consumer.
- **Tags through a `tags` variable**, merged into the resources.
  `default_tags` belongs to the root's provider, never to the module.

## Two dependent PRs

When the module lives in another repo:

| PR | Repo | Content | Order |
|---|---|---|---|
| 1 | modules repo | module + tests | first; the owner cuts the tag |
| 2 | project stack | `module` pinned at `?ref=<module>/vX.Y.Z` + wiring + cost table | after the tag exists |

PR 2 declares the dependency in its body (link to PR 1, the tag it waits for)
and does not land before the tag. To validate PR 2 earlier, point `source` at a
local checkout of PR 1 only for `init -backend=false && validate && test`,
never committed; commit the pinned form and say that init and CI stay red
until the tag exists. The cost table goes in PR 2, with the resources the
module instantiates; PR 1 instantiates nothing and says so. Merge order and PR
stacks: the `github` agent (skill `parallel-git`). The skill never pushes a
tag.
