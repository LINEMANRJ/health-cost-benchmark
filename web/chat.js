/* Chat "Pergunte aos dados" do site (GitHub Pages).
 *
 * Arquitetura (tudo no navegador do visitante):
 *  - Pyodide executa o pacote Python do projeto (mesmas ferramentas testadas do pipeline) sobre a
 *    tabela fato publicada junto com o site;
 *  - o JavaScript conduz o loop de tool use com o provedor escolhido (Claude ou Cohere), usando a
 *    chave de API informada pelo próprio visitante;
 *  - cada resposta passa pela verificação numérica (grounding) em Python antes de ser exibida.
 *
 * Segurança: a chave fica só na memória da página (ou no sessionStorage, se o visitante marcar
 * "lembrar nesta aba") e é enviada exclusivamente ao endpoint do provedor. A Content-Security-Policy
 * da página restringe conexões a esses endpoints. Respostas do modelo são escapadas antes de renderizar.
 */
(() => {
  "use strict";

  const PYODIDE_URL = "pyodide/";
  const MAX_STEPS = 10;
  const PROVIDERS = {
    anthropic: {
      label: "Claude (Anthropic)",
      model: "claude-opus-5",
      keyHint: "sk-ant-…",
      keyUrl: "https://platform.claude.com",
    },
    cohere: {
      label: "Cohere",
      model: "command-a-plus-05-2026",
      keyHint: "chave da Cohere",
      keyUrl: "https://dashboard.cohere.com",
    },
  };

  const $ = (sel) => document.querySelector(sel);
  const state = {
    py: null,
    loading: null,
    busy: false,
    provider: "anthropic",
    conversations: { anthropic: [], cohere: [] },
  };

  // ------------------------------------------------------------------ utilidades de interface
  function setStatus(text, kind = "info") {
    const el = $("#chat-status");
    el.textContent = text;
    el.dataset.kind = kind;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /* Markdown mínimo e seguro: o texto é escapado ANTES de aplicar a formatação. */
  function renderMarkdown(md) {
    const lines = escapeHtml(md).split("\n");
    const out = [];
    let i = 0;
    const inline = (t) => t
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/_\(([^)]+)\)_/g, "<em>($1)</em>");
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*\|.*\|\s*$/.test(line)) {
        const rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
        const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
        const [head, ...rest] = body;
        let html = "<div class='chat-table'><table><thead><tr>" +
          cells(head).map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>";
        html += rest.map((r) => "<tr>" + cells(r).map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("");
        out.push(html + "</tbody></table></div>");
        continue;
      }
      if (/^\s*[-*] /.test(line)) {
        const items = [];
        while (i < lines.length && /^\s*[-*] /.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*] /, ""));
        out.push("<ul>" + items.map((t) => `<li>${inline(t)}</li>`).join("") + "</ul>");
        continue;
      }
      const h = line.match(/^(#{1,4}) (.*)$/);
      if (h) { out.push(`<p><strong>${inline(h[2])}</strong></p>`); i++; continue; }
      if (line.trim() === "") { i++; continue; }
      const para = [];
      while (i < lines.length && lines[i].trim() !== "" && !/^\s*\|/.test(lines[i]) && !/^\s*[-*] /.test(lines[i]) && !/^#{1,4} /.test(lines[i])) {
        para.push(inline(lines[i++]));
      }
      out.push(`<p>${para.join("<br>")}</p>`);
    }
    return out.join("");
  }

  function addMessage(role, html) {
    const log = $("#chat-log");
    const div = document.createElement("div");
    div.className = `chat-msg chat-${role}`;
    div.innerHTML = html;
    log.appendChild(div);
    div.scrollIntoView({ behavior: "smooth", block: "end" });
    return div;
  }

  function renderAnswer(result) {
    const badge = result.ungrounded.length
      ? `<div class="chat-warn">⚠️ Números sem correspondência nas ferramentas: ${result.ungrounded.map(escapeHtml).join(", ")}</div>`
      : `<div class="chat-ok">✅ Todos os números conferem com os resultados das ferramentas.</div>`;
    const calls = result.calls.map((c) => `
      <li>${c.ok ? "✅" : "❌"} <code>${escapeHtml(c.name)}</code> · ${c.duration_ms} ms
        <pre>${escapeHtml(JSON.stringify(c.input, null, 2))}</pre>
        ${c.error ? `<div class="chat-err">Erro devolvido ao modelo: ${escapeHtml(c.error)}</div>` : ""}
      </li>`).join("");
    const usage = `Provedor: ${escapeHtml(PROVIDERS[result.provider].label)} · modelo: ${escapeHtml(result.model)} · ` +
      `etapas: ${result.steps} · tokens de entrada: ${result.usage.input} (cache: ${result.usage.cache}) · saída: ${result.usage.output}`;
    addMessage("assistant", `${renderMarkdown(result.answer || "(sem texto)")}${badge}
      <details><summary>Como cheguei a esta resposta — ${result.calls.length} consulta(s) aos dados</summary>
      <ul class="chat-calls">${calls}</ul><div class="chat-meta">${usage}</div></details>`);
  }

  // ------------------------------------------------------------------ Python (Pyodide)
  async function ensurePython() {
    if (state.py) return state.py;
    if (state.loading) return state.loading;
    state.loading = (async () => {
      setStatus("Carregando o Python no navegador (primeira vez: ~35 MB)…");
      const pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
      setStatus("Carregando pandas e SciPy…");
      await pyodide.loadPackage(["pandas", "scipy"]);
      setStatus("Carregando o código do projeto e os dados…");
      const [pkg, data, bridge] = await Promise.all([
        fetch("py/hcb.zip").then((r) => { if (!r.ok) throw new Error("pacote hcb"); return r.arrayBuffer(); }),
        fetch("data/fato_internacoes.csv").then((r) => { if (!r.ok) throw new Error("dados"); return r.text(); }),
        fetch("py/bridge.py").then((r) => { if (!r.ok) throw new Error("bridge"); return r.text(); }),
      ]);
      pyodide.unpackArchive(pkg, "zip", { extractDir: "/home/pyodide/pkg" });
      pyodide.FS.writeFile("/home/pyodide/fato.csv", data);
      await pyodide.runPythonAsync(bridge);
      state.py = {
        systemPrompt: pyodide.globals.get("SYSTEM_PROMPT"),
        tools: {
          anthropic: JSON.parse(pyodide.globals.get("ANTHROPIC_TOOLS")),
          cohere: JSON.parse(pyodide.globals.get("COHERE_TOOLS")),
        },
        runTool: (name, args) => JSON.parse(pyodide.globals.get("run_tool")(name, JSON.stringify(args ?? {}))),
        check: (answer) => JSON.parse(pyodide.globals.get("check_answer")(answer)),
        reset: () => pyodide.globals.get("reset")(),
      };
      setStatus("Pronto. Faça uma pergunta.", "ok");
      return state.py;
    })();
    try {
      return await state.loading;
    } catch (err) {
      state.loading = null;
      throw err;
    }
  }

  // ------------------------------------------------------------------ provedores
  class ApiError extends Error {}

  async function postJson(url, headers, body) {
    let resp;
    try {
      resp = await fetch(url, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
    } catch (err) {
      throw new ApiError("O navegador não conseguiu acessar a API do provedor (rede, bloqueio ou CORS).");
    }
    let payload = null;
    try { payload = await resp.json(); } catch (_) { /* corpo vazio */ }
    if (!resp.ok) {
      const detail = payload?.error?.message || payload?.message || resp.statusText;
      if (resp.status === 401) throw new ApiError("Chave de API inválida ou ausente.");
      if (resp.status === 403) throw new ApiError("A chave não tem permissão para este modelo.");
      if (resp.status === 429) throw new ApiError("Limite de requisições atingido. Tente novamente em instantes.");
      throw new ApiError(`Erro da API (${resp.status}): ${detail}`);
    }
    return payload;
  }

  /* Claude: Messages API com tool use, cache do prompt e fallback server-side em recusas. */
  async function stepAnthropic(key, model, messages, py) {
    const data = await postJson("https://api.anthropic.com/v1/messages", {
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
      "anthropic-beta": "server-side-fallback-2026-07-01",
      "anthropic-dangerous-direct-browser-access": "true",
    }, {
      model, max_tokens: 16000,
      system: [{ type: "text", text: py.systemPrompt, cache_control: { type: "ephemeral" } }],
      tools: py.tools.anthropic, messages,
      cache_control: { type: "ephemeral" },
      fallbacks: "default",
    });
    messages.push({ role: "assistant", content: data.content });
    const u = data.usage || {};
    const usage = { input: u.input_tokens || 0, output: u.output_tokens || 0, cache: u.cache_read_input_tokens || 0 };
    const text = (data.content || []).filter((b) => b.type === "text").map((b) => b.text).join("\n");
    if (data.stop_reason === "tool_use") {
      const uses = data.content.filter((b) => b.type === "tool_use");
      return { done: false, usage, model: data.model, calls: uses.map((b) => ({ id: b.id, name: b.name, input: b.input || {} })),
        pushResults: (results) => messages.push({ role: "user", content: results.map((r) => ({
          type: "tool_result", tool_use_id: r.id, content: r.ok ? JSON.stringify(r.output) : `Erro: ${r.error}`, ...(r.ok ? {} : { is_error: true }),
        })) }) };
    }
    if (data.stop_reason === "refusal") return { done: true, usage, model: data.model, text: "O modelo recusou esta solicitação. Reformule a pergunta sobre custos hospitalares." };
    if (data.stop_reason === "pause_turn") return { done: false, usage, model: data.model, calls: [], pushResults: () => {} };
    return { done: true, usage, model: data.model, text: text + (data.stop_reason === "max_tokens" ? "\n\n_(Resposta interrompida por limite de tamanho.)_" : "") };
  }

  /* Cohere: Chat v2 com tool use (tool_plan/tool_calls; resultados como documentos). */
  async function stepCohere(key, model, messages, py) {
    if (!messages.length || messages[0].role !== "system") messages.unshift({ role: "system", content: py.systemPrompt });
    const data = await postJson("https://api.cohere.com/v2/chat", { Authorization: `Bearer ${key}` },
      { model, messages, tools: py.tools.cohere, max_tokens: 8000 });
    const tokens = data.usage?.tokens || data.usage?.billed_units || {};
    const usage = { input: tokens.input_tokens || 0, output: tokens.output_tokens || 0, cache: data.usage?.cached_tokens || 0 };
    const msg = data.message || {};
    if (data.finish_reason === "TOOL_CALL" && msg.tool_calls?.length) {
      messages.push({ role: "assistant", tool_plan: msg.tool_plan || "", tool_calls: msg.tool_calls });
      const calls = msg.tool_calls.map((tc) => {
        let input = {};
        try { input = JSON.parse(tc.function.arguments || "{}"); } catch (_) { input = { __argumentos_invalidos__: String(tc.function.arguments).slice(0, 200) }; }
        return { id: tc.id, name: tc.function.name, input: (input && typeof input === "object" && !Array.isArray(input)) ? input : {} };
      });
      return { done: false, usage, model, calls,
        pushResults: (results) => results.forEach((r) => messages.push({ role: "tool", tool_call_id: r.id, content: [{
          type: "document", document: { data: r.ok ? (r.output && typeof r.output === "object" && !Array.isArray(r.output) ? r.output : { resultado: r.output }) : { erro: r.error } },
        }] })) };
    }
    const text = (msg.content || []).filter((c) => c.type === "text").map((c) => c.text).join("");
    messages.push({ role: "assistant", content: text || "(sem texto)" });
    if (data.finish_reason === "ERROR" || data.finish_reason === "TIMEOUT") return { done: true, usage, model, text: "A API da Cohere não concluiu a resposta. Tente novamente." };
    return { done: true, usage, model, text: text + (data.finish_reason === "MAX_TOKENS" ? "\n\n_(Resposta interrompida por limite de tamanho.)_" : "") };
  }

  // ------------------------------------------------------------------ loop do agente
  async function ask(question) {
    const provider = state.provider;
    const key = $("#chat-key").value.trim();
    const model = $("#chat-model").value.trim() || PROVIDERS[provider].model;
    if (!key) { setStatus(`Informe sua chave de API (${PROVIDERS[provider].label}).`, "error"); $("#chat-key").focus(); return; }
    rememberKey();
    state.busy = true;
    toggleInputs(false);
    addMessage("user", `<p>${escapeHtml(question)}</p>`);
    const thinking = addMessage("assistant", "<p class='chat-thinking'>Consultando os dados…</p>");
    const messages = state.conversations[provider];
    const turnStart = messages.length;
    try {
      const py = await ensurePython();
      setStatus("Consultando o modelo…");
      messages.push({ role: "user", content: question });
      const step = provider === "cohere" ? stepCohere : stepAnthropic;
      const result = { provider, model, calls: [], steps: 0, usage: { input: 0, output: 0, cache: 0 }, answer: "", ungrounded: [] };
      while (true) {
        if (result.steps >= MAX_STEPS) {
          messages.push({ role: "assistant", content: "(análise interrompida por limite de etapas)" });
          result.answer = `_(Interrompido após ${MAX_STEPS} etapas. Reformule a pergunta de forma mais específica.)_`;
          break;
        }
        result.steps += 1;
        const r = await step(key, model, messages, py);
        for (const k of ["input", "output", "cache"]) result.usage[k] += r.usage[k];
        result.model = r.model || model;
        if (r.done) { result.answer = r.text; break; }
        const results = r.calls.map((c) => {
          setStatus(`Executando ${c.name}…`);
          const out = py.runTool(c.name, c.input);
          result.calls.push({ name: c.name, input: c.input, ok: out.ok, error: out.error, duration_ms: out.duration_ms });
          return { id: c.id, ...out };
        });
        r.pushResults(results);
      }
      result.ungrounded = py.check(result.answer);
      thinking.remove();
      renderAnswer(result);
      setStatus("Pronto. Faça outra pergunta.", "ok");
    } catch (err) {
      thinking.remove();
      // Fecha o turno para manter o histórico válido (somente acréscimos).
      if (messages.length > turnStart && messages[messages.length - 1].role !== "assistant") {
        messages.push({ role: "assistant", content: "(consulta interrompida por erro)" });
      }
      addMessage("assistant", `<div class="chat-err">${escapeHtml(err instanceof ApiError ? err.message : `Falha: ${err.message || err}`)}</div>`);
      setStatus("Não foi possível concluir. Verifique a mensagem acima.", "error");
    } finally {
      state.busy = false;
      toggleInputs(true);
    }
  }

  // ------------------------------------------------------------------ controles
  function toggleInputs(enabled) {
    for (const el of document.querySelectorAll("#chat-form button, #chat-form input, .chat-example")) el.disabled = !enabled;
  }

  function storageKey() { return `hcb-chat-key-${state.provider}`; }

  function rememberKey() {
    try {
      if ($("#chat-remember").checked) sessionStorage.setItem(storageKey(), $("#chat-key").value.trim());
      else sessionStorage.removeItem(storageKey());
    } catch (_) { /* armazenamento indisponível */ }
  }

  function loadKey() {
    let saved = "";
    try { saved = sessionStorage.getItem(storageKey()) || ""; } catch (_) { /* ignore */ }
    $("#chat-key").value = saved;
    $("#chat-remember").checked = Boolean(saved);
  }

  function selectProvider(p) {
    if (state.provider !== p && $("#chat-log").children.length) {
      addMessage("system", `<p>Provedor alterado para ${escapeHtml(PROVIDERS[p].label)} (histórico separado).</p>`);
    }
    state.provider = p;
    const cfg = PROVIDERS[p];
    $("#chat-model").value = cfg.model;
    $("#chat-key").placeholder = cfg.keyHint;
    $("#chat-key-link").href = cfg.keyUrl;
    $("#chat-key-link").textContent = `Obter chave (${cfg.label})`;
    loadKey();
  }

  function init() {
    if (!$("#chat-app")) return;
    if (typeof loadPyodide !== "function") { setStatus("Chat indisponível: Python no navegador não carregou.", "error"); return; }
    for (const input of document.querySelectorAll("input[name='chat-provider']")) {
      input.addEventListener("change", () => selectProvider(input.value));
    }
    selectProvider("anthropic");
    $("#chat-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const q = $("#chat-input").value.trim();
      if (!q || state.busy) return;
      $("#chat-input").value = "";
      ask(q);
    });
    for (const btn of document.querySelectorAll(".chat-example")) {
      btn.addEventListener("click", () => { if (!state.busy) ask(btn.textContent.trim()); });
    }
    $("#chat-remember").addEventListener("change", rememberKey);
    $("#chat-clear").addEventListener("click", () => {
      state.conversations[state.provider] = [];
      if (state.py) state.py.reset();
      $("#chat-log").innerHTML = "";
      setStatus("Conversa reiniciada.", "info");
    });
    $("#chat-preload").addEventListener("click", () => ensurePython().catch((e) => setStatus(`Falha ao carregar: ${e.message}`, "error")));
    setStatus("O Python do projeto será carregado no navegador na primeira pergunta (~35 MB).");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
