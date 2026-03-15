#!/usr/bin/env python3
"""
Lightweight persistence check script (not a strict unit test).

Usage:
  1. Start the server: `uvicorn src.app.main:app --reload`
  2. Run this script: it will create an agent and a memory, then prompt you to
     restart the server manually. After you restart the server, re-run the
     script with --verify to check the memory is still present.

This is intended for manual/CI use where a restart step is manageable.
"""
import os, sys, time, argparse, requests

BASE = os.getenv("BASE", "http://127.0.0.1:8000")

parser = argparse.ArgumentParser()
parser.add_argument("--verify", action="store_true", help="Verify memory after restart")
parser.add_argument("--agent-id", type=int, help="Agent id to verify (used with --verify)")
args = parser.parse_args()

if not args.verify:
    agent_name = f"persistence-check-{int(time.time())}"
    r = requests.post(f"{BASE}/agents", json={"name": agent_name, "description": "persistence check"})
    r.raise_for_status()
    agent = r.json()
    aid = agent.get("id") or agent.get("agent_id")
    print("Created agent:", aid)
    mem = {"content": "persistence-test", "metadata": {"source": "persistence-check"}}
    r2 = requests.post(f"{BASE}/agents/{aid}/memories/ingest", json=mem)
    r2.raise_for_status()
    print("Ingested memory. Now restart the server (or container). After restart run this script with --verify --agent-id", aid)
    sys.exit(0)
else:
    if not args.agent_id:
        print("--agent-id required with --verify")
        sys.exit(2)
    aid = args.agent_id
    r = requests.get(f"{BASE}/agents/{aid}/status")
    if r.status_code != 200:
        print("Agent not found or server not running", r.status_code)
        sys.exit(3)
    j = r.json()
    recent = j.get("recent_memories", [])
    found = any("persistence-test" in (m.get("content") or "") for m in recent)
    if found:
        print("Persistence verified: memory present")
        sys.exit(0)
    else:
        print("Persistence check failed: memory not found in recent_memories")
        sys.exit(4)
