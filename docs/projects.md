# Projects

A workflow needs somewhere to work. Until projects existed the only thing a caller
could say was a path, and saying nothing got a fresh empty directory under
`.factory-workspaces` — the right default for a factory that builds something from
nothing, and the wrong one for every workflow whose purpose is to change a codebase
that already exists.

A project is a name for a checkout. Declare it once and `--project snake` points any
workflow at it.

## The file

`$HARNESS_CONFIG_DIR/projects.json`, defaulting to
`~/.coil-agent-harness/projects.json` — the same directory `providers.json` uses, and
machine-specific for the same reason: where your checkouts live is not something to
commit.

```json
{
  "version": 1,
  "projects": [
    {
      "name": "snake",
      "path": "~/Documents/Code/projects/coil-snake",
      "label": "Coil Snake",
      "summary": "SDL2 snake, the factory's standing example",
      "default_issue_workflow": "snake-issue"
    },
    {
      "name": "harness",
      "path": "~/Documents/Code/projects/coil-agent-harness"
    }
  ]
}
```

`name` and `path` are required; the path must be absolute or start with `~/`.
`label` defaults to the name, and `default_issue_workflow` defaults to `issues`,
the generic implement-and-verify workflow in `factories/issues`.

```sh
./harness projects
```

lists what is declared, marking any checkout that is not there.

Absence is not an error: with no file at all, everything behaves exactly as it did
before projects existed. Anything else — unreadable, unparseable, missing a name or
path, a relative path, or one name declared twice — refuses to run and names the
entry. A project resolves to a directory agents are about to write into, so a typo
has to stop the run rather than quietly send the work somewhere else.

## Running a workflow against a project

```sh
./harness factory run factories/snake-feature --project snake
```

A workflow does not belong to a project and its manifest says nothing about one. It
is a reusable definition; the project is chosen when you run it, so the same
workflow runs in any checkout you have.

Where a run happens is resolved in the order a person means it:

1. an explicit `workspace` argument or `--workspace`;
2. `--project`;
3. a fresh `.factory-workspaces` directory — the historical behaviour, and what a
   workflow that builds something from nothing still wants.

An unknown project name, or one whose checkout is missing, is refused at step 2
rather than falling through to step 3. Silently running in an empty scratch directory
would produce a confident report about a codebase that was never there.

A run records the workspace it ran in, so which project it happened in is a durable
fact about that run rather than a label attached to a definition. That is what the
window groups by.

## Issues

An issue is a request against a codebase: a Markdown file, by convention under
`.factory-issues`, whose front matter names the project it was filed against.

```markdown
---
project: snake
---

# Snake does not wrap at the borders

When the snake reaches any edge of the board, it does not appear on the opposite
edge. Instead, play stops as though hitting a wall caused game over.
```

Running one hands the file to a workflow as that run's context:

```sh
./harness factory issue factories/issues --issue .factory-issues/snake-does-not-wrap.md
```

The workspace comes from `--workspace`, then `--project`, then the issue's own front
matter. If none of those name one, the command refuses:
an issue is a change to something that exists, and there is no honest way to resolve
one in an empty directory.

## The window

`coil-agent-gui` reads this same file, and is built on the same three nouns:

- the rail is **projects**, and under each one the **runs** that happened there and the
  **issues** filed there;
- the middle pane of a project is the **library** — every workflow you have — under the
  question "run a workflow here";
- picking one puts its name on the Run button along with the project: `Run in snake`.

⌘N writes a workflow into the library and asks for no project, because a workflow has
none. ⌘I files an issue in the project you are looking at. If the window and the CLI
read different files they would disagree about what "snake" means, and the button that
starts a run would point somewhere other than the row you clicked.
