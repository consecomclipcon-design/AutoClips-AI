/* AutoClips zero-media browser client.
   NEVER send original video, final MP4, YouTube OAuth token or resumable URL to our storage.
   Media bytes go only from this browser to Google's YouTube upload API.
   The SaaS API receives JSON metadata and transient access token for channel verification.
*/
const e = (id) => document.getElementById(id);
const ui = {
  api: e("saasApi"), supabase: e("saasSupabase"), publicKey: e("saasPublishable"),
  googleClientId: e("saasGoogleClientId"), email: e("saasEmail"), password: e("saasPassword"),
  feedback: e("saasFeedback"), org: e("saasOrg"), orgName: e("saasOrgName"),
  channel: e("saasChannel"), status: e("saasStatus"), credits: e("saasCredits"),
  count: e("saasBuyCount"), title: e("saasTitle"), description: e("saasDescription"),
  sourceId: e("saasSourceId"), basis: e("saasRightsBasis"),
  sourceList: e("saasSourceList"), discovery: e("saasDiscoverResults"),
  prepare: e("saasPrepare"), publish: e("saasPublish"),
  progress: e("saasPublishProgress"), reconcileJob: e("saasReconcileJob"),
  reconcileVideoId: e("saasReconcileVideoId")
};
const YOUTUBE_READ = "https://www.googleapis.com/auth/youtube.readonly";
const YOUTUBE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload";
let session = null, lastPrepared = null, channels = new Map();
let googleAccess = null;
const fmt = n => Number(n || 0).toLocaleString("pt-BR");
function feedback(message) {
  ui.feedback.textContent = String(message);
  window.dispatchEvent(new CustomEvent("autoclips:feedback", {detail:{message:String(message)}}));
}
function safeUrl(element) {
  let u;
  try { u = new URL(element.value.trim()); } catch { throw Error("Informe uma URL válida"); }
  const local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
  if (u.protocol !== "https:" && !(u.protocol === "http:" && local)) {
    throw Error("A API e autenticação devem usar HTTPS fora do localhost.");
  }
  return u.origin + u.pathname.replace(/\/+$/, "");
}
function orgId() {
  if (!ui.org.value) throw Error("Selecione um espaço de trabalho.");
  return ui.org.value;
}
async function api(path, opts = {}) {
  if (!session) throw Error("Entre na sua conta AutoClips primeiro.");
  const headers = { Authorization: "Bearer " + session, ...(opts.headers || {}) };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(safeUrl(ui.api) + path, { ...opts, headers });
  const result = await response.json().catch(() => ({}));
  if (response.status === 402) window.dispatchEvent(new Event("autoclips:credits-exhausted"));
  if (!response.ok) throw Error(result.detail || "Erro HTTP " + response.status);
  return result;
}
async function loadOrgs() {
  const rows = await api("/v1/organizations");
  const oldValue = ui.org.value;
  ui.org.replaceChildren();
  for (const org of rows) {
    const option = document.createElement("option");
    option.value = org.id; option.textContent = org.name + " (" + org.role + ")";
    ui.org.append(option);
  }
  if (rows.some(org => org.id === oldValue)) ui.org.value = oldValue;
  await refreshWorkspace();
}
async function refreshWorkspace() {
  if (!ui.org.value) {
    ui.credits.textContent = "Crie um espaço de trabalho.";
    ui.status.replaceChildren(); return;
  }
  const org = encodeURIComponent(orgId());
  const [wallet, linked, jobs, sources] = await Promise.all([
    api("/v1/wallet?org_id=" + org),
    api("/v1/channels?org_id=" + org),
    api("/v1/jobs?org_id=" + org),
    api("/v1/sources?org_id=" + org),
  ]);
  channels = new Map(linked.filter(c => c.active).map(c => [c.id, c]));
  ui.credits.textContent = fmt(wallet.available) + " disponíveis · " + fmt(wallet.reserved) + " reservados";
  window.dispatchEvent(new CustomEvent("autoclips:wallet", {detail:{wallet,jobs}}));
  const selectedChannel = ui.channel.value, selectedSource = ui.sourceList.value;
  ui.channel.replaceChildren();
  for (const channel of channels.values()) {
    const opt = document.createElement("option");
    opt.value = channel.id; opt.textContent = channel.title + " · " + channel.youtube_channel_id;
    ui.channel.append(opt);
  }
  if (channels.has(selectedChannel)) ui.channel.value = selectedChannel;
  ui.sourceList.replaceChildren();
  for (const source of sources) {
    const opt = document.createElement("option");
    opt.value = source.id; opt.textContent = source.youtube_source_id;
    ui.sourceList.append(opt);
  }
  if (sources.some(x => x.id === selectedSource)) ui.sourceList.value = selectedSource;
  const selectedRecon = ui.reconcileJob.value;
  ui.reconcileJob.replaceChildren();
  for (const issue of jobs.filter(j => j.status === "needs_reconciliation" || j.status === "uploading")) {
    const opt = document.createElement("option");
    opt.value = issue.id;
    opt.textContent = issue.title + " · " + issue.status;
    ui.reconcileJob.append(opt);
  }
  if (jobs.some(j => j.id === selectedRecon)) ui.reconcileJob.value = selectedRecon;
  ui.status.replaceChildren();
  if (!jobs.length) ui.status.textContent = "Nenhuma publicação registrada.";
  for (const job of jobs.slice(0, 20)) {
    const div = document.createElement("div"); div.className = "saas-job";
    const strong = document.createElement("strong");
    strong.textContent = job.title + " · " + job.status;
    const details = document.createElement("small");
    details.textContent = (channels.get(job.channel_id)?.title || "Canal") +
      " · crédito " + job.credit_state +
      (job.youtube_video_id ? " · YouTube ID " + job.youtube_video_id : "");
    div.append(strong, details); ui.status.append(div);
  }
}
function ensureGoogle(scopeList) {
  const clientId = ui.googleClientId.value.trim();
  if (!/^[0-9]+-[a-z0-9-]+\.apps\.googleusercontent\.com$/.test(clientId))
    throw Error("Informe o Google OAuth Client ID público válido.");
  if (!window.google?.accounts?.oauth2?.initTokenClient)
    throw Error("Biblioteca oficial de autorização do Google indisponível. Reabra a página com internet.");
  return new Promise((resolve, reject) => {
    const scopes = scopeList.join(" ");
    const tokenClient = google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: scopes,
      callback: response => {
        if (response.error || !response.access_token) {
          reject(Error("Google não concedeu autorização: " + (response.error || "sem acesso")));
          return;
        }
        if (!google.accounts.oauth2.hasGrantedAllScopes(response, ...scopeList)) {
          reject(Error("Google não concedeu todos os escopos exigidos."));
          return;
        }
        googleAccess = { token: response.access_token,
          expiresAt: Date.now() + Math.max(0, Number(response.expires_in || 3600) - 60) * 1000,
          scopes: response.scope || "" };
        resolve(googleAccess.token);
      },
      error_callback: () => reject(Error("Autorização do Google cancelada ou bloqueada pelo navegador.")),
    });
    // MUST be invoked synchronously from a real button click.
    tokenClient.requestAccessToken({ prompt: "consent" });
  });
}
function activeGoogleToken(required) {
  if (!googleAccess || googleAccess.expiresAt <= Date.now())
    throw Error("Sua autorização Google expirou. Use o botão do Google novamente.");
  for (const scope of required) {
    if (!googleAccess.scopes.split(/\s+/).includes(scope)) throw Error("Permissão Google insuficiente.");
  }
  return googleAccess.token;
}
async function youtubeGet(resource, params, token) {
  const endpoint = new URL("https://www.googleapis.com/youtube/v3/" + resource);
  for (const [k, v] of Object.entries(params)) endpoint.searchParams.set(k, String(v));
  const response = await fetch(endpoint.toString(), {
    headers: { Authorization: "Bearer " + token },
  });
  if (!response.ok) throw Error("Google API retornou HTTP " + response.status);
  return response.json();
}
async function selectGoogleChannel(token) {
  const data = await youtubeGet("channels", { part: "snippet", mine: "true", maxResults: 50 }, token);
  const rows = (data.items || []).filter(x => /^UC[A-Za-z0-9_-]{22}$/.test(x.id));
  if (!rows.length) throw Error("Nenhum canal disponível nesta autorização Google.");
  // Authorization can represent just one Brand Account/channel, depending on user's selection.
  // Never guess destination from the user's previously connected channels.
  return rows;
}
e("saasLogin").onclick = async () => {
  try {
    const response = await fetch(safeUrl(ui.supabase) + "/auth/v1/token?grant_type=password", {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: ui.publicKey.value.trim() },
      body: JSON.stringify({ email: ui.email.value.trim(), password: ui.password.value }),
    });
    const data = await response.json();
    if (!response.ok || !data.access_token) throw Error(data.msg || "Credenciais inválidas");
    session = data.access_token;
    ui.password.value = "";
    lastPrepared = null; ui.publish.disabled = true;
    feedback("Autenticado. Sua sessão fica somente na memória desta aba.");
    await loadOrgs();
  } catch (err) { feedback("Login: " + err.message); }
};
e("saasSignup").onclick = async () => {
  try {
    const response = await fetch(safeUrl(ui.supabase) + "/auth/v1/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: ui.publicKey.value.trim() },
      body: JSON.stringify({ email: ui.email.value.trim(), password: ui.password.value }),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.msg || "Cadastro indisponível.");
    ui.password.value = "";
    feedback("Cadastro recebido. Verifique o e-mail e depois entre.");
  } catch (err) { feedback("Cadastro: " + err.message); }
};
e("saasCreateOrg").onclick = async () => {
  try {
    const org = await api("/v1/organizations", {
      method: "POST", body: JSON.stringify({ name: ui.orgName.value.trim() }),
    });
    await loadOrgs(); ui.org.value = org.id; await refreshWorkspace();
    feedback("Espaço de trabalho criado.");
  } catch (err) { feedback(err.message); }
};
e("saasRefresh").onclick = async () => {
  try { await refreshWorkspace(); feedback("Metadados atualizados; nenhum vídeo foi transferido ao SaaS."); }
  catch (err) { feedback(err.message); }
};
ui.org.onchange = () => {
  lastPrepared = null; ui.publish.disabled = true;
  refreshWorkspace().catch(err => feedback(err.message));
};
e("saasConnect").onclick = async () => {
  try {
    if (!session || !ui.org.value) throw Error("Entre na conta e escolha o espaço de trabalho.");
    const token = await ensureGoogle([YOUTUBE_READ]);
    const googleChannels = await selectGoogleChannel(token);
    for (const channel of googleChannels) {
      await api("/v1/channels/register", {
        method: "POST", headers: { "X-YouTube-Access-Token": token },
        body: JSON.stringify({ org_id: orgId(), youtube_channel_id: channel.id }),
      });
    }
    await refreshWorkspace();
    feedback("Canal(is) registrado(s). Nenhum token Google permanente foi armazenado no AutoClips.");
  } catch (err) { feedback("Google: " + err.message); }
};
e("saasRegisterSource").onclick = async () => {
  try {
    const channelId = ui.sourceId.value.trim();
    if (!/^UC[A-Za-z0-9_-]{22}$/.test(channelId)) throw Error("Informe um ID UC... válido.");
    if (ui.basis.value.trim().length < 3) throw Error("Descreva a autorização do conteúdo.");
    await api("/v1/sources", {
      method: "POST",
      body: JSON.stringify({ org_id: orgId(), youtube_channel_id: channelId,
        authorization_basis: ui.basis.value.trim() }),
    });
    await refreshWorkspace();
    feedback("Fonte registrada. A descoberta de metadados não autoriza baixar conteúdo.");
  } catch (err) { feedback(err.message); }
};
e("saasDiscover").onclick = async () => {
  try {
    if (!ui.sourceList.value) throw Error("Cadastre uma origem primeiro.");
    if (!session) throw Error("Entre na conta.");
    // Obtaining a token here requires direct Google consent user gesture.
    const token = await ensureGoogle([YOUTUBE_READ]);
    const qs = new URLSearchParams({ org_id: orgId() });
    const found = await api("/v1/sources/" + ui.sourceList.value + "/discover?" + qs.toString(), {
      method: "POST", headers: { "X-YouTube-Access-Token": token },
    });
    const items = await api("/v1/sources/" + ui.sourceList.value +
      "/videos?org_id=" + encodeURIComponent(orgId()));
    ui.discovery.replaceChildren();
    for (const item of items.slice(0, 15)) {
      const div = document.createElement("div");
      div.textContent = item.title + " · " + item.youtube_video_id +
        " · aguardando arquivo autorizado do cliente";
      ui.discovery.append(div);
    }
    feedback("Descobertos " + found.discovered + " IDs, sem fazer download dos vídeos.");
  } catch (err) { feedback("Descoberta: " + err.message); }
};
e("saasCheckout").onclick = async () => {
  try {
    const credits = Number(ui.count.value);
    if (!Number.isInteger(credits) || credits < 100 || credits > 100000) throw Error("Escolha entre 100 e 100.000 créditos.");
    const result = await api("/v1/billing/checkout", {
      method: "POST", body: JSON.stringify({ org_id: orgId(), credits }),
    });
    location.assign(result.checkout_url);
  } catch (err) { feedback("Pagamento: " + err.message); }
};
function getLocalExport() {
  const output = window.autoclipsLocalGetExport?.();
  if (!output?.blob || output.blob.size < 1024) throw Error("Gere o corte no editor primeiro.");
  if (output.blob.type !== "video/mp4" && output.blob.type !== "video/webm") {
    throw Error("Formato não suportado para envio direto ao YouTube.");
  }
  if (output.blob.size > 256 * 1024 * 1024) {
    throw Error("MVP limitado a 256 MB por corte. Salve localmente e tente outro formato/tamanho.");
  }
  return output;
}
function shaHex(buffer) {
  return Array.from(new Uint8Array(buffer), item => item.toString(16).padStart(2, "0")).join("");
}
ui.prepare.onclick = async () => {
  ui.prepare.disabled = true;
  try {
    const output = getLocalExport();
    if (!e("saasApprovalCheck").checked) throw Error("Revise a prévia e confirme direitos e publicação privada.");
    const channel = channels.get(ui.channel.value);
    if (!channel) throw Error("Conecte um canal de destino.");
    feedback("Calculando assinatura do corte LOCAL, sem enviar bytes ao SaaS.");
    const sha = shaHex(await crypto.subtle.digest("SHA-256", await output.blob.arrayBuffer()));
    const clientKey = "sha256:" + sha + ":channel:" + channel.youtube_channel_id;
    const job = await api("/v1/jobs", {
      method: "POST", body: JSON.stringify({
        org_id: orgId(), channel_id: channel.id, client_key: clientKey,
        sha256: sha, size_bytes: output.blob.size,
        title: (ui.title.value.trim() || output.name).slice(0, 100),
        description: ui.description.value.slice(0, 5000),
      }),
    });
    if (job.status === "published" || job.status === "uploading" ||
        job.status === "needs_reconciliation" || job.status === "cancelled") {
      throw Error("Esta publicação já está em estado " + job.status +
        ". O envio duplicado foi bloqueado; consulte histórico/reconciliação.");
    }
    const reserved = await api("/v1/jobs/" + job.id + "/approve", {
      method: "POST",
      body: JSON.stringify({ org_id: orgId(), rights_confirmed: true, visibility: "private" }),
    });
    lastPrepared = { jobId: job.id, blob: output.blob, mime: output.blob.type,
      channel, title: (ui.title.value.trim() || output.name).slice(0, 100),
      description: ui.description.value.slice(0, 5000) };
    ui.publish.disabled = false;
    await refreshWorkspace();
    feedback("1 crédito reservado. Clique em 'Enviar diretamente ao YouTube' para consentir no Google.");
  } catch (err) { feedback("Preparação: " + err.message); }
  finally { ui.prepare.disabled = false; }
};

function safeResumableUrl(url) {
  const u = new URL(url);
  if (u.protocol !== "https:" || u.hostname !== "www.googleapis.com" ||
      !u.pathname.startsWith("/upload/youtube/v3/videos")) {
    throw Error("Sessão do YouTube inválida ou destino inseguro.");
  }
  return u.toString();
}
async function initiateYoutubeUpload(blob, token, title, description) {
  const endpoint = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json; charset=UTF-8",
      "X-Upload-Content-Type": blob.type,
      "X-Upload-Content-Length": String(blob.size),
    },
    body: JSON.stringify({
      snippet: { title, description },
      status: { privacyStatus: "private" },
    }),
  });
  if (!response.ok) throw Error("YouTube recusou iniciar upload: HTTP " + response.status);
  const location = response.headers.get("Location");
  if (!location) throw Error("A resposta CORS do YouTube não expôs a sessão resumível.");
  return safeResumableUrl(location);
}
async function resumeYoutubeUpload(sessionUrl, blob, token, currentResponse = null) {
  let response = currentResponse;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (!response || response.status !== 308) {
      response = await fetch(sessionUrl, {
        method: "PUT",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Range": "bytes */" + blob.size,
        },
      });
    }
    if (response.status === 200 || response.status === 201) return response.json();
    if (response.status !== 308) throw Error("Upload incerto: HTTP " + response.status);
    const range = response.headers.get("Range") || "";
    const match = /^bytes=0-(\d+)$/.exec(range);
    const offset = match ? Number(match[1]) + 1 : 0;
    if (!Number.isSafeInteger(offset) || offset < 0 || offset >= blob.size) {
      throw Error("YouTube retornou deslocamento inválido; verificar manualmente.");
    }
    feedback("Retomando envio ao YouTube pelo mesmo identificador de sessão: " +
      Math.round((offset / blob.size) * 100) + "%");
    response = await fetch(sessionUrl, {
      method: "PUT",
      headers: {
        Authorization: "Bearer " + token,
        "Content-Type": blob.type,
        "Content-Range": "bytes " + offset + "-" + (blob.size - 1) + "/" + blob.size,
      },
      body: blob.slice(offset),
    });
    if (response.status === 200 || response.status === 201) return response.json();
  }
  throw Error("Envio ainda incerto após tentativa limitada de retomada.");
}
async function sendDirectToYoutube(prepared, token, title, description) {
  // This function is intentionally the ONLY media network path in the SaaS browser client.
  // No fetch to our API is ever made with prepared.blob as body.
  const sessionUrl = await initiateYoutubeUpload(prepared.blob, token, title, description);
  ui.progress.value = 8;
  const uploadResponse = await fetch(sessionUrl, {
    method: "PUT",
    headers: { Authorization: "Bearer " + token, "Content-Type": prepared.mime },
    body: prepared.blob,
  });
  if (uploadResponse.status === 200 || uploadResponse.status === 201) {
    ui.progress.value = 100;
    return uploadResponse.json();
  }
  const result = await resumeYoutubeUpload(sessionUrl, prepared.blob, token, uploadResponse);
  ui.progress.value = 100;
  return result;
}
ui.publish.onclick = async () => {
  if (!lastPrepared) { feedback("Prepare primeiro uma publicação e mantenha o corte aberto."); return; }
  ui.publish.disabled = true;
  const prepared = lastPrepared;
  let began = false;
  let remoteVideoId = null;
  try {
    // Google popup is immediately initiated by the button's user gesture.
    const token = await ensureGoogle([YOUTUBE_READ, YOUTUBE_UPLOAD]);
    const owned = await selectGoogleChannel(token);
    if (!owned.some(row => row.id === prepared.channel.youtube_channel_id))
      throw Error("A conta Google selecionada NÃO corresponde ao canal de destino. Upload bloqueado.");
    if (!e("saasApprovalCheck").checked) throw Error("Confirmação de direitos não está marcada.");
    const title = prepared.title;
    const description = prepared.description;
    await api("/v1/jobs/" + prepared.jobId + "/begin", {
      method: "POST", body: JSON.stringify({ org_id: orgId() }),
    });
    began = true;
    feedback("O navegador está enviando o corte DIRETAMENTE ao YouTube; mantenha esta aba aberta.");
    ui.progress.value = 0;
    const result = await sendDirectToYoutube(prepared, token, title, description);
    if (!/^[A-Za-z0-9_-]{11}$/.test(result?.id || "")) {
      throw Error("YouTube não retornou ID válido; envio precisa ser reconciliado.");
    }
    remoteVideoId = result.id;
    const confirmed = await api("/v1/jobs/" + prepared.jobId + "/complete", {
      method: "POST",
      headers: { "X-YouTube-Access-Token": token },
      body: JSON.stringify({ org_id: orgId(), youtube_video_id: remoteVideoId }),
    });
    feedback("Publicado em modo privado. ID YouTube: " +
      confirmed.youtube_video_id + ". Um crédito consumido após confirmação oficial.");
    lastPrepared = null;
    await refreshWorkspace();
  } catch (err) {
    if (began) {
      try {
        await api("/v1/jobs/" + prepared.jobId + "/uncertain", {
          method: "POST", body: JSON.stringify({ org_id: orgId() }),
        });
      } catch { /* no assumption that the server received the update */ }
      feedback("Envio precisa de reconciliação: " + err.message +
        (remoteVideoId ? " · YouTube ID: " + remoteVideoId : "") +
        ". NÃO reenviar como novo vídeo automaticamente.");
    } else {
      ui.publish.disabled = false;
      feedback("Envio não iniciado: " + err.message + ". Crédito permanece reservado.");
    }
    await refreshWorkspace().catch(() => {});
  }
};
e("saasReconcile").onclick = async () => {
  try {
    if (!ui.reconcileJob.value) throw Error("Nenhum trabalho aguardando reconciliação.");
    if (!/^[A-Za-z0-9_-]{11}$/.test(ui.reconcileVideoId.value.trim()))
      throw Error("Informe exatamente o ID YouTube de 11 caracteres.");
    if (!session) throw Error("Entre na sua conta primeiro.");
    // A short-lived Google read token is required to verify actual channel ownership.
    const token = await ensureGoogle([YOUTUBE_READ]);
    const result = await api("/v1/jobs/" + ui.reconcileJob.value + "/complete", {
      method: "POST",
      headers: { "X-YouTube-Access-Token": token },
      body: JSON.stringify({
        org_id: orgId(), youtube_video_id: ui.reconcileVideoId.value.trim()
      }),
    });
    await refreshWorkspace();
    feedback("Publicação privada confirmada pelo Google. ID " + result.youtube_video_id +
      "; 1 crédito capturado sem reenviar o vídeo.");
  } catch (error) { feedback("Reconciliação: " + error.message); }
};
e("saasLogout").onclick = () => {
  if (googleAccess?.token && window.google?.accounts?.oauth2?.revoke) {
    try { google.accounts.oauth2.revoke(googleAccess.token, () => {}); } catch {}
  }
  session = null; googleAccess = null; lastPrepared = null;
  ui.publish.disabled = true;
  ui.password.value = "";
  ui.org.replaceChildren(); ui.channel.replaceChildren(); ui.sourceList.replaceChildren();
  ui.reconcileJob.replaceChildren(); ui.status.replaceChildren();
  ui.credits.textContent = "Sessão encerrada.";
  feedback("Você saiu. Nenhum vídeo foi enviado nem apagado do computador.");
};
(async () => {
  try {
    const response = await fetch("./saas-config.json", { cache: "no-store" });
    if (!response.ok) return;
    const conf = await response.json();
    if (conf.apiUrl) ui.api.value = conf.apiUrl;
    if (conf.supabaseUrl) ui.supabase.value = conf.supabaseUrl;
    if (conf.supabasePublishableKey) ui.publicKey.value = conf.supabasePublishableKey;
    if (conf.googleClientId) ui.googleClientId.value = conf.googleClientId;
  } catch {}
})();
