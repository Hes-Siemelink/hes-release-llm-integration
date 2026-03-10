# MCP Client Task & Agent Summary

This repository contains a Digital.ai Release integration plugin (container-based) whose purpose is to demonstrate how
to implement tasks and (specifically) an MCP Client task that can connect to a Model Context Protocol (MCP) ticket
server and invoke its tools (e.g. `list_tickets`).

The project started from the official template (see the separate workshop repository `release-integration-sdk-workshop`)
and keeps the standard build and packaging layout:

* `resources/type-definitions.yaml` – Defines the task types exposed in Release.
* `src/` – Python implementation classes (subclassing `digitalai.release.integration.BaseTask`).
* `tests/` – Unit tests (fast feedback loop without installing the plugin into Release).
* `dev-environment/` – Docker Compose resources for running a local Release development server.

## Fast Overview of Digital.ai Release Integration Plugin Lifecycle

1. Define or update task metadata in `resources/type-definitions.yaml` (names map to Python classes with identical
   simple names).
2. Implement or adjust Python task code under `src/`.
3. Add / refine unit tests under `tests/` for quick iteration.
4. Build the plugin + container image: `sh build.sh --upload` (or the Windows script) – publishes the image to the local
   registry and produces a plugin ZIP.
5. Install/refresh in the local Release instance using the wrapper script
   `./xlw plugin release install --file build/<artifact>.zip`.
6. Run/observe tasks in the Release UI (activity log, outputs, failures, etc.).

## Adding a new task

These are the instructions for adding a new task.

The basic steps are:

1. Add a new entry in `resources/type-definitions.yaml` (copy an existing one and adjust the name, input/output
   properties, etc.).
2. Create a new Python class in `src/` with the same name as the task type (e.g. `MyTask` for a task type
   `MyTask`).
3. Implement the `execute()` method of the class (access input properties via `self.input_properties` and set output
   properties via `self.set_output_property()`).
4. Add unit tests in `tests/` (copy an existing test case and adjust it).

You need to know the following and you may ask the user if you don't have this information:

1. Task name and prefix. For example `release.TaskName` where `release` is the prefix.
2. One input property and its type. For example `name` of type `string`.
3. One output property and its type. For example `result` of type `string

## Adding an exisiting server to a task

If you want to add an existing server to a task, you need to do the following

1. Find the server definition in `resources/type-definitions.yaml` (e.g. `MCPServer`).
2. Add a `server` property to the task definition in `resources/type-definitions.yaml` that references the server
   definition. This must be an input property
3. In the Python class, access the server configuration via `

<!-- BEGIN BEADS INTEGRATION -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Dolt-powered version control with native sync
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update <id> --claim --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Auto-Sync

bd automatically syncs via Dolt:

- Each write auto-commits to Dolt history
- Use `bd dolt push`/`bd dolt pull` for remote sync
- No manual export/import needed!

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

<!-- END BEADS INTEGRATION -->
