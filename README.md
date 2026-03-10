# Code Agent for Digital.ai Release

A Digital.ai Release container plugin that uses [OpenCode](https://opencode.ai) to implement
[beads](https://github.com/steveyegge/beads) (work items) and create GitHub pull requests -- directly
from your release pipelines.

## What it does

Given a bead ID, the plugin:

1. **Claims the bead** and clones the target repository
2. **Runs OpenCode** headlessly to implement the story described in the bead
3. **Handles questions** -- if OpenCode needs clarification, it creates a question bead and polls for answers
4. **Delivers a PR** -- commits, pushes, creates a GitHub pull request, and updates the bead with the PR link

No LangChain, no complex LLM libraries -- just a Python harness that shells out to `opencode`, `git`, `gh`, and `bd`.

## Task: Code Agent: Create Pull Request

### Input Properties

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| Beads Server | CI config | Yes | -- | Connection to the beads server (host, port, project ID) |
| Bead ID | string | Yes | -- | The bead to implement (e.g., `bc-42`) |
| Repository URL | string | Yes | -- | GitHub repository URL to clone |
| Base Branch | string | No | `main` | Branch to create the feature branch from |
| GitHub Token | password | Yes | -- | GitHub PAT with repo and PR permissions |
| LLM Model | CI config | Yes | -- | LLM provider configuration (Anthropic or OpenAI) |
| OpenCode Timeout | integer | No | 1800 | Max seconds for OpenCode to run |
| Question Timeout | integer | No | 3600 | Max seconds to wait for question answers |
| Max Question Rounds | integer | No | 5 | Max question-answer round trips |

### Output Properties

| Property | Type | Description |
|----------|------|-------------|
| Pull Request URL | string | URL of the created PR |
| Branch Name | string | Feature branch name (e.g., `beads/bc-42`) |
| Bead Status | string | Final status: `pr-created` or `no-changes` |

## Configuration Types

### Code Agent: Beads Server

Connection to a Dolt SQL server running the beads database.

- **Host** -- Hostname of the Dolt server (default: `beads-server`)
- **Port** -- Dolt SQL server port (default: `3306`)
- **Project ID** -- The beads project ID (from `.beads/metadata.json`)
- **Prefix** -- Bead ID prefix (default: `bc`)
- **Sync Mode** -- `direct` (SQL) or `dolt` (push/pull)
- **Actor** -- Name for git commits and audit trail (default: `beads-coder`)

### Code Agent: LLM Model

LLM provider configuration for OpenCode.

- **Provider** -- `anthropic` or `openai`
- **API Key** -- Provider API key
- **Model** -- Model identifier (e.g., `claude-sonnet-4-20250514`). Leave empty for provider default.

---

## Build & Run

### Prerequisites

- Python 3.11+
- Docker
- Add to `/etc/hosts`: `127.0.0.1 container-registry`

### Start the dev environment

```bash
docker compose -f dev-environment/docker-compose.yaml up -d --build
```

Log in at http://localhost:5516 with `admin/admin`.

### Build & publish the plugin

```bash
sh build.sh --upload
```

### Run the tests

```bash
python3 -m unittest discover -s tests -v
```

## Architecture

```
src/
  create_pull_request.py  -- Main 4-phase pipeline task (Setup, Code, Q&A, Deliver)
  beads_client.py         -- Python wrapper for bd CLI (BeadsClient)
  git_ops.py              -- Git and GitHub CLI operations
  opencode_runner.py      -- OpenCode headless invocation
  agents_md.py            -- AGENTS.md template injection for workspaces
  beads_test_connection.py -- BeadsServer config validation
  llm_test_connection.py  -- LLM provider config validation

resources/
  type-definitions.yaml   -- Release task type definitions
  container-AGENTS.md     -- AGENTS.md template injected into workspaces
  container-opencode.json -- OpenCode config (permission: allow)

tests/
  test_create_pull_request.py  -- 18 tests
  test_beads_client.py         -- 33 tests
  test_git_ops.py              -- 15 tests
  test_opencode_runner.py      -- 15 tests
  test_agents_md.py            -- 10 tests
  test_llm_test_connection.py  -- 8 tests
  test_beads_test_connection.py -- 4 tests
```

## Container Image

The Dockerfile builds a multi-stage image:

- **Python 3.11-slim** -- Release SDK + task code
- **Node.js 22** -- OpenCode runtime
- **gh** -- GitHub CLI for PR creation
- **bd** -- Beads CLI for issue tracking
- **dolt** -- Dolt for beads database sync
