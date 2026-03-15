#!/usr/bin/env python3
import sys, os, time
import requests

# Ensure repo root on path if run directly
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE = os.getenv('BASE', 'http://127.0.0.1:8000')

def main():
    # Create a temporary agent
    r = requests.post(f"{BASE}/agents", json={"name": f"search-test-{int(time.time())}", "description": "test"})
    if r.status_code not in (200,201):
        print('create agent failed', r.status_code, r.text)
        sys.exit(2)
    agent = r.json()
    aid = agent['id']

    # Add a memory directly using the create memory endpoint (no embedding provided)
    r2 = requests.post(f"{BASE}/agents/{aid}/memories", json={"content":"this is a memory without explicit embedding","metadata":{"case":"null-embed-test"}}, timeout=20)
    print('ingest:', r2.status_code, r2.text)

    # Search by providing an explicit embedding (simple small vector) to ensure API does not error when DB has null embeddings
    r3 = requests.post(f"{BASE}/agents/{aid}/memories/search", json={"embedding":[0.0], "limit":5}, timeout=20)
    print('search:', r3.status_code, r3.text)
    if r3.status_code == 200:
        print('SEARCH OK')
        sys.exit(0)
    else:
        sys.exit(3)

if __name__ == '__main__':
    main()
