import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from .. import crud
from ..db import AsyncSessionLocal

router = APIRouter()


@router.get("/playground", response_class=HTMLResponse)
async def agent_playground():
    initial_agents = []
    try:
        async with AsyncSessionLocal() as db:
            agents = await crud.get_agents(db)
            initial_agents = [{"id": agent.id, "name": agent.name} for agent in agents]
    except Exception:
        initial_agents = []

    html = r"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Agent Playground</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 20px; }
      label { display:block; margin-top:10px }
      select, textarea, input { width:100%; }
      textarea { height: 140px; }
      #output { white-space: pre-wrap; background:#f7f7f7; padding:10px; margin-top:10px; }
      button { margin-top:8px; padding:8px 12px; }
      .repo-controls { display:flex; gap:12px; align-items:center; margin-top:10px; }
      .repo-controls .repo-path-wrap { flex:1; min-width:0; }
      .repo-controls .repo-path-wrap input { width:100%; box-sizing:border-box; }
      .repo-controls .repo-toggle { display:flex; align-items:center; gap:8px; margin:0; white-space:nowrap; }
      .repo-controls .repo-toggle input { width:auto; margin:0; }
      .repo-note { font-size:12px; color:#666; margin-top:6px; }
    </style>
  </head>
  <body>
    <h2>Agent Playground</h2>
    <label>Agent
      <select id="agentSelect"></select>
    </label>
    <label>LiteLLM Model
      <select id="modelSelect"><option value="">(default)</option></select>
      <button id="refreshModels" style="margin-top:6px;">Refresh Models</button>
    </label>
    <label>Goal
      <textarea id="goal"></textarea>
    </label>
    <label>Context (optional)
      <textarea id="context"></textarea>
    </label>
    <div class="repo-controls">
      <div class="repo-path-wrap">
        <label style="margin-top:0">Repository / Folder (optional)
          <input id="repoPath" placeholder="agents/ or workspace/ or leave blank" />
        </label>
      </div>
      <label class="repo-toggle">
        <input type="checkbox" id="repoToggle" />
        <span>Enable repo tool</span>
      </label>
    </div>
    <div class="repo-note" id="repoStatus">Repo tool: checking status...</div>
    <button id="submit">Submit</button>
    <div style="margin-top:8px">Status: <span id="status">-</span></div>
    <div style="display:flex;gap:20px;margin-top:12px;">
      <div style="flex:1">
        <h3>Result</h3>
        <div id="output"></div>
      </div>
      <div style="width:380px;">
        <h3>Agent Status</h3>
        <div>Queue size: <span id="queueSize">-</span></div>
        <button id="refreshStatus">Refresh Status</button>
        <button id="viewQueue">View Queue</button>
        <div id="queueView" style="max-height:240px;overflow:auto;border:1px solid #eee;padding:6px;margin-top:8px;background:#fff"></div>
        <h4>Recent Memories</h4>
        <div id="recent"></div>
      </div>
    </div>

    <script>
      const INITIAL_AGENTS = __INITIAL_AGENTS__;
      const MODEL_STORAGE_KEY = 'agentic-ai-model-options';
      let lastSubmittedMs = 0;

      function setOutput(message){
        const out = document.getElementById('output');
        if(out) out.textContent = message;
      }

      function isUsefulMemory(content){
        if(!content) return false;
        if(content.includes('unknown tool:')) return false;
        if(content.includes('"tool_call"')) return false;
        if(content.includes('adapter error:')) return false;
        return content.startsWith('LLM final:') || content.startsWith('LLM result:') || content.startsWith('Tool ');
      }

      function shouldShowInRecent(memory){
        if(!memory || !memory.content) return false;
        const content = memory.content;
        if(content.includes('adapter error:')) return false;
        if(content.includes('unknown tool:')) return false;
        if(content.includes('"tool_call"')) return false;
        if(content.includes("model '' not found")) return false;
        if(content.includes("model '\'\'' not found")) return false;
        return true;
      }

      function formatMemoryForOutput(content){
        if(!content) return '';
        const cleaned = content
          .replace(/^LLM final:\s*/, '')
          .replace(/^LLM result:\s*/, '')
          .replace(/^Tool [^:]+ (executed|result):\s*/, '');
        try{
          const parsed = JSON.parse(cleaned);
          if(parsed && typeof parsed === 'object'){
            if(Object.prototype.hasOwnProperty.call(parsed, 'result')) return String(parsed.result);
            if(Object.prototype.hasOwnProperty.call(parsed, 'value')) return String(parsed.value);
          }
        }catch(_){ }
        return cleaned;
      }

      function latestDisplayMemory(memories){
        if(!Array.isArray(memories)) return null;
        const fresh = memories.filter(m => {
          if(!m || !m.created_at || !lastSubmittedMs) return false;
          const t = Date.parse(m.created_at);
          return !Number.isNaN(t) && t >= (lastSubmittedMs - 2000);
        });
        for(const m of fresh){
          if(isUsefulMemory(m.content)) return m;
        }
        for(const m of memories){
          if(isUsefulMemory(m.content)) return m;
        }
        return memories.length ? memories[0] : null;
      }

      function normalizeModelIds(payload){
        if(!payload) return [];
        if(Array.isArray(payload)){
          return payload.map(m => typeof m === 'string' ? m : (m && (m.id || m.name || m.model))).filter(Boolean);
        }
        if(Array.isArray(payload.models)) return normalizeModelIds(payload.models);
        if(Array.isArray(payload.data)) return normalizeModelIds(payload.data);
        if(Array.isArray(payload.result)) return normalizeModelIds(payload.result);
        return [];
      }

      async function loadAgents(){
        const btn = document.getElementById('submit');
        const sel = document.getElementById('agentSelect');
        if(btn) btn.disabled = true;
        if(sel) sel.innerHTML = '<option value="">Loading agents...</option>';

        function renderAgents(agents){
          if(!sel) return;
          sel.innerHTML = '';
          if(!Array.isArray(agents) || agents.length === 0){
            sel.innerHTML = '<option value="">(no agents found)</option>';
            return;
          }
          agents.forEach(a => {
            const opt = document.createElement('option');
            const aid = a.id || a.file || (a.frontmatter && a.frontmatter.name) || a.name;
            const label = a.name || (a.frontmatter && a.frontmatter.name) || a.summary || a.file || aid;
            opt.value = aid;
            opt.textContent = label;
            sel.appendChild(opt);
          });
        }

        if(Array.isArray(INITIAL_AGENTS) && INITIAL_AGENTS.length){
          renderAgents(INITIAL_AGENTS);
          if(btn) btn.disabled = false;
        }

        try{
          const res = await fetch('/agents/');
          if(!res.ok){
            const txt = await res.text();
            setOutput('Failed to load agents: ' + res.status + ' ' + txt);
            if(!INITIAL_AGENTS.length && sel) sel.innerHTML = '<option value="">(failed to load agents)</option>';
            return;
          }
          const agents = await res.json();
          renderAgents(agents);
          if(btn) btn.disabled = false;
          await refreshStatus();
        }catch(e){
          setOutput('Error loading agents: ' + e);
          if(!INITIAL_AGENTS.length && sel) sel.innerHTML = '<option value="">(error loading agents)</option>';
        }
      }

      async function fetchModels(){
        const msel = document.getElementById('modelSelect');
        const prevSelection = msel ? msel.value : '';

        function renderModels(models){
          if(!msel) return;
          msel.innerHTML = '<option value="">(default)</option>';
          if(Array.isArray(models) && models.length){
            models.forEach(model => {
              const opt = document.createElement('option');
              opt.value = model;
              opt.textContent = model;
              msel.appendChild(opt);
            });
          } else {
            msel.innerHTML = '<option value="">(default)</option><option value="" disabled>(no models found)</option>';
          }
        }

        try{
          const cached = window.localStorage.getItem(MODEL_STORAGE_KEY);
          if(cached){
            const parsed = JSON.parse(cached);
            if(Array.isArray(parsed) && parsed.length){
              renderModels(parsed);
              if(prevSelection && parsed.includes(prevSelection)){
                msel.value = prevSelection;
              }
            }
          }
        }catch(_){ }

        function fetchWithTimeout(url, ms){
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), ms);
          return fetch(url, { signal: controller.signal }).finally(() => clearTimeout(timer));
        }

        try{
          const [litellmRes, ollamaRes] = await Promise.all([
            fetchWithTimeout('/admin/litellm/models', 3000).catch(() => null),
            fetchWithTimeout('/admin/ollama_models', 2000).catch(() => null)
          ]);

          let models = [];

          // Prefer fresh probe results, but do not overwrite a non-empty cached list
          const cachedRaw = window.localStorage.getItem(MODEL_STORAGE_KEY);
          let cachedModels = null;
          try{ cachedModels = cachedRaw ? JSON.parse(cachedRaw) : null; }catch(_){ cachedModels = null; }

          if(litellmRes && litellmRes.ok){
            const litellmData = await litellmRes.json();
            // respect explicit unavailable flag from backend
            if(litellmData && litellmData.available !== false){
              models.push(...normalizeModelIds(litellmData));
            }
          }

          if(ollamaRes && ollamaRes.ok){
            const ollamaData = await ollamaRes.json();
            if(ollamaData && ollamaData.available !== false){
              const ollamaModels = normalizeModelIds(ollamaData.models).map(id => id.startsWith('ollama:') ? id : ('ollama:' + id));
              models.push(...ollamaModels);
            }
          }

          models = Array.from(new Set(models.filter(Boolean)));

          // If probes returned nothing but we have a non-empty cached list, keep cache
          if(models.length === 0 && Array.isArray(cachedModels) && cachedModels.length){
            models = cachedModels;
          }

          renderModels(models);
          try { window.localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify(models)); } catch (_) { }
          if(prevSelection && models.includes(prevSelection)){
            msel.value = prevSelection;
          }
        }catch(e){
          console.error('model fetch error', e);
          try{
            const cached = window.localStorage.getItem(MODEL_STORAGE_KEY);
            if(!cached && msel) msel.innerHTML = '<option value="">(default)</option><option value="" disabled>(error loading models)</option>';
            // if we have a cached list, render it so refresh doesn't clear UI
            try{ const parsed = cached ? JSON.parse(cached) : null; if(Array.isArray(parsed) && parsed.length){ renderModels(parsed); } }catch(_){ }
          }catch(_){
            if(msel) msel.innerHTML = '<option value="">(default)</option><option value="" disabled>(error loading models)</option>';
          }
        }
      }

      async function submit(){
        const id = document.getElementById('agentSelect').value;
        const goal = document.getElementById('goal').value;
        const context = document.getElementById('context').value;
        const repoPath = document.getElementById('repoPath').value.trim();
        const modelEl = document.getElementById('modelSelect');
        const model = modelEl ? modelEl.value : '';
        if(!id || !goal){ alert('Select agent and provide a goal'); return; }
        const statusEl = document.getElementById('status');
        if(statusEl) statusEl.textContent = 'Submitting...';
        lastSubmittedMs = Date.now();
        const body = { goal: goal };
        if(model) body.model = model;

        let ctx = {};
        if(context){
          try { ctx = JSON.parse(context); } catch (_) { ctx.note = context; }
        }

        if(repoPath){
          ctx.repo_base = repoPath;
          try{
            const listRes = await fetch('/admin/repo/list?path=' + encodeURIComponent(repoPath));
            if(listRes.ok){
              const listData = await listRes.json();
              const files = Array.isArray(listData.result) ? listData.result : [];
              let candidate = null;
              for(const item of files){
                const name = item && item.name ? item.name.toLowerCase() : '';
                if(!item.is_dir && (name.startsWith('readme') || name.endsWith('.md') || name.endsWith('.txt'))){
                  candidate = item.name;
                  break;
                }
              }
              if(!candidate){
                const firstFile = files.find(item => item && !item.is_dir);
                if(firstFile) candidate = firstFile.name;
              }
              if(candidate){
                const filePath = repoPath.replace(/\\/g, '/') .replace(/\/$/, '') + '/' + candidate;
                // Reading file contents from the server is disabled; include only path metadata.
                ctx.repo_snapshot = { path: filePath };
              }
            }
          }catch(e){
            console.warn('repo prefetch failed', e);
          }
        }

        if(Object.keys(ctx).length) body.context = ctx;

        try{
          const res = await fetch('/agents/' + id + '/run', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(body)
          });
          const txt = await res.text();
          if(!res.ok){
            document.getElementById('output').textContent = `Request failed: ${res.status} ${txt}`;
            if(statusEl) statusEl.textContent = 'Error';
            return;
          }
          document.getElementById('output').textContent = 'Queued...';
          if(statusEl) statusEl.textContent = 'Submitted';
          await refreshStatus();
          for(let i = 0; i < 6; i++){
            await new Promise(resolve => setTimeout(resolve, 1500));
            await refreshStatus();
          }
        }catch(e){
          document.getElementById('output').textContent = 'Network/error: ' + e;
          if(statusEl) statusEl.textContent = 'Error';
        }
      }

      async function refreshStatus(){
        const id = document.getElementById('agentSelect').value;
        if(!id) return;
        try{
          const res = await fetch('/agents/' + id + '/status');
          const data = await res.json();
          document.getElementById('queueSize').textContent = data.queue_size;
          const recent = document.getElementById('recent');
          recent.innerHTML = '';
          (data.recent_memories || []).filter(shouldShowInRecent).forEach(m => {
            const d = document.createElement('div');
            d.style.borderTop = '1px solid #ddd';
            d.style.padding = '6px 0';
            d.textContent = (m.created_at ? ('[' + m.created_at + '] ') : '') + (m.content || m.id);
            recent.appendChild(d);
          });
          const display = latestDisplayMemory(data.recent_memories || []);
          if(display){
            setOutput(formatMemoryForOutput(display.content));
          }
        }catch(e){
          console.error(e);
        }
      }

      async function fetchRepoToolState(){
        const status = document.getElementById('repoStatus');
        const toggle = document.getElementById('repoToggle');
        try{
          const res = await fetch('/admin/repo_tool');
          if(!res.ok) throw new Error('status ' + res.status);
          const data = await res.json();
          if(toggle) toggle.checked = !!data.enabled;
          if(status) status.textContent = 'Repo tool: ' + (data.enabled ? 'enabled' : 'disabled') + ' | allowed dirs: ' + (data.allowed_dirs || '-');
        }catch(e){
          if(status) status.textContent = 'Repo tool: unavailable';
        }
      }

      async function setRepoToolState(enabled){
        const status = document.getElementById('repoStatus');
        try{
          const res = await fetch('/admin/repo_tool', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ enabled })
          });
          if(!res.ok) throw new Error('status ' + res.status);
          const data = await res.json();
          if(status) status.textContent = 'Repo tool: ' + (data.enabled ? 'enabled' : 'disabled');
        }catch(e){
          if(status) status.textContent = 'Repo tool: failed to update';
        }
      }

      async function fetchQueue(){
        const out = document.getElementById('queueView');
        out.textContent = 'Loading...';
        try{
          const res = await fetch('/admin/queue');
          if(!res.ok){ out.textContent = 'Failed to fetch queue: ' + res.status; return; }
          const data = await res.json();
          out.innerHTML = `<div style="font-size:12px;margin-bottom:6px"><b>Backend:</b> ${data.backend} <b>Queue:</b> ${data.queue_name}</div>`;
          if(!data.items || data.items.length === 0){ out.innerHTML += '<div style="color:#666">(empty)</div>'; return; }
          data.items.slice(0, 50).forEach(it => {
            const d = document.createElement('div');
            d.style.borderTop = '1px solid #f0f0f0';
            d.style.padding = '6px 0';
            try { d.textContent = JSON.stringify(it); } catch (e) { d.textContent = '' + it; }
            out.appendChild(d);
          });
        }catch(e){
          out.textContent = 'Error: ' + e;
        }
      }

      document.getElementById('refreshStatus').addEventListener('click', refreshStatus);
      document.getElementById('viewQueue').addEventListener('click', fetchQueue);
      document.getElementById('submit').addEventListener('click', async function(e){ await submit(); startPolling(); });
      document.getElementById('refreshModels').addEventListener('click', function(e){ e.preventDefault(); fetchModels(); });
      document.getElementById('repoToggle').addEventListener('change', function(e){ setRepoToolState(!!e.target.checked); });

      // Polling: refresh selected agent's status every 2.5s while an agent is selected.
      let pollIntervalId = null;
      function clearPolling(){ if(pollIntervalId){ clearInterval(pollIntervalId); pollIntervalId = null; } }
      function startPolling(){
        clearPolling();
        const aid = document.getElementById('agentSelect').value;
        if(!aid) return;
        // immediate refresh then periodic
        refreshStatus();
        pollIntervalId = setInterval(() => { refreshStatus(); }, 2500);
      }

      document.getElementById('agentSelect').addEventListener('change', function(){
        refreshStatus();
        const aid = document.getElementById('agentSelect').value;
        if(aid) startPolling(); else clearPolling();
      });

      // stop polling when leaving the page (cleanup)
      window.addEventListener('beforeunload', clearPolling);

      loadAgents();
      fetchModels();
      fetchRepoToolState();
    </script>
  </body>
</html>
    """

    html = html.replace("__INITIAL_AGENTS__", json.dumps(initial_agents))
    return HTMLResponse(content=html)
