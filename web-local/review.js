/* Mobile review: no local source file access and no tokens persisted. */
const el = id => document.getElementById(id);
const ui = {
  api: el("api"), authUrl: el("authUrl"), publishable: el("publishable"),
  email: el("email"), password: el("password"), org: el("org"), feedback: el("feedback"),
  credits: el("credits"), items: el("items"), preview: el("preview"),
  desc: el("previewDescription"), rights: el("rights"), approve: el("approve")
};
let session = null, active = null, channels = new Map();
function feedback(message) { ui.feedback.textContent = message; }
function url(input) {
  const parsed = new URL(input.value.trim());
  if (parsed.protocol !== "https:" && !(
    parsed.protocol === "http:" && ["localhost", "127.0.0.1"].includes(parsed.hostname)))
    throw Error("Use HTTPS ou localhost");
  return parsed.origin + parsed.pathname.replace(/\/$/, "");
}
async function api(path, options = {}) {
  if (!session) throw Error("Entre na sua conta primeiro.");
  const response = await fetch(url(ui.api) + path, {
    ...options,
    headers: { Authorization: "Bearer " + session,
      ...(options.body ? { "Content-Type": "application/json" } : {}) }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.detail || "HTTP " + response.status);
  return data;
}
async function refresh() {
  if (!session || !ui.org.value) return;
  const orgId = ui.org.value;
  const [wallet, linked, jobs] = await Promise.all([
    api("/v1/wallet?org_id=" + encodeURIComponent(orgId)),
    api("/v1/channels?org_id=" + encodeURIComponent(orgId)),
    api("/v1/jobs?org_id=" + encodeURIComponent(orgId)),
  ]);
  channels = new Map(linked.map(channel => [channel.id, channel]));
  ui.credits.textContent = wallet.available + " créditos disponíveis · " +
    wallet.reserved + " reservados";
  ui.items.replaceChildren();
  if (!jobs.length) ui.items.textContent = "Ainda não há publicações.";
  for (const job of jobs) {
    const box = document.createElement("div"); box.className = "item";
    const title = document.createElement("h3"); title.textContent = job.title;
    const info = document.createElement("small");
    info.textContent = (channels.get(job.channel_id)?.title || "Canal") +
      " · " + job.status + " · " + job.credit_state;
    const btn = document.createElement("button");
    btn.className = "secondary"; btn.textContent = "Ver corte";
    btn.disabled = job.status === "awaiting_media";
    btn.onclick = async () => {
      try {
        ui.preview.removeAttribute("src"); ui.preview.load();
        ui.rights.checked = false;
        ui.approve.disabled = job.status !== "ready";
        active = job;
        const data = await api("/v1/jobs/" + encodeURIComponent(job.id) + "/preview?org_id=" + encodeURIComponent(orgId));
        ui.preview.src = data.preview_url; ui.preview.load();
        ui.desc.textContent = "Canal de destino: " +
          (channels.get(job.channel_id)?.title || "Desconhecido") +
          ". Publicação: " + job.status + ". Prévia expira em 3 minutos.";
      } catch (error) { feedback("Prévia: " + error.message); }
    };
    box.append(title, info, btn); ui.items.append(box);
  }
}
el("login").onclick = async () => {
  try {
    const response = await fetch(url(ui.authUrl) + "/auth/v1/token?grant_type=password", {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: ui.publishable.value.trim() },
      body: JSON.stringify({ email: ui.email.value.trim(), password: ui.password.value })
    });
    const data = await response.json();
    if (!response.ok || !data.access_token) throw Error(data.msg || "Login não autorizado");
    session = data.access_token; ui.password.value = "";
    const orgs = await api("/v1/organizations");
    ui.org.replaceChildren();
    for (const org of orgs) {
      const option = document.createElement("option");
      option.value = org.id; option.textContent = org.name;
      ui.org.append(option);
    }
    feedback("Conta autenticada para revisão.");
    await refresh();
  } catch (error) { feedback("Login: " + error.message); }
};
el("refresh").onclick = async () => {
  try { await refresh(); feedback("Fila atualizada."); }
  catch (error) { feedback(error.message); }
};
ui.org.onchange = () => {
  active = null; ui.approve.disabled = true; ui.preview.removeAttribute("src");
  ui.preview.load(); refresh().catch(error => feedback(error.message));
};
ui.approve.onclick = async () => {
  try {
    if (!active || active.status !== "ready") throw Error("Selecione um corte pronto.");
    if (!ui.rights.checked) throw Error("Confirme os direitos e o destino privado.");
    await api("/v1/jobs/" + encodeURIComponent(active.id) + "/approve", {
      method: "POST", body: JSON.stringify({
        org_id: ui.org.value, rights_confirmed: true, visibility: "private"
      })
    });
    feedback("Publicação privada aprovada e enfileirada. A cobrança será confirmada após upload.");
    active = null; ui.approve.disabled = true;
    await refresh();
  } catch (error) { feedback(error.message); }
};
(async () => {
  try {
    const response = await fetch("./saas-config.json", { cache: "no-store" });
    if (!response.ok) return;
    const conf = await response.json();
    if (conf.apiUrl) ui.api.value = conf.apiUrl;
    if (conf.supabaseUrl) ui.authUrl.value = conf.supabaseUrl;
    if (conf.supabasePublishableKey) ui.publishable.value = conf.supabasePublishableKey;
  } catch {}
})();
