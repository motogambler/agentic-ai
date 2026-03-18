import os
import shutil
import subprocess
import sys
from urllib.parse import urlparse

DEFAULT_MODELS = os.getenv('PRELOAD_MODELS', '')
if not DEFAULT_MODELS:
    DEFAULT_MODELS = ",".join([
        "hf:databricks/dolly-v2-3b",
        "hf:tiiuae/falcon-7b-instruct",
        "hf:mistralai/mistral-7b",
        "hf:OpenAssistant/research-oasst-small-1-pythia-12b",
        "gpt4all:gpt4all-j",
        "ggml:vicuna-7b-q4",
    ])

MODELS_DIR = os.getenv('MODELS_DIR', '/app/models')


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def run_ollama_pull(name: str) -> bool:
    if shutil.which('ollama') is None:
        return False
    try:
        subprocess.run(['ollama', 'pull', name], check=True)
        return True
    except Exception:
        return False


def download_hf(repo_id: str, dest: str) -> bool:
    try:
        from huggingface_hub import snapshot_download
    except Exception:
        return False
    try:
        snapshot_download(repo_id, cache_dir=dest, resume_download=True)
        return True
    except Exception:
        return False


def download_url(url: str, dest: str) -> bool:
    try:
        import httpx
        ensure_dir(os.path.dirname(dest))
        with httpx.stream('GET', url, timeout=60.0) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return True
    except Exception:
        return False


def handle_item(item: str):
    item = item.strip()
    if not item:
        return
    if ':' in item:
        prefix, rest = item.split(':', 1)
    else:
        prefix, rest = 'hf', item

    target = os.path.join(MODELS_DIR, prefix.replace('/', '_') + '_' + rest.replace('/', '_'))
    ensure_dir(target)

    if prefix == 'ollama':
        print(f"[preload] trying ollama pull {rest}")
        ok = run_ollama_pull(rest)
        print('[preload] ollama pull', 'ok' if ok else 'failed')
        return

    if prefix == 'hf':
        print(f"[preload] downloading HF repo {rest} to {target}")
        ok = download_hf(rest, target)
        print('[preload] hf', 'ok' if ok else 'failed')
        return

    if prefix in ('http', 'https', 'url'):
        url = rest if prefix == 'url' else f"{prefix}:{rest}"
        fn = os.path.basename(urlparse(url).path) or 'model.bin'
        dest = os.path.join(target, fn)
        print(f"[preload] downloading URL {url} to {dest}")
        ok = download_url(url, dest)
        print('[preload] url', 'ok' if ok else 'failed')
        return

    # custom short names (gpt4all, ggml) - try as URL first, then skip
    if prefix in ('gpt4all', 'ggml'):
        print(f"[preload] custom handler for {prefix}:{rest} - skipping automatic download; please provide full url or use ollama/hf prefixes")
        return

    print(f"[preload] unknown prefix '{prefix}' for {item} - skipping")


def main():
    models = os.getenv('PRELOAD_MODELS', DEFAULT_MODELS)
    if not models:
        print('[preload] no PRELOAD_MODELS set; nothing to do')
        return
    ensure_dir(MODELS_DIR)
    items = [m.strip() for m in models.split(',') if m.strip()]
    for it in items:
        try:
            handle_item(it)
        except Exception as e:
            print('[preload] error handling', it, e)


if __name__ == '__main__':
    main()
