# Claude Code Agent Teams & Subagents — Master Reference Guide

> A comprehensive reference for building, configuring, and orchestrating agent teams and subagents in Claude Code. Use this document when designing multi-agent workflows for any project.

---

## Table of Contents

1. [Core Concepts](#1-core-concepts)
2. [Subagents vs Agent Teams — When to Use Which](#2-subagents-vs-agent-teams--when-to-use-which)
3. [Subagent Configuration](#3-subagent-configuration)
4. [Agent Team Configuration](#4-agent-team-configuration)
5. [Communication & Coordination](#5-communication--coordination)
6. [Isolation Modes](#6-isolation-modes)
7. [Model Selection](#7-model-selection)
8. [Permissions & Security](#8-permissions--security)
9. [Hooks & Lifecycle Events](#9-hooks--lifecycle-events)
10. [Persistent Memory](#10-persistent-memory)
11. [Forked Subagents](#11-forked-subagents)
12. [Best Practices](#12-best-practices)
13. [Patterns & Examples](#13-patterns--examples)
14. [Troubleshooting](#14-troubleshooting)
15. [Limitations](#15-limitations)
16. [Quick Reference Cheat Sheet](#16-quick-reference-cheat-sheet)

---

## 1. Core Concepts

### Subagents

Specialized AI assistants that handle specific tasks within a single session. Each runs in its own context window with a custom system prompt, specific tool access, and independent permissions. Results return to the main conversation.

**Key properties:**
- Run within a single session
- Only report back to the caller (no inter-agent communication)
- Main agent manages all work
- Lower token cost (results summarized back)
- Best for focused tasks where only the result matters

### Agent Teams

Multiple independent Claude Code instances coordinated by a team lead. Teammates work in parallel, communicate directly with each other, and share a task list.

**Key properties:**
- Each teammate is a full, independent Claude Code session
- Teammates message each other directly
- Shared task list with self-coordination
- Higher token cost (each teammate has its own context)
- Best for complex work requiring discussion and collaboration

### Built-in Subagents

| Agent | Model | Tools | Purpose |
|:------|:------|:------|:--------|
| **Explore** | Haiku | Read-only | File discovery, code search, codebase exploration |
| **Plan** | Inherit | Read-only | Codebase research for planning (used in plan mode) |
| **general-purpose** | Inherit | All | Complex research, multi-step operations, code modifications |

> Explore and Plan skip CLAUDE.md files and git status to stay fast and inexpensive. All other subagents load both.

---

## 2. Subagents vs Agent Teams — When to Use Which

| | Subagents | Agent Teams |
|:---|:---|:---|
| **Context** | Own context window; results return to caller | Own context window; fully independent |
| **Communication** | Report results back to main agent only | Teammates message each other directly |
| **Coordination** | Main agent manages all work | Shared task list with self-coordination |
| **Best for** | Focused tasks where only the result matters | Complex work requiring discussion and collaboration |
| **Token cost** | Lower: results summarized back | Higher: each teammate is separate instance |

### Use Subagents When:
- Task produces verbose output you don't need in main context
- You want to enforce specific tool restrictions
- Work is self-contained and can return a summary
- You need quick, focused workers that report back

### Use Agent Teams When:
- Teammates need to share findings and challenge each other
- Research/review from multiple angles simultaneously
- New modules/features where teammates each own a separate piece
- Debugging with competing hypotheses
- Cross-layer coordination (frontend, backend, tests)

### Use Neither (Stay in Main Conversation) When:
- Task needs frequent back-and-forth or iterative refinement
- Multiple phases share significant context
- Making a quick, targeted change
- Latency matters

---

## 3. Subagent Configuration

### File Format

Subagents are defined as Markdown files with YAML frontmatter:

```markdown
---
name: my-agent-name
description: When Claude should delegate to this agent
tools: Read, Grep, Glob, Bash
model: sonnet
---

System prompt goes here in the markdown body.
This is the instruction set the subagent follows.
```

### Subagent Scopes (Priority Order)

| Location | Scope | Priority |
|:---|:---|:---|
| Managed settings | Organization-wide | 1 (highest) |
| `--agents` CLI flag | Current session only | 2 |
| `.claude/agents/` | Current project | 3 |
| `~/.claude/agents/` | All your projects (personal) | 4 |
| Plugin's `agents/` directory | Where plugin is enabled | 5 (lowest) |

When multiple subagents share the same name, the higher-priority location wins.

- **Project subagents** (`.claude/agents/`): Check into version control for team use
- **User subagents** (`~/.claude/agents/`): Personal, available across all projects
- Both directories are scanned recursively (subdirectories are fine)

### All Frontmatter Fields

| Field | Required | Description |
|:---|:---|:---|
| `name` | **Yes** | Unique identifier, lowercase letters and hyphens |
| `description` | **Yes** | When Claude should delegate to this subagent |
| `tools` | No | Tool allowlist. Inherits all if omitted |
| `disallowedTools` | No | Tools to deny (removed from inherited/specified list) |
| `model` | No | `sonnet`, `opus`, `haiku`, `fable`, full model ID, or `inherit` (default) |
| `permissionMode` | No | `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan` |
| `maxTurns` | No | Maximum agentic turns before stopping |
| `skills` | No | Skills to preload into context at startup |
| `mcpServers` | No | MCP servers available to this subagent |
| `hooks` | No | Lifecycle hooks scoped to this subagent |
| `memory` | No | Persistent memory scope: `user`, `project`, or `local` |
| `background` | No | `true` to always run in background (default: `false`) |
| `effort` | No | `low`, `medium`, `high`, `xhigh`, `max` |
| `isolation` | No | `worktree` for isolated git worktree |
| `color` | No | `red`, `blue`, `green`, `yellow`, `purple`, `orange`, `pink`, `cyan` |
| `initialPrompt` | No | Auto-submitted first user turn when running as main session agent |

### Tool Configuration

**Allowlist (only these tools):**
```yaml
tools: Read, Grep, Glob, Bash
```

**Denylist (everything except these):**
```yaml
disallowedTools: Write, Edit
```

**If both are set:** `disallowedTools` is applied first, then `tools` resolves against remaining.

**MCP server patterns:**
```yaml
# Grant all tools from a server
tools: mcp__github

# Remove all tools from a server
disallowedTools: mcp__github

# Remove all MCP tools from any server
disallowedTools: mcp__*
```

**Restrict which subagents can be spawned:**
```yaml
# Only allow spawning worker and researcher subagents
tools: Agent(worker, researcher), Read, Bash

# Allow spawning any subagent
tools: Agent, Read, Bash

# Omit Agent entirely = cannot spawn any subagents
tools: Read, Bash
```

### Tools NOT Available to Subagents

These depend on main conversation UI/session state and cannot be used:
- `AskUserQuestion`
- `EnterPlanMode`
- `ExitPlanMode` (unless `permissionMode: plan`)
- `ScheduleWakeup`
- `WaitForMcpServers`

### CLI-Defined Subagents (Session-Only)

```powershell
claude --agents @'
{
  "code-reviewer": {
    "description": "Expert code reviewer. Use proactively after code changes.",
    "prompt": "You are a senior code reviewer. Focus on code quality, security, and best practices.",
    "tools": ["Read", "Grep", "Glob", "Bash"],
    "model": "sonnet"
  },
  "debugger": {
    "description": "Debugging specialist for errors and test failures.",
    "prompt": "You are an expert debugger. Analyze errors, identify root causes, and provide fixes."
  }
}
'@
```

Accepts the same fields as file-based subagents. Use `prompt` instead of the markdown body.

### MCP Servers Scoped to a Subagent

```yaml
---
name: browser-tester
description: Tests features in a real browser using Playwright
mcpServers:
  # Inline definition: only available to this subagent
  - playwright:
      type: stdio
      command: npx
      args: ["-y", "@playwright/mcp@latest"]
  # Reference by name: reuses an already-configured server
  - github
---
```

---

## 4. Agent Team Configuration

### Enable Agent Teams

Add to settings.json or environment:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### Starting a Team

Describe the task and teammates in natural language:

```
Spawn three teammates to explore this from different angles:
one on UX, one on technical architecture, one playing devil's advocate.
```

Claude spawns teammates, populates a shared task list, and coordinates work.

### Display Modes

| Mode | Description | Setup |
|:---|:---|:---|
| `in-process` (default) | All teammates in main terminal. Arrow keys to navigate. | No setup needed |
| `auto` | Split panes when tmux/iTerm2 available, else in-process | Needs tmux or iTerm2 |
| `tmux` | Force split-pane mode | Needs tmux or iTerm2 |

Set in settings:
```json
{
  "teammateMode": "auto"
}
```

Or per-session:
```bash
claude --teammate-mode auto
```

### In-Process Mode Controls

| Key | Action |
|:----|:-------|
| Up/Down arrows | Select a teammate |
| Enter | Open selected teammate's transcript and message it |
| Escape | Interrupt selected teammate's current turn |
| x | Stop a teammate |
| Ctrl+T | Toggle the task list |

### Specifying Teammates and Models

```
Spawn 4 teammates to refactor these modules in parallel. Use Sonnet for each teammate.
```

Teammates don't inherit the lead's `/model` selection by default. Set **Default teammate model** in `/config` to change this.

### Requiring Plan Approval

```
Spawn an architect teammate to refactor the authentication module.
Require plan approval before they make any changes.
```

The teammate works in read-only plan mode until the lead approves. Influence the lead's judgment with criteria: "only approve plans that include test coverage."

### Using Subagent Definitions for Teammates

Reference any subagent definition when spawning a teammate:

```
Spawn a teammate using the security-reviewer agent type to audit the auth module.
```

The teammate honors the definition's `tools` allowlist and `model`. The definition's body is appended to the teammate's system prompt. Team coordination tools (SendMessage, task tools) are always available regardless of `tools` restrictions.

> Note: `skills` and `mcpServers` from subagent definitions are NOT applied to teammates. Teammates load these from project/user settings.

### Architecture

| Component | Role |
|:---|:---|
| **Team lead** | Main session that spawns teammates and coordinates work |
| **Teammates** | Separate Claude Code instances working on assigned tasks |
| **Task list** | Shared list of work items that teammates claim and complete |
| **Mailbox** | Messaging system for inter-agent communication |

**Storage locations:**
- Team config: `~/.claude/teams/{team-name}/config.json` (auto-generated, removed on session end)
- Task list: `~/.claude/tasks/{team-name}/` (persists locally, never uploaded)

Team name format: `session-` + first 8 chars of session ID.

### Task Management

Tasks have three states: **pending**, **in progress**, **completed**.

Tasks can have dependencies — a pending task with unresolved dependencies cannot be claimed until those dependencies complete.

**Assignment methods:**
- **Lead assigns**: Tell the lead which task to give to which teammate
- **Self-claim**: Teammates pick up the next unassigned, unblocked task automatically

Task claiming uses file locking to prevent race conditions.

### Shutting Down Teammates

```
Ask the researcher teammate to shut down
```

The lead sends a shutdown request. The teammate can approve (exit gracefully) or reject with an explanation.

---

## 5. Communication & Coordination

### Subagent Communication

- One-way: subagent reports results back to the main agent only
- Main agent manages all delegation and synthesis
- No subagent-to-subagent communication

### Agent Team Communication

- **Automatic message delivery**: Messages delivered automatically to recipients
- **Idle notifications**: Teammates notify the lead when they finish
- **Shared task list**: All agents see task status and claim available work
- **Direct messaging**: Any teammate can message any other by name
- **No broadcast**: To reach everyone, send one message per recipient

The lead assigns every teammate a name at spawn time. For predictable names, specify them in the spawn instruction.

### Resuming Subagents (SendMessage)

Completed subagents can be resumed using `SendMessage` with the agent's ID:

```
Continue that code review and now analyze the authorization logic
```

Requires agent teams to be enabled (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). Explore and Plan agents cannot be resumed (they're one-shot).

---

## 6. Isolation Modes

### Worktree Isolation

Set `isolation: worktree` in the subagent definition to run in a temporary git worktree:

```yaml
---
name: risky-refactor
description: Attempts experimental refactoring in isolation
isolation: worktree
---
```

- Creates an isolated copy of the repository
- Branches from the default branch (not the parent session's HEAD)
- Worktree is automatically cleaned up if the subagent makes no changes
- If changes were made, the worktree path and branch are returned

Also available when spawning teammates or forks by passing `isolation: "worktree"` to the Agent tool.

---

## 7. Model Selection

### Resolution Order (Highest Priority First)

1. `CLAUDE_CODE_SUBAGENT_MODEL` environment variable
2. Per-invocation `model` parameter (when Claude spawns the agent)
3. Subagent definition's `model` frontmatter
4. Main conversation's model (inherit)

### Available Model Values

| Value | Model |
|:------|:------|
| `sonnet` | Claude Sonnet (latest) |
| `opus` | Claude Opus (latest) |
| `haiku` | Claude Haiku (fast, cheap) |
| `fable` | Claude Fable (latest) |
| Full model ID | e.g., `claude-sonnet-4-6`, `claude-opus-4-8` |
| `inherit` | Same as main conversation (default) |

### Teammate Models

Teammates don't inherit the lead's `/model` selection by default. Options:
- Specify in spawn prompt: `"Use Sonnet for each teammate"`
- Set **Default teammate model** in `/config` to **Default (leader's model)**

---

## 8. Permissions & Security

### Subagent Permissions

- Inherit permission context from main conversation
- Can override via `permissionMode` field
- **Exception**: If parent uses `bypassPermissions` or `acceptEdits`, this takes precedence and cannot be overridden
- If parent uses auto mode, subagent inherits auto mode regardless of frontmatter

| Mode | Behavior |
|:---|:---|
| `default` | Standard permission checking with prompts |
| `acceptEdits` | Auto-accept file edits and common filesystem commands in working directory |
| `auto` | Background classifier reviews commands and protected-directory writes |
| `dontAsk` | Auto-deny permission prompts (explicitly allowed tools still work) |
| `bypassPermissions` | Skip permission prompts (use with caution) |
| `plan` | Plan mode (read-only exploration) |

### Teammate Permissions

- Start with the lead's permission settings
- If lead uses `--dangerously-skip-permissions`, all teammates do too
- Can change individual modes after spawning
- Cannot set per-teammate modes at spawn time

### Background Subagent Permissions

- Run with permissions already granted in the session
- Auto-deny any tool call that would otherwise prompt
- If clarifying questions are needed, that tool call fails but subagent continues

### Plugin Subagent Restrictions

Plugin subagents do NOT support:
- `hooks`
- `mcpServers`
- `permissionMode`

These fields are ignored when loading agents from a plugin.

### Disabling Subagents

```json
{
  "permissions": {
    "deny": ["Agent(Explore)", "Agent(my-custom-agent)"]
  }
}
```

Or via CLI:
```bash
claude --disallowedTools "Agent(Explore)"
```

To prevent all subagent delegation: deny the `Agent` tool itself.

---

## 9. Hooks & Lifecycle Events

### Hooks in Subagent Frontmatter

Defined in the subagent's markdown file. Only run while that specific subagent is active.

```yaml
---
name: code-reviewer
description: Review code changes with automatic linting
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate-command.sh"
  PostToolUse:
    - matcher: "Edit|Write"
      hooks:
        - type: command
          command: "./scripts/run-linter.sh"
---
```

Supported events:
| Event | Matcher Input | When It Fires |
|:------|:-------------|:--------------|
| `PreToolUse` | Tool name | Before subagent uses a tool |
| `PostToolUse` | Tool name | After subagent uses a tool |
| `Stop` | (none) | When subagent finishes (converted to `SubagentStop` at runtime) |

### Project-Level Hooks (in settings.json)

Respond to subagent lifecycle events in the main session:

```json
{
  "hooks": {
    "SubagentStart": [
      {
        "matcher": "db-agent",
        "hooks": [
          { "type": "command", "command": "./scripts/setup-db-connection.sh" }
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          { "type": "command", "command": "./scripts/cleanup-db-connection.sh" }
        ]
      }
    ]
  }
}
```

### Agent Team Quality Gate Hooks

| Event | When It Fires | Exit Code 2 Behavior |
|:------|:-------------|:---------------------|
| `TeammateIdle` | Teammate is about to go idle | Send feedback, keep teammate working |
| `TaskCreated` | Task is being created | Prevent creation, send feedback |
| `TaskCompleted` | Task is being marked complete | Prevent completion, send feedback |

---

## 10. Persistent Memory

### Configuration

```yaml
---
name: code-reviewer
description: Reviews code for quality and best practices
memory: user
---
```

### Memory Scopes

| Scope | Location | Use When |
|:------|:---------|:---------|
| `user` | `~/.claude/agent-memory/<agent-name>/` | Learnings should apply across all projects |
| `project` | `.claude/agent-memory/<agent-name>/` | Knowledge is project-specific, shareable via VCS |
| `local` | `.claude/agent-memory-local/<agent-name>/` | Project-specific, should NOT be in VCS |

`project` is the recommended default.

### What Happens When Memory Is Enabled

- System prompt includes instructions for reading/writing to the memory directory
- First 200 lines or 25KB of `MEMORY.md` in memory directory is injected into context
- Read, Write, and Edit tools are automatically enabled

### Tips

- Ask the subagent to consult memory before starting: "check your memory for patterns you've seen before"
- Ask the subagent to update memory after tasks: "save what you learned to your memory"
- Include memory instructions in the system prompt for proactive maintenance

---

## 11. Forked Subagents

A fork inherits the entire conversation so far instead of starting fresh.

### Enable Forks

`/fork` command is enabled by default since v2.1.161. To control explicitly:
- `CLAUDE_CODE_FORK_SUBAGENT=1` to enable
- `CLAUDE_CODE_FORK_SUBAGENT=0` to disable

### Usage

```
/fork draft unit tests for the parser changes so far
```

### Fork vs Named Subagent

| | Fork | Named Subagent |
|:---|:---|:---|
| Context | Full conversation history | Fresh context with delegation prompt |
| System prompt & tools | Same as main session | From subagent definition |
| Model | Same as main session | From subagent's `model` field |
| Permissions | Prompts surface in terminal | Auto-denied in background |
| Prompt cache | Shared with main session | Separate cache |

### When to Use Forks

- Named subagent would need too much background context
- You want to try several approaches in parallel from the same starting point
- Side task where re-explaining the situation would be wasteful

### Limitations

- A fork cannot spawn further forks (can spawn other subagent types)
- Enabling fork mode makes all subagent spawns run in background

---

## 12. Best Practices

### Subagent Design

1. **Design focused subagents** — each should excel at one specific task
2. **Write detailed descriptions** — Claude uses the description to decide when to delegate
3. **Limit tool access** — grant only necessary permissions
4. **Check into version control** — share project subagents with your team
5. **Include "use proactively" in description** to encourage automatic delegation

### Agent Team Sizing

- **Start with 3-5 teammates** for most workflows
- **5-6 tasks per teammate** keeps everyone productive
- Three focused teammates often outperform five scattered ones
- Scale up only when work genuinely benefits from parallelism

### Task Sizing

- **Too small**: coordination overhead exceeds the benefit
- **Too large**: teammates work too long without check-ins
- **Just right**: self-contained units producing a clear deliverable (function, test file, review)

### Agent Team Do's

- Give teammates enough context in the spawn prompt (they don't inherit conversation history)
- Specify predictable teammate names for later reference
- Start with research/review tasks if new to agent teams
- Monitor and steer — check in, redirect, synthesize findings
- Break work so each teammate owns different files

### Agent Team Don'ts

- Don't have two teammates edit the same file (leads to overwrites)
- Don't let the team run unattended too long (increases wasted effort risk)
- Don't use teams for sequential tasks or same-file edits
- Don't use teams for routine tasks (single session is more cost-effective)

### Reducing Permission Prompts

Pre-approve common operations in permission settings before spawning teammates.

---

## 13. Patterns & Examples

### Pattern: Parallel Code Review

```
Spawn three teammates to review PR #142:
- One focused on security implications
- One checking performance impact
- One validating test coverage
Have them each review and report findings.
```

### Pattern: Competing Hypotheses (Debugging)

```
Users report the app exits after one message instead of staying connected.
Spawn 5 agent teammates to investigate different hypotheses. Have them talk to
each other to try to disprove each other's theories, like a scientific
debate. Update the findings doc with whatever consensus emerges.
```

### Pattern: Cross-Layer Implementation

```
Spawn three teammates:
- "frontend" to build the React components in src/components/
- "backend" to implement the API endpoints in src/api/
- "tests" to write integration tests in tests/
```

### Example: Read-Only Code Reviewer (Subagent)

```markdown
---
name: code-reviewer
description: Expert code review specialist. Proactively reviews code for quality, security, and maintainability.
tools: Read, Grep, Glob, Bash
model: inherit
---

You are a senior code reviewer ensuring high standards of code quality and security.

When invoked:
1. Run git diff to see recent changes
2. Focus on modified files
3. Begin review immediately

Review checklist:
- Code is clear and readable
- Functions and variables are well-named
- No duplicated code
- Proper error handling
- No exposed secrets or API keys
- Input validation implemented
- Good test coverage
- Performance considerations addressed

Provide feedback organized by priority:
- Critical issues (must fix)
- Warnings (should fix)
- Suggestions (consider improving)

Include specific examples of how to fix issues.
```

### Example: Debugger (Subagent)

```markdown
---
name: debugger
description: Debugging specialist for errors, test failures, and unexpected behavior.
tools: Read, Edit, Bash, Grep, Glob
---

You are an expert debugger specializing in root cause analysis.

When invoked:
1. Capture error message and stack trace
2. Identify reproduction steps
3. Isolate the failure location
4. Implement minimal fix
5. Verify solution works

For each issue, provide:
- Root cause explanation
- Evidence supporting the diagnosis
- Specific code fix
- Testing approach
- Prevention recommendations

Focus on fixing the underlying issue, not the symptoms.
```

### Example: Database Query Validator with Hook

```markdown
---
name: db-reader
description: Execute read-only database queries.
tools: Bash
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate-readonly-query.sh"
---

You are a database analyst with read-only access.
Execute SELECT queries to answer questions about the data.
```

### Example: Subagent with Scoped MCP Server

```markdown
---
name: browser-tester
description: Tests features in a real browser using Playwright
mcpServers:
  - playwright:
      type: stdio
      command: npx
      args: ["-y", "@playwright/mcp@latest"]
  - github
---

Use the Playwright tools to navigate, screenshot, and interact with pages.
```

---

## 14. Troubleshooting

| Problem | Solution |
|:--------|:---------|
| Teammates not appearing | Check agent panel below prompt (in-process mode). Idle teammates hide after 30s — send a message by name to bring back |
| Too many permission prompts | Pre-approve common operations in permission settings before spawning |
| Teammates stopping on errors | View teammate output, give additional instructions, or spawn a replacement |
| Lead shuts down too early | Tell it: "Wait for your teammates to complete their tasks before proceeding" |
| Lead starts implementing instead of delegating | Tell it: "Wait for your teammates to complete their tasks before proceeding" |
| Orphaned tmux sessions | `tmux ls` then `tmux kill-session -t <name>` |
| Task appears stuck | Check if work is done; manually update status or tell lead to nudge teammate |
| Subagent not loading after file edit | Restart session (files loaded at startup; `/agents` interface takes effect immediately) |

---

## 15. Limitations

### Agent Teams

- **No session resumption**: `/resume` and `/rewind` do not restore in-process teammates
- **Task status can lag**: teammates sometimes fail to mark tasks complete
- **Shutdown can be slow**: teammates finish current request before shutting down
- **One team per session**: cannot create additional named teams or share across sessions
- **No nested teams**: teammates cannot spawn their own teammates
- **Lead is fixed**: cannot promote a teammate to lead
- **Permissions set at spawn**: all teammates start with lead's mode
- **Split panes**: not supported in VS Code terminal, Windows Terminal, or Ghostty

### Subagents

- **Nested depth limit**: subagents can spawn nested subagents up to depth 5 (fixed, not configurable)
- **Forks can't fork**: a fork cannot spawn further forks
- **Explore and Plan are one-shot**: cannot be resumed
- **No AskUserQuestion**: subagents cannot prompt the user directly

---

## 16. Quick Reference Cheat Sheet

### Enable Agent Teams
```json
{ "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" } }
```

### Minimal Subagent Definition
```markdown
---
name: my-agent
description: What this agent does and when to use it
---

System prompt instructions here.
```

### Full Subagent Definition Template
```markdown
---
name: my-agent
description: Detailed description of when Claude should delegate to this agent
tools: Read, Grep, Glob, Bash, Edit, Write
disallowedTools: []
model: sonnet
permissionMode: default
maxTurns: 50
skills:
  - my-skill-name
mcpServers:
  - server-name
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate.sh"
memory: project
background: false
effort: high
isolation: worktree
color: blue
---

Detailed system prompt with instructions, workflow steps, and output format.
```

### Spawn Teammates
```
Spawn 3 teammates to [task]. Use Sonnet for each.
Spawn a teammate using the [agent-type] agent type to [task].
Require plan approval before they make any changes.
```

### File Locations
```
Project subagents:  .claude/agents/*.md
User subagents:     ~/.claude/agents/*.md
Team config:        ~/.claude/teams/session-XXXXXXXX/config.json
Task list:          ~/.claude/tasks/session-XXXXXXXX/
Agent memory:       ~/.claude/agent-memory/<name>/ (user scope)
                    .claude/agent-memory/<name>/ (project scope)
                    .claude/agent-memory-local/<name>/ (local scope)
```

### Model Resolution Order
1. `CLAUDE_CODE_SUBAGENT_MODEL` env var
2. Per-invocation `model` parameter
3. Subagent definition's `model` frontmatter
4. Main conversation's model

### Key Environment Variables
| Variable | Purpose |
|:---------|:--------|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | Enable agent teams |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Override model for all subagents |
| `CLAUDE_CODE_FORK_SUBAGENT` | Enable/disable fork mode |
| `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` | Disable all background tasks |
| `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS` | Remove built-in agents (SDK/headless) |
