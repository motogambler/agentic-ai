Architecture & Components

## Overview

Local-first, modular agent platform combining Ollama, LiteLLM, and optional OpenAI for hybrid inference. Uses Docker/Rancher for infra and includes cost-aware controls and observability.

## Core Runtime

- **Agent Core:** Python service (FastAPI) that routes requests, manages agent definitions, policies, tools, and session orchestration.
- **Worker / Executor:** Background worker pool (e.g., Celery / asyncio workers) for long-running tasks, tool execution, and async planning.

## LLM Adapters (Pluggable)

- **Ollama Adapter:** interface to local Ollama instances (HTTP/CLI).
- **LiteLLM Adapter:** local inference via `litellm` Python bindings.
- **OpenAI Adapter:** cloud fallback with strict budgeting and token accounting.

Each adapter exposes a common call interface with usage metadata (tokens, latency, model id).

## Agent Framework / DSL

- Minimal, open API to define agents: goals, tools, memory configuration, and policies.
- Support for scripted agents and programmatic creation via REST and CLI.

## Tools & Tooling Layer

- Standardized tool invocation (shell, HTTP, Python callables, custom connectors).
- Tool registry with capability metadata, permission controls, and safe execution sandboxing.

## Memory & Storage

- **Local (quick start):** SQLite-backed vector store (Chroma or similar) for embeddings and session state.
- **Durable (production):** Postgres with `pgvector` running in Docker/Rancher for persistence, backups, and scaling.

## Infrastructure (Rancher / Docker)

- Docker Compose / Helm manifests to run services locally under Rancher.
- Containers for: Agent service, worker, Postgres/pgvector, optional vector DB, and monitoring agents.

## Cost Monitoring & Budgeting

- Token and call accounting in adapters (particularly for OpenAI).
- Budget caps (daily/weekly), alerts, and a simple CLI/dashboard showing spend and usage per agent.

## Observability & Logging

- Structured logs, request traces, and metrics (Prometheus-friendly).
- Request metadata includes tokens consumed, model used, and latency for each LLM call.

## Security & Policies

- Local secrets via environment variables or local vault integration.
- Policy layer for tool whitelisting, safe mode toggles, and rate limiting.

## Developer UX & Examples

- CLI for creating and running agents, plus a minimal web UI to inspect runs and memory.
- Example templates: retrieval-augmented QA, task planner, and code assistant.

## Extensibility

- Clear adapter interface for adding more local/cloud LLMs.
- Plugin hooks for custom tools, memory backends, and evaluation suites.

## Next Steps

1. Scaffold repository with a FastAPI starter and adapter interfaces.
2. Provide Docker Compose for Postgres+pgvector and a quick SQLite/Chroma fallback.
3. Add basic Ollama and LiteLLM adapter implementations and budget-tracking middleware.

---