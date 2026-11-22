/* AutoClips remote dashboard: metadata ONLY. No media URLs and no media preview. */
const e = id => document.getElementById(id);
const ui = {
  api: e("api"), authUrl: e("authUrl"), publishable: e("publishable"),
  email: e("email"), password: e("password"), org: e("org"),
  feedback: e("feedback"), credits: e("credits"), items: e("items")
};
let session = null;
function feedback(message) { ui.feedback.textContent = String(message); }
function validatedUrl(el) {
  const u = new URL(el.value.trim());
  const local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
  if (u.protocol !== "https:" && !(u.protocol === "http:" && local)) throw Error("Use HTTPS");
  return u.origin + u.pathname.replace(/\/$/, "");
}
async function api(path) {
  if (!session) throw Error("Autenticação necessária.");
  const response = await fetch(validatedUrl(ui.api) + path, {
    headers: { Authorization: "Bearer " + session }
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(json.detail || "HTTP " + response.status);
  return json;
}
async function refresh() {
  if (!ui.org.value) return;
  const id = encodeURIComponent(ui.org.value);
  const [wallet, linked, jobs] = await Promise.all([
    api("/v1/wallet?org_id=" + id),
    api("/v1/channels?org_id=" + id),
    api("/v1/jobs?org_id=" + id)
  ]);
  const names = new Map(linked.map(channel => [channel.id, channel.title]));
  ui.credits.textContent = wallet.available + " créditos disponíveis · " + wallet.reserved + " reservados";
  ui.items.replaceChildren();
  if (!jobs.length) ui.items.textContent = "Ainda não há publicações.";
  for (const job of jobs) {
    const row = document.createElement("div"); row.className = "item";
    const title = document.createElement("h3"); title.textContent = job.title;
    const info = document.createElement("small");
    info.textContent = (names.get(job.channel_id) || "Canal") + " · " + job.status +
      " · crédito: " + job.credit_state +
      (job.youtube_video_id ? " · ID YouTube: " + job.youtube_video_id : "");
    row.append(title, info);
    ui.items.append(row);
  }
}
e("login").onclick = async () => {
  try {
    const response = await fetch(validatedUrl(ui.authUrl) + "/auth/v1/token?grant_type=password", {
      method: "POST",
      headers: { "Content-Type": "application/json", apikey: ui.publishable.value.trim() },
      body: JSON.stringify({ email: ui.email.value.trim(), password: ui.password.value })
    });
    const body = await response.json();
    if (!response.ok || !body.access_token) throw Error(body.msg || "Credenciais inválidas");
    session = body.access_token; ui.password.value = "";
    const orgs = await api("/v1/organizations");
    ui.org.replaceChildren();
    for (const org of orgs) {
      const option = document.createElement("option"); option.value = org.id;
      option.textContent = org.name;
      ui.org.append(option);
    }
    await refresh();
    feedback("Autenticado. Este painel não armazena nem reproduz mídia.");
  } catch (error) { feedback(error.message); }
};
e("refresh").onclick = async () => {
  try { await refresh(); feedback("Metadados atualizados."); }
  catch (err) { feedback(err.message); }
};
ui.org.onchange = () => refresh().catch(err => feedback(err.message));
(async () => {
  try {
    const response = await fetch("./saas-config.json", { cache: "no-store" });
    if (!response.ok) return;
    const config = await response.json();
    if (config.apiUrl) ui.api.value = config.apiUrl;
    if (config.supabaseUrl) ui.authUrl.value = config.supabaseUrl;
    if (config.supabasePublishableKey) ui.publishable.value = config.supabasePublishableKey;
  } catch {}
})();
