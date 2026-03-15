#!/usr/bin/env python3
import os, sys, time
import requests

BASE = os.getenv("BASE", "http://127.0.0.1:8000")
print("Using base URL:", BASE)

try:
    agent_name = f"e2e-test-agent-{int(time.time())}"
    r = requests.post(f"{BASE}/agents", json={"name":agent_name,"description":"e2e test"}, timeout=10)
except Exception as e:
    print("Error creating agent:", e)
    sys.exit(2)

print("create agent:", r.status_code)
print(r.text)
if r.status_code not in (200, 201):
    sys.exit(1)

agent = r.json()
agent_id = agent.get("id") or agent.get("agent_id")
print("agent id:", agent_id)

embedding = [0.0] * 1536
mem = {"content": "This is a test memory from e2e", "metadata": {"source": "e2e"}, "embedding": embedding}
try:
    r2 = requests.post(f"{BASE}/agents/{agent_id}/memories/ingest", json=mem, timeout=20)
except Exception as e:
    print("Error ingesting memory:", e)
    sys.exit(3)

print("ingest status:", r2.status_code)
print(r2.text)

if r2.status_code not in (200,201):
    sys.exit(4)

try:
    r3 = requests.delete(f"{BASE}/agents/{agent_id}", timeout=20)
except Exception as e:
    print("Error deleting agent:", e)
    sys.exit(5)

print("delete agent:", r3.status_code)
if r3.status_code not in (200, 204):
    print(r3.text)
    sys.exit(6)

print("E2E test completed successfully")
