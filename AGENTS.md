# Code Agent Release Plugin

This repository contains a Digital.ai Release integration plugin (container-based) that uses OpenCode to implement
beads (work items) and create GitHub pull requests.

## Project Structure

* `resources/type-definitions.yaml` -- Defines the task types exposed in Release (prefix: `code-agent.`).
* `src/` -- Python implementation classes (subclassing `digitalai.release.integration.BaseTask`).
* `tests/` -- Unit tests (103 tests, all using `unittest` + `unittest.mock`).
* `dev-environment/` -- Docker Compose resources for running a local Release development server.
* `resources/container-AGENTS.md` -- AGENTS.md template injected into workspaces at runtime.
* `resources/container-opencode.json` -- OpenCode config for container execution.

## Source Modules

| Module | Class | Purpose |
|--------|-------|---------|
| `src/create_pull_request.py` | `CreatePullRequest` | Main 4-phase pipeline: setup, code, question loop, deliver |
| `src/beads_client.py` | `BeadsClient` | Python wrapper for bd CLI (show/update/create/close beads, comments, sync) |
| `src/git_ops.py` | (functions) | Git and GitHub CLI operations (clone, branch, commit, push, create PR) |
| `src/opencode_runner.py` | (functions) | OpenCode headless invocation, prompt composition, needs-answer detection |
| `src/agents_md.py` | (functions) | AGENTS.md template injection and cleanup for workspaces |
| `src/beads_test_connection.py` | `BeadsTestConnection` | Test connection script for BeadsServer config |
| `src/llm_test_connection.py` | `LLMTestConnection` | Test connection script for LLMServer config |

## Type Definitions (prefix: `code-agent.`)

* `code-agent.BeadsServer` -- Configuration type for beads server connection
* `code-agent.LLMServer` -- Configuration type for LLM provider (Anthropic/OpenAI)
* `code-agent.CreatePullRequest` -- Container task: implement a bead and create a PR
* `code-agent.BeadsTestConnection` -- Test connection script for BeadsServer
* `code-agent.LLMTestConnection` -- Test connection script for LLMServer

## Running Tests

Use `unittest` (not pytest -- langsmith plugin crashes on Python 3.12):

```bash
python3 -m unittest discover -s tests -v
```

Or run specific test modules:

```bash
python3 -m unittest tests.test_create_pull_request tests.test_beads_client tests.test_git_ops -v
```

## Build

```bash
sh build.sh --upload
```

## Adding a new task

1. Add a new entry in `resources/type-definitions.yaml` (copy an existing one and adjust).
2. Create a new Python class in `src/` with the same name as the type suffix (e.g., `MyTask` for `code-agent.MyTask`).
3. Implement the `execute()` method (read `self.input_properties`, write `self.set_output_property()`).
4. Add unit tests in `tests/`.

## SDK Patterns

* Tasks extend `digitalai.release.integration.BaseTask`
* Read inputs: `self.input_properties["key"]`
* Write outputs: `self.set_output_property("key", value)`
* Log to activity: `self.add_comment("message")`
* Status line: `self.set_status_line("Phase: setup")`
* Server configs use `kind: ci` with `referenced-type` to reference `xlrelease.Configuration` subtypes
* Class name must match the type suffix (e.g., `code-agent.CreatePullRequest` -> class `CreatePullRequest`)

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

- Use bd for ALL task tracking
- Always use `--json` flag for programmatic use
- Link discovered work with `discovered-from` dependencies
- Check `bd ready` before asking "what should I work on?"
- Do NOT create markdown TODO lists
- Do NOT use external issue trackers
- Do NOT duplicate tracking systems

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
