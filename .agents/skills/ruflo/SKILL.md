---
name: ruflo
description: >-
  Teach Antigravity how to use Ruflo agent harness to orchestrate multi-agent
  swarms, manage persistent memory, run autonomous workflows, and integrate
  with the Comment-analyzer YouTube live-chat Q&A system. Activate when the
  user asks to run agents, coordinate tasks, use swarms, manage memory across
  sessions, or automate workflows with Ruflo.
---

# Ruflo Integration Skill

Ruflo is an **agent meta-harness** around Claude Code / Codex that provides:
- 100+ specialized agents organized into swarms
- Persistent vector memory (RAG) across sessions
- Self-learning intelligence (learns from successful patterns)
- Federated agent communication across machines
- 35 plugins for code quality, security, DevOps, architecture

## Architecture (Comment-analyzer context)

```
Antigravity CLI (you)
    ↓ MCP tools (ruflo-mcp server)
Ruflo Swarm
    ├── comment-analyzer-agent  → polls YouTube live chat
    ├── qa-memory-agent         → manages Q&A memory (ruflo-rag-memory)
    ├── groq-answer-agent       → drafts answers via Groq AI
    └── poster-agent            → posts answers back to YouTube
```

## Key MCP Tools Available (via ruflo-mcp server)

All tools are prefixed `mcp__ruflo__` in Antigravity:

| Tool | What it does |
|------|-------------|
| `mcp__ruflo__swarm_init` | Start a named agent swarm |
| `mcp__ruflo__agent_spawn` | Spawn a specific agent role |
| `mcp__ruflo__memory_store` | Save a Q&A pair to persistent vector memory |
| `mcp__ruflo__memory_query` | Semantic search over stored Q&A pairs |
| `mcp__ruflo__memory_list` | List all memory records |
| `mcp__ruflo__workflow_run` | Execute a named reusable workflow |
| `mcp__ruflo__goal_set` | Set a high-level goal for agents to pursue |
| `mcp__ruflo__cost_status` | Check token usage and budget |

## Workflow: Initialize Ruflo for Comment-analyzer

When the user says "set up Ruflo" or "init Ruflo":

1. Run `npx ruflo init` in `D:\work\Comment-analyzer`
2. Confirm `.claude/`, `.claude-flow/`, `CLAUDE.md` are created
3. Verify the MCP server is registered
4. Run the comment-analyzer swarm workflow below

## Workflow: Start Comment-Analyzer Swarm

```bash
# From D:\work\Comment-analyzer
npx ruflo swarm start --name "comment-analyzer" \
  --agents "qa-memory,groq-answer,live-chat-monitor" \
  --strategy "coordinated"
```

Or via MCP tool in Antigravity:
```
mcp__ruflo__swarm_init {
  "name": "comment-analyzer",
  "topology": "hierarchical",
  "agents": ["qa-memory", "groq-answer", "live-chat-monitor"]
}
```

## Workflow: Persist Q&A to Ruflo Vector Memory

When the user approves a Q&A pair in the Streamlit UI, it can be saved
to Ruflo's persistent vector memory so it survives across sessions:

```
mcp__ruflo__memory_store {
  "content": "<question>",
  "metadata": {
    "answer": "<answer>",
    "source": "comment-analyzer",
    "auto_reply": true
  },
  "namespace": "comment-analyzer-qa"
}
```

To retrieve: `mcp__ruflo__memory_query { "query": "<viewer question>", "namespace": "comment-analyzer-qa", "top_k": 3 }`

## Workflow: Run Autonomous Answer Loop

```bash
npx ruflo autopilot start \
  --goal "Monitor YouTube live chat and auto-reply to known questions" \
  --context "D:\work\Comment-analyzer" \
  --interval 30
```

## Plugin Commands (after `npx ruflo init`)

| Command | Purpose |
|---------|---------|
| `/swarm start comment-analyzer` | Start multi-agent coordination |
| `/memory store <q> <a>` | Save Q&A to vector DB |
| `/memory search <question>` | Semantic search for best answer |
| `/rag import qa_data.json` | Import existing Q&A into Ruflo RAG |
| `/cost status` | Check token usage |
| `/intelligence report` | See what agents have learned |

## Integration Points with Comment-analyzer Code

- **`qa_engine.py`**: Ruflo `ruflo-rag-memory` plugin can replace the
  in-memory `_session_records` with persistent vector storage.
- **`groq_service.py`**: Ruflo `ruflo-ruvllm` plugin can add smart
  routing across multiple LLM providers (Groq, Ollama, Anthropic).
- **`live_chat_poller.py`**: Ruflo `ruflo-loop-workers` plugin provides
  a robust background timer/scheduler replacing the manual poll loop.
- **`answer_poster.py`**: Ruflo `ruflo-swarm` coordinates poster agent
  with the QA memory agent to prevent double-posting.

## Checking Ruflo Status

```bash
npx ruflo status          # overall health
npx ruflo agents list     # all running agents
npx ruflo memory stats    # memory usage and record counts
npx ruflo cost summary    # token usage breakdown
```
