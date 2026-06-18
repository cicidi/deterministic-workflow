---
name: ai-cowork-install
description: "Installs and configures the ai-coworker tool for the deterministic workflow framework project. Sets up coworker.yaml, syncs to all AI tools (Claude Code, OpenCode, Gemini), and configures project-specific MCP servers."
user-invocable: true
---

# AI Cowork Install — Deterministic Workflow Framework

## When to Use

- First-time project setup — installing the ai-coworker tool
- Adding a new AI tool to the sync list
- Adding project-specific MCP servers

## Prerequisites

- Node.js ≥ 18
- Python ≥ 3.10
- Git

## Installation

### Step 1: Install ai-coworker

```bash
npm install -g ai-coworker
```

Verify:
```bash
coworker --version
```

### Step 2: Initialize Project Config

```bash
cd /path/to/deterministic-ai-agent
coworker init
```

This creates `~/.coworker/coworker.yaml`.

### Step 3: Configure Project-Specific MCP Servers

Add these MCP servers to `~/.coworker/coworker.yaml`:

```yaml
# ~/.coworker/coworker.yaml
mcp:
  # Knowledge base for spec documents
  - name: deterministic-specs
    command: npx
    args:
      - "-y"
      - "@anthropic/mcp-server-filesystem"
      - "--root=/home/cicidi/project/deterministic-ai-agent/docs/specs"
    enabled: true

  # GitHub integration for issue management
  - name: github
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
    enabled: true

  # Python code execution
  - name: python-runner
    command: python
    args:
      - "-m"
      - "mcp_server_python"
    enabled: false   # enable when implementation phase begins

# AI tool integrations  
tools:
  claude_code:
    enabled: true
    skills_path: "/home/cicidi/project/deterministic-ai-agent/skills"

  opencode:
    enabled: true
    skills_path: "/home/cicidi/project/deterministic-ai-agent/skills"

  gemini:
    enabled: false
    skills_path: "/home/cicidi/project/deterministic-ai-agent/skills"

# Project settings
project:
  name: "deterministic-ai-agent"
  root: "/home/cicidi/project/deterministic-ai-agent"
  always_loaded_docs:
    - "docs/VISION.md"
    - "CLAUDE.md"
  specs_base: "docs/specs/"
```

### Step 4: Sync to All Tools

```bash
coworker sync
```

This syncs the MCP servers, skills, and project docs to all enabled AI tools (Claude Code, OpenCode).

### Step 5: Verify

```bash
coworker status
```

Expected output shows all MCP servers as "connected" and all AI tools as "synced".

## Project-Specific Skills

After installation, register the project skills:

```bash
# These skills are in the project's skills/ directory
coworker skill register skills/issue-create
coworker skill register skills/implement-interview
coworker skill register skills/evals-create
coworker skill sync    # sync skills to all AI tools
```

## Development Environment Setup

### Python Environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### LLM Provider Setup

Create `.env` from `.env.example`:
```bash
cp .env.example .env
# Edit .env with your LLM API keys
```

## Quick Start Commands

```bash
# Start LangFlow (visual editor)
pip install langflow && langflow run

# Start LangGraph dev server
pip install langgraph-cli && langgraph dev

# View project status
coworker status

# List available skills
coworker skill list
```

## Troubleshooting

**MCP server not connecting:**
```bash
coworker doctor    # diagnose issues
coworker restart   # restart all MCP servers
```

**Skills not appearing in Claude Code:**
```bash
coworker skill list --tool claude_code
coworker sync --force
# Restart Claude Code
```

**Python MCP server fails to start:**
```bash
pip install mcp-server-python  # ensure the Python MCP package is installed
```

## What Gets Installed

| Component | Tool | Path |
|-----------|------|------|
| MCP servers | Filesystem (specs), GitHub | `~/.coworker/coworker.yaml` |
| Skills | issue-create, implement-interview, evals-create | `skills/` → synced to all AI tools |
| Project docs | VISION.md, CLAUDE.md | Auto-loaded by AI tools every session |
| LLM config | `.env` | API keys for OpenAI/Anthropic/DeepSeek |
