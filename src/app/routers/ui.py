from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/playground", response_class=HTMLResponse)
async def agent_playground():
    html = """
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
        try{
          const res = await fetch('/agents/');
          if(!res.ok){
            const txt = await res.text();
            setOutput('Failed to load agents: ' + res.status + ' ' + txt);
            if(sel) sel.innerHTML = '<option value="">(failed to load agents)</option>';
            return;
          }
          const agents = await res.json();
          if(sel) sel.innerHTML = '';
          if(!Array.isArray(agents) || agents.length === 0){
            if(sel) sel.innerHTML = '<option value="">(no agents found)</option>';
          } else {
            agents.forEach(a => {
              const opt = document.createElement('option');
              const aid = a.id || a.file || (a.frontmatter && a.frontmatter.name) || a.name;
              const label = a.name || (a.frontmatter && a.frontmatter.name) || a.summary || a.file || aid;
              opt.value = aid;
              opt.textContent = label;
              sel.appendChild(opt);
            });
          }
          if(btn) btn.disabled = false;
          await refreshStatus();
        }catch(e){
          setOutput('Error loading agents: ' + e);
          if(sel) sel.innerHTML = '<option value="">(error loading agents)</option>';
        }
      }

      async function fetchModels(){
        const msel = document.getElementById('modelSelect');
        if(msel) msel.innerHTML = '<option value="">Loading models...</option>';
        try{
          const [litellmRes, ollamaRes] = await Promise.all([
            fetch('/admin/litellm/models'),
            fetch('/admin/ollama_models')
          ]);

          let models = [];

          if(litellmRes.ok){
            const litellmData = await litellmRes.json();
            models.push(...normalizeModelIds(litellmData));
          }

          if(ollamaRes.ok){
            const ollamaData = await ollamaRes.json();
            const ollamaModels = normalizeModelIds(ollamaData.models).map(id => id.startsWith('ollama:') ? id : ('ollama:' + id));
            models.push(...ollamaModels);
          }

          models = Array.from(new Set(models.filter(Boolean)));

          if(msel) msel.innerHTML = '<option value="">(default)</option>';
          if(msel && models.length){
            models.forEach(model => {
              const opt = document.createElement('option');
              opt.value = model;
              opt.textContent = model;
              msel.appendChild(opt);
            });
          } else if(msel) {
            msel.innerHTML = '<option value="">(default)</option><option value="" disabled>(no models found)</option>';
          }
        }catch(e){
          console.error('model fetch error', e);
          if(msel) msel.innerHTML = '<option value="">(default)</option><option value="" disabled>(error loading models)</option>';
        }
      }
      async function submit(){
        const id = document.getElementById('agentSelect').value;
        const goal = document.getElementById('goal').value;
        const context = document.getElementById('context').value;
        const modelEl = document.getElementById('modelSelect');
        const model = modelEl ? modelEl.value : '';
        if(!id || !goal){ alert('Select agent and provide a goal'); return; }
        const statusEl = document.getElementById('status');
        if(statusEl) statusEl.textContent = 'Submitting...';
        lastSubmittedMs = Date.now();
        const body = { goal: goal };
        if(model) body.model = model;
        if(context) body.context = context;
        try{
          const res = await fetch('/agents/'+id+'/run', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)});
          const txt = await res.text();
          if(!res.ok){
            document.getElementById('output').textContent = `Request failed: ${res.status} ${txt}`;
            if(statusEl) statusEl.textContent = 'Error';
            return;
          }
          // try parse JSON, otherwise show raw text
          let data;
          try{ data = JSON.parse(txt); }catch(_){ data = txt; }
          document.getElementById('output').textContent = 'Queued...';
          if(statusEl) statusEl.textContent = 'Submitted';
          await refreshStatus();
          for(let i = 0; i < 6; i++){
            await new Promise(resolve => setTimeout(resolve, 1500));
            await refreshStatus();
          }
        }catch(e){
          document.getElementById('output').textContent = 'Network/error: '+e;
          if(statusEl) statusEl.textContent = 'Error';
        }
      }
      async function refreshStatus(){
        const id = document.getElementById('agentSelect').value;
        if(!id) return;
        try{
          const res = await fetch('/agents/'+id+'/status');
          const data = await res.json();
          document.getElementById('queueSize').textContent = data.queue_size;
          const recent = document.getElementById('recent');
          recent.innerHTML = '';
          (data.recent_memories||[]).filter(shouldShowInRecent).forEach(m=>{
            const d = document.createElement('div');
            d.style.borderTop='1px solid #ddd';
            d.style.padding='6px 0';
            d.textContent = (m.created_at?('['+m.created_at+'] '):'') + (m.content||m.id);
            recent.appendChild(d);
          });
          const display = latestDisplayMemory(data.recent_memories || []);
          if(display){
            setOutput(formatMemoryForOutput(display.content));
          }
        }catch(e){ console.error(e); }
      }
      document.getElementById('refreshStatus').addEventListener('click', refreshStatus);
      document.getElementById('viewQueue').addEventListener('click', fetchQueue);
      document.getElementById('submit').addEventListener('click', submit);
      document.getElementById('refreshModels').addEventListener('click', function(e){ e.preventDefault(); fetchModels(); });
      document.getElementById('agentSelect').addEventListener('change', refreshStatus);

      loadAgents();
      fetchModels();
      setInterval(function(){ fetchModels().catch(()=>{}); }, 60000);

      async function fetchQueue(){
        const out = document.getElementById('queueView');
        out.textContent = 'Loading...';
        try{
          const res = await fetch('/admin/queue');
          if(!res.ok){ out.textContent = 'Failed to fetch queue: '+res.status; return; }
          const data = await res.json();
          out.innerHTML = `<div style="font-size:12px;margin-bottom:6px"><b>Backend:</b> ${data.backend} <b>Queue:</b> ${data.queue_name}</div>`;
          if(!data.items || data.items.length===0){ out.innerHTML += '<div style="color:#666">(empty)</div>'; return; }
          data.items.slice(0,50).forEach(it=>{
            const d = document.createElement('div');
            d.style.borderTop='1px solid #f0f0f0';
            d.style.padding='6px 0';
            try{ d.textContent = JSON.stringify(it); }catch(e){ d.textContent = ''+it; }
            out.appendChild(d);
          });
        }catch(e){ out.textContent = 'Error: '+e; }
      }
    </script>
  </body>
</html>
    """
    return HTMLResponse(content=html)
