/* Optional AutoClips SaaS interface; does not send original source files.
   Secrets remain on server. Supabase publishable key is public; password/token lives in memory only. */
const e = id => document.getElementById(id);
const ui = {
  api: e("saasApi"), supabase: e("saasSupabase"), publicKey: e("saasPublishable"),
  email: e("saasEmail"), password: e("saasPassword"), feedback: e("saasFeedback"),
  org: e("saasOrg"), orgName: e("saasOrgName"), channel: e("saasChannel"),
  status: e("saasStatus"), credits: e("saasCredits"), count: e("saasBuyCount"),
  title: e("saasTitle"), description: e("saasDescription"), sourceId: e("saasSourceId"), basis: e("saasRightsBasis"), sourceList: e("saasSourceList"), discovery: e("saasDiscoverResults"),
  upload: e("saasUpload"), approve: e("saasApprove")
};
let token = "", userId = "", lastJobId = null, configs = null;
const formatCredits = amount => Number(amount || 0).toLocaleString("pt-BR");
function feedback(message) { ui.feedback.textContent = message; }
function baseUrl(input) {
  try {
    const url = new URL(input.value.trim());
    const local = url.hostname === "127.0.0.1" || url.hostname === "localhost";
    if (url.protocol !== "https:" && !(url.protocol === "http:" && local)) throw Error();
    return url.origin + url.pathname.replace(/\/+$/, "");
  } catch { throw Error("Use URL HTTPS ou localhost para o backend"); }
}
function apiUrl() { return baseUrl(ui.api); }
function authUrl() { return baseUrl(ui.supabase); }
async function request(path, options = {}) {
  if (!token) throw Error("Entre na conta antes de continuar");
  const response = await fetch(apiUrl() + path, {
    ...options,
    headers: { "Authorization": "Bearer " + token,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}) }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.detail || data.message || "HTTP " + response.status);
  return data;
}
function orgId() {
  if (!ui.org.value) throw Error("Selecione uma organização");
  return ui.org.value;
}
async function loadOrgs() {
  const orgs = await request("/v1/organizations");
  ui.org.replaceChildren();
  for (const org of orgs) {
    const opt = document.createElement("option");
    opt.value = org.id; opt.textContent = org.name + " (" + org.role + ")";
    ui.org.append(opt);
  }
  const previous = sessionStorage.getItem("autoclips_saas_org");
  if (previous && orgs.some(o => o.id === previous)) ui.org.value = previous;
  await refreshWorkspace();
}
async function refreshWorkspace() {
  if (!ui.org.value) {
    ui.status.textContent = "Crie uma organização para começar."; return;
  }
  sessionStorage.setItem("autoclips_saas_org", ui.org.value);
  const org = encodeURIComponent(orgId());
  const [wallet, channels, jobs] = await Promise.all([
    request("/v1/wallet?org_id=" + org),
    request("/v1/channels?org_id=" + org),
    request("/v1/jobs?org_id=" + org),
  ]);
  ui.credits.textContent = formatCredits(wallet.available) + " disponíveis · " +
    formatCredits(wallet.reserved) + " reservados";
  ui.channel.replaceChildren();
  for (const channel of channels.filter(c => c.active)) {
    const opt = document.createElement("option");
    opt.value = channel.id;
    opt.textContent = channel.title + " · " + channel.youtube_channel_id;
    ui.channel.append(opt);
  }
  const sources = await request("/v1/sources?org_id=" + org);
  ui.sourceList.replaceChildren();
  for (const source of sources) {
    const opt = document.createElement("option");
    opt.value = source.id; opt.textContent = source.youtube_source_id;
    ui.sourceList.append(opt);
  }
  ui.status.replaceChildren();
  if (!jobs.length) {
    ui.status.textContent = "Nenhuma publicação na fila.";
  } else for (const job of jobs.slice(0, 20)) {
    const item = document.createElement("div");
    item.className = "saas-job";
    const strong = document.createElement("strong");
    strong.textContent = job.title + " — " + job.status;
    const small = document.createElement("small");
    small.textContent = job.youtube_video_id ?
      "ID YouTube: " + job.youtube_video_id : "Crédito: " + job.credit_state;
    item.append(strong, small); ui.status.append(item);
  }
}
e("saasLogin").onclick = async () => {
  try {
    if (!ui.email.value || !ui.password.value) throw Error("Informe e-mail e senha");
    const response = await fetch(authUrl() + "/auth/v1/token?grant_type=password", {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: ui.publicKey.value.trim() },
      body: JSON.stringify({ email: ui.email.value.trim(), password: ui.password.value })
    });
    const data = await response.json();
    if (!response.ok || !data.access_token) throw Error(data.msg || data.error_description || "Login não autorizado");
    token = data.access_token;
    userId = data.user?.id || "";
    ui.password.value = "";
    feedback("Conta autenticada. A sessão fica somente na memória da aba.");
    await loadOrgs();
  } catch (error) { feedback("Login: " + error.message); }
};
e("saasSignup").onclick = async () => {
  try {
    const response = await fetch(authUrl() + "/auth/v1/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: ui.publicKey.value.trim() },
      body: JSON.stringify({ email: ui.email.value.trim(), password: ui.password.value })
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.msg || data.error_description || "Cadastro não autorizado");
    ui.password.value = "";
    feedback("Cadastro recebido. Confirme seu e-mail se a verificação estiver ativada, depois entre.");
  } catch (error) { feedback("Cadastro: " + error.message); }
};
e("saasCreateOrg").onclick = async () => {
  try {
    if (!ui.orgName.value.trim()) throw Error("Informe o nome do espaço de trabalho");
    const org = await request("/v1/organizations", {
      method: "POST", body: JSON.stringify({ name: ui.orgName.value.trim() })
    });
    sessionStorage.setItem("autoclips_saas_org", org.id);
    await loadOrgs();
    feedback("Espaço de trabalho criado.");
  } catch (error) { feedback(error.message); }
};
e("saasConnect").onclick = async () => {
  try {
    const data = await request("/v1/channels/connect", {
      method: "POST", body: JSON.stringify({ org_id: orgId() })
    });
    window.location.assign(data.authorization_url);
  } catch (error) { feedback(error.message); }
};
e("saasRefresh").onclick = async () => {
  try { await refreshWorkspace(); feedback("Dados atualizados."); }
  catch (error) { feedback(error.message); }
};
ui.org.onchange = async () => {
  try { await refreshWorkspace(); } catch (error) { feedback(error.message); }
};
e("saasRegisterSource").onclick = async () => {
  try {
    const channelId = ui.sourceId.value.trim();
    if (!/^UC[A-Za-z0-9_-]{22}$/.test(channelId)) throw Error("Informe um ID de canal UC... válido.");
    if (ui.basis.value.trim().length < 3) throw Error("Descreva a base de autorização de uso.");
    await request("/v1/sources", {
      method: "POST",
      body: JSON.stringify({
        org_id: orgId(), youtube_channel_id: channelId,
        authorization_basis: ui.basis.value.trim()
      })
    });
    await refreshWorkspace();
    feedback("Origem cadastrada. Somente os IDs e metadados serão descobertos.");
  } catch (error) { feedback(error.message); }
};
e("saasDiscover").onclick = async () => {
  try {
    if (!ui.sourceList.value) throw Error("Cadastre uma origem.");
    if (!ui.channel.value) throw Error("Conecte um canal Google para consultar metadados.");
    const qs = new URLSearchParams({ org_id: orgId(), connected_channel_id: ui.channel.value });
    const result = await request("/v1/sources/" + ui.sourceList.value + "/discover?" + qs.toString(), {
      method: "POST"
    });
    const rows = await request("/v1/sources/" + ui.sourceList.value +
      "/videos?org_id=" + encodeURIComponent(orgId()));
    ui.discovery.replaceChildren();
    for (const video of rows.slice(0, 15)) {
      const div = document.createElement("div");
      div.textContent = video.title + " · " + video.youtube_video_id + " · aguardando original autorizado";
      ui.discovery.append(div);
    }
    feedback("Encontrados " + result.discovered + " IDs. Nenhum vídeo original foi baixado.");
  } catch (error) { feedback("Descoberta: " + error.message); }
};
e("saasCheckout").onclick = async () => {
  try {
    const credits = Number(ui.count.value);
    if (!Number.isInteger(credits) || credits < 100 || credits > 100000)
      throw Error("Pacote permitido: 100 a 100.000 créditos");
    const data = await request("/v1/billing/checkout", {
      method: "POST", body: JSON.stringify({ org_id: orgId(), credits })
    });
    window.location.assign(data.checkout_url);
  } catch (error) { feedback(error.message); }
};
function localExport() {
  const result = window.autoclipsLocalGetExport?.();
  if (!result?.blob || result.blob.size < 1024) throw Error("Gere um corte MP4 neste editor antes de enviar");
  if (result.blob.type !== "video/mp4" || !result.name.endsWith(".mp4"))
    throw Error("Seu navegador exportou WebM. O uploader exige MP4 H.264/AAC; use navegador compatível.");
  if (result.blob.size > 256 * 1024 * 1024)
    throw Error("Arquivo acima de 256 MB: upload local grande ainda não homologado.");
  return result;
}
function hex(bytes) {
  return Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, "0")).join("");
}
ui.upload.onclick = async () => {
  ui.upload.disabled = true;
  try {
    const result = localExport();
    if (!ui.channel.value) throw Error("Conecte primeiro um canal de destino");
    if (!e("rights").checked) throw Error("Confirme os direitos do material no editor.");
    feedback("Calculando SHA-256 localmente...");
    const sha256 = hex(await crypto.subtle.digest("SHA-256", await result.blob.arrayBuffer()));
    const stableClientKey = "sha256:" + sha256 + ":channel:" + ui.channel.value;
    const created = await request("/v1/exports", {
      method: "POST", body: JSON.stringify({
        org_id: orgId(), channel_id: ui.channel.value,
        client_key: stableClientKey, sha256, size_bytes: result.blob.size,
        title: ui.title.value || result.name.slice(0, 100), description: ui.description.value || ""
      })
    });
    const id = created.job.id;
    lastJobId = id;
    if (created.already_uploaded && created.job.status !== "ready") {
      ui.approve.disabled = true;
      feedback("Esta publicação já existe no canal (" + created.job.status + "). Nova postagem duplicada bloqueada.");
      await refreshWorkspace();
      return;
    }
    if (!created.already_uploaded) {
      feedback("Enviando somente o MP4 final ao bucket privado...");
      const response = await fetch(created.upload_url, {
        method: "PUT", body: result.blob, headers: created.required_headers
      });
      if (!response.ok) throw Error("Upload ao bucket falhou: " + response.status);
      await request("/v1/exports/" + encodeURIComponent(id) + "/complete", {
        method: "POST", body: JSON.stringify({ org_id: orgId() })
      });
    }
    ui.approve.disabled = false;
    feedback("MP4 final recebido. Revise o conteúdo antes de aprovar postagem privada (1 crédito).");
    await refreshWorkspace();
  } catch (error) { feedback("Exportação SaaS: " + error.message); }
  finally { ui.upload.disabled = false; }
};
ui.approve.onclick = async () => {
  try {
    if (!lastJobId) throw Error("Envie um corte para revisão primeiro.");
    if (!e("saasApprovalCheck").checked) throw Error("Marque a confirmação explícita da publicação privada.");
    await request("/v1/jobs/" + encodeURIComponent(lastJobId) + "/approve", {
      method: "POST",
      body: JSON.stringify({ org_id: orgId(), rights_confirmed: true, visibility: "private" })
    });
    ui.approve.disabled = true;
    feedback("Publicação privada enfileirada. Um crédito foi reservado; será consumido após confirmação do YouTube.");
    await refreshWorkspace();
  } catch (error) { feedback(error.message); }
};
(async () => {
  try {
    const res = await fetch("./saas-config.json", { cache: "no-store" });
    if (!res.ok) return;
    configs = await res.json();
    if (configs.apiUrl) ui.api.value = configs.apiUrl;
    if (configs.supabaseUrl) ui.supabase.value = configs.supabaseUrl;
    if (configs.supabasePublishableKey) ui.publicKey.value = configs.supabasePublishableKey;
  } catch { /* Standalone local proof remains usable without SaaS config. */ }
  if (new URLSearchParams(location.search).get("google")) {
    feedback("Autorização Google finalizada. Faça login novamente para conferir o canal.");
  }
})();
