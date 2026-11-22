/* AutoClips - prova local independente do dashboard existente.
   Nenhum upload, acesso de rede, cookies de terceiros ou credenciais Google. */
const el = (id) => document.getElementById(id);
const video = el("source"), canvas = el("composition"), ctx = canvas.getContext("2d", { alpha: false });
const worker = typeof Worker !== "undefined" ? new Worker("./render.worker.js") : null;
const state = {
  db: null, entries: [], files: new Map(), selected: null, objectUrl: null,
  workerReady: !!worker, frameBusy: false, frameSeq: 0,
  recording: null, audioContext: null, audioSource: null, output: null
};
const videoFile = (file) => file && (file.type.startsWith("video/") || /\.(mp4|mov|mkv|webm|m4v)$/i.test(file.name));
const fmt = (n) => Number(n).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
function status(message) { el("status").textContent = message; }
function idFor(file) { return [file.name, file.size, file.lastModified].join("|"); }
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("autoclips-web-local-v1", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("entries", { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
function store(entry) {
  if (!state.db) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const tx = state.db.transaction("entries", "readwrite");
    tx.objectStore("entries").put(entry);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
function listStored() {
  return new Promise((resolve, reject) => {
    const tx = state.db.transaction("entries", "readonly");
    const req = tx.objectStore("entries").getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
function updateFileList() {
  const target = el("files");
  target.replaceChildren();
  el("restore").hidden = !state.entries.some((entry) => !state.files.has(entry.id) && entry.handle);
  if (!state.entries.length) {
    const p = document.createElement("p");
    p.textContent = "Nenhum vídeo selecionado.";
    target.append(p);
    return;
  }
  for (const entry of state.entries) {
    const button = document.createElement("button");
    button.className = "file" + (state.selected?.id === entry.id ? " active" : "");
    button.type = "button";
    const left = document.createElement("span");
    left.textContent = entry.name;
    const smaller = document.createElement("small");
    smaller.textContent = fmt(entry.size / (1024 * 1024)) + " MB · " +
      (state.files.has(entry.id) ? entry.status || "pronto" : "aguardando arquivo ou permissão");
    left.append(smaller);
    const arrow = document.createElement("span"); arrow.textContent = "Abrir";
    button.append(left, arrow);
    button.onclick = () => selectEntry(entry);
    target.append(button);
  }
}
async function addFile(file, handle = null) {
  if (!videoFile(file)) return false;
  const id = idFor(file);
  state.files.set(id, file);
  const existing = state.entries.find((entry) => entry.id === id);
  if (!existing) {
    const entry = {
      id, name: file.name, size: file.size, lastModified: file.lastModified,
      handle, status: "pronto", start: 0, end: null
    };
    state.entries.push(entry);
    await store(entry);
  } else if (handle && !existing.handle) {
    existing.handle = handle; existing.status = "pronto"; await store(existing);
  }
  return true;
}
async function selectEntry(entry) {
  if (state.recording) { status("Finalize a exportação antes de trocar o original."); return; }
  let file = state.files.get(entry.id);
  if (!file && entry.handle) {
    try {
      const permission = await entry.handle.queryPermission({ mode: "read" });
      if (permission !== "granted") {
        const newPermission = await entry.handle.requestPermission({ mode: "read" });
        if (newPermission !== "granted") { status("Leitura não autorizada. Selecione o arquivo novamente."); return; }
      }
      file = await entry.handle.getFile();
      if (idFor(file) !== entry.id) { status("O arquivo mudou. Escolha-o novamente para evitar cortes incorretos."); return; }
      state.files.set(entry.id, file);
    } catch (error) { status("Não foi possível reabrir o arquivo: " + error.message); return; }
  }
  if (!file) { el("inputFiles").click(); status("Escolha novamente o arquivo deste trabalho."); return; }
  video.pause();
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.selected = entry;
  state.objectUrl = URL.createObjectURL(file);
  video.src = state.objectUrl;
  video.load();
  el("editing").disabled = false;
  el("start").value = String(entry.start ?? 0);
  el("end").value = String(entry.end ?? 30);
  el("progress").value = 0;
  el("output").replaceChildren(); state.output = null; el("save").disabled = true;
  el("rights").checked = false;
  worker?.postMessage({ type: "reset-photo" });
  updateFileList();
  status("Arquivo local selecionado; nenhum upload foi feito.");
}
function configureWorker() {
  worker?.postMessage({
    type: "configure", white: el("hookWhite").value, red: el("hookRed").value,
    subtitle: el("subtitle").value
  });
}
worker?.addEventListener("message", ({ data }) => {
  if (data.type === "composed") {
    if (data.bitmap) {
      try { ctx.drawImage(data.bitmap, 0, 0, canvas.width, canvas.height); }
      finally { data.bitmap.close(); }
    }
    state.frameBusy = false;
  } else if (data.type === "error") {
    state.frameBusy = false; status("Erro na composição: " + data.message);
  }
});
worker?.addEventListener("error", (error) => {
  state.workerReady = false; status("Worker indisponível: " + error.message);
});
async function renderFrame() {
  if (!worker || state.frameBusy || video.readyState < 2 || !video.videoWidth) return;
  state.frameBusy = true;
  try {
    const bitmap = await createImageBitmap(video);
    worker.postMessage({ type: "frame", seq: ++state.frameSeq, bitmap }, [bitmap]);
  } catch (error) {
    state.frameBusy = false;
    if (state.recording) status("Erro ao ler frame: " + error.message);
  }
}
let rafId = 0;
function animate() {
  cancelAnimationFrame(rafId);
  const tick = () => {
    if (!video.paused && video.readyState >= 2) renderFrame();
    const job = state.recording;
    if (job && !job.paused) {
      const elapsed = Math.max(0, Math.min(job.end - job.start, video.currentTime - job.start));
      el("progress").value = 100 * elapsed / (job.end - job.start);
      if (video.currentTime >= job.end - 0.035 || video.ended) {
        finishRecording(); return;
      }
    }
    if (!video.paused || (job && job.paused)) rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);
}
video.addEventListener("loadedmetadata", () => {
  if (!state.selected) return;
  const duration = video.duration;
  if (!Number.isFinite(duration) || duration <= 0) {
    status("Não foi possível determinar a duração. Tente um MP4 ou WebM compatível."); return;
  }
  const start = Math.max(0, Math.min(Number(el("start").value) || 0, duration - 0.1));
  const end = Math.max(start + 0.1, Math.min(Number(state.selected.end) || start + 30, duration));
  el("start").value = String(Number(start.toFixed(2)));
  el("end").value = String(Number(end.toFixed(2)));
  el("metadata").textContent = video.videoWidth + "×" + video.videoHeight + " · " +
    fmt(duration) + " s · " + state.selected.name;
  video.currentTime = start;
});
video.addEventListener("error", () => status("Formato não reproduzível neste navegador. Tente MP4 H.264/AAC ou WebM."));
video.addEventListener("seeked", renderFrame);
video.addEventListener("play", animate);
video.addEventListener("ended", () => { if (state.recording) finishRecording(); });
for (const input of ["hookWhite", "hookRed", "subtitle"]) {
  el(input).addEventListener("input", () => { configureWorker(); renderFrame(); });
}
for (const input of ["start", "end"]) {
  el(input).addEventListener("change", async () => {
    if (!state.selected || state.recording) return;
    state.selected[input] = Number(el(input).value);
    await store(state.selected);
    if (input === "start" && Number.isFinite(state.selected.start)) video.currentTime = state.selected.start;
  });
}
el("choose").onclick = () => el("inputFiles").click();
el("inputFiles").onchange = async () => {
  let count = 0;
  for (const file of el("inputFiles").files || []) if (await addFile(file)) count++;
  updateFileList();
  if (count) await selectEntry(state.entries.find((entry) => state.files.has(entry.id)));
  el("inputFiles").value = "";
  el("permissions").textContent = count + " arquivo(s) autorizado(s) na sessão. Sem upload.";
};
el("folder").onclick = async () => {
  if (typeof window.showDirectoryPicker !== "function") {
    el("inputFiles").click();
    el("permissions").textContent = "Seletor de pasta indisponível: use a seleção manual de vídeos.";
    return;
  }
  try {
    const directory = await window.showDirectoryPicker({ mode: "read", id: "autoclips-originais" });
    let count = 0;
    for await (const handle of directory.values()) {
      if (handle.kind !== "file" || count >= 300) continue;
      const file = await handle.getFile();
      if (await addFile(file, handle)) count++;
    }
    updateFileList();
    if (count && !state.selected) await selectEntry(state.entries.find((entry) => state.files.has(entry.id)));
    el("permissions").textContent = count + " vídeo(s) localizado(s). Sem leitura recursiva de subpastas.";
  } catch (error) {
    if (error.name !== "AbortError") status("Pasta não selecionada: " + error.message);
  }
};
el("restore").onclick = async () => {
  let restored = 0;
  for (const entry of state.entries.filter((item) => item.handle && !state.files.has(item.id))) {
    try {
      if (await entry.handle.queryPermission({ mode: "read" }) === "granted") {
        const file = await entry.handle.getFile();
        if (idFor(file) === entry.id) { state.files.set(entry.id, file); restored++; }
      }
    } catch {}
  }
  updateFileList();
  status(restored + " arquivo(s) restaurado(s). Os demais exigem nova autorização individual.");
};
function mimeForRecorder() {
  if (!window.MediaRecorder) return null;
  const candidates = [
    "video/mp4;codecs=avc1.42E01E,mp4a.40.2", "video/mp4",
    "video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"
  ];
  return candidates.find((mime) => MediaRecorder.isTypeSupported(mime)) || null;
}
function seekTo(seconds) {
  return new Promise((resolve, reject) => {
    if (Math.abs(video.currentTime - seconds) < 0.025 && video.readyState >= 2) { resolve(); return; }
    const onSeek = () => { cleanup(); resolve(); };
    const onError = () => { cleanup(); reject(new Error("Falha ao posicionar o vídeo.")); };
    const cleanup = () => { video.removeEventListener("seeked", onSeek); video.removeEventListener("error", onError); };
    video.addEventListener("seeked", onSeek, { once: true });
    video.addEventListener("error", onError, { once: true });
    video.currentTime = seconds;
  });
}
function safeFilename(name) {
  return name.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]+/g, "-").slice(0, 64) || "clip";
}
async function startExport() {
  if (state.recording || !state.selected) return;
  if (!el("rights").checked) { status("Confirme os direitos do vídeo e da foto antes de exportar."); return; }
  if (!state.workerReady || !window.OffscreenCanvas || !HTMLCanvasElement.prototype.captureStream) {
    status("Seu navegador não suporta esta composição local. Experimente Chrome ou Edge atualizado."); return;
  }
  const mime = mimeForRecorder();
  if (!mime) { status("MediaRecorder não suporta os formatos de saída deste navegador."); return; }
  const start = Number(el("start").value), end = Number(el("end").value);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start ||
      end - start > 180 || end > video.duration + 0.01) {
    status("Intervalo inválido. Use início < fim, dentro do original e com duração máxima de 180 segundos."); return;
  }
  const file = state.files.get(state.selected.id);
  if (!file) { status("Original não disponível. Reautorize o arquivo."); return; }
  el("export").disabled = true; el("progress").value = 0; el("save").disabled = true;
  el("output").replaceChildren(); state.output = null;
  try {
    const audioContext = state.audioContext || new AudioContext();
    state.audioContext = audioContext;
    await audioContext.resume();
    configureWorker();
    const photo = el("photo").files?.[0];
    if (photo) {
      if (!photo.type.startsWith("image/") || photo.size > 30 * 1024 * 1024) {
        throw new Error("A foto deve ser uma imagem de até 30 MB.");
      }
      const bitmap = await createImageBitmap(photo);
      worker.postMessage({ type: "photo", bitmap }, [bitmap]);
    } else worker.postMessage({ type: "reset-photo" });
    video.pause();
    await seekTo(start);
    await renderFrame();
    if (!state.audioSource) {
      state.audioSource = audioContext.createMediaElementSource(video);
      state.audioSource.connect(audioContext.destination);
    }
    const destination = audioContext.createMediaStreamDestination();
    state.audioSource.connect(destination);
    await audioContext.resume();
    const canvasStream = canvas.captureStream(30);
    const combined = new MediaStream([
      ...canvasStream.getVideoTracks(), ...destination.stream.getAudioTracks()
    ]);
    const recorder = new MediaRecorder(combined, { mimeType: mime, videoBitsPerSecond: 2_500_000 });
    const chunks = [];
    const job = { start, end, recorder, combined, destination, chunks, mime, paused: false, finished: false };
    state.recording = job;
    state.selected.status = "processando localmente"; await store(state.selected); updateFileList();
    el("pause").disabled = false; el("pause").textContent = "Pausar";
    recorder.ondataavailable = ({ data }) => { if (data.size) chunks.push(data); };
    recorder.onerror = (event) => { status("Erro na gravação: " + (event.error?.message || "desconhecido")); finishRecording(); };
    recorder.onstop = async () => {
      combined.getTracks().forEach((track) => track.stop());
      state.audioSource?.disconnect(destination);
      const blob = new Blob(chunks, { type: mime.split(";")[0] });
      if (blob.size) {
        const extension = mime.startsWith("video/mp4") ? "mp4" : "webm";
        state.output = { blob, name: safeFilename(file.name) + "-" + Math.round(start) + "-" + Math.round(end) + "." + extension };
        const a = document.createElement("a");
        const url = URL.createObjectURL(blob);
        a.href = url; a.download = state.output.name;
        a.textContent = "Pré-visualizar / baixar " + state.output.name + " (" + fmt(blob.size / 1024 / 1024) + " MB)";
        a.target = "_blank";
        el("output").replaceChildren(a);
        el("save").disabled = false;
        status("Corte exportado localmente. Confira áudio, imagem e sincronização antes de publicar.");
        state.selected.status = "exportado localmente";
      } else {
        status("O navegador não gerou um arquivo válido. Tente outro formato de origem ou navegador.");
        state.selected.status = "falhou";
      }
      await store(state.selected); updateFileList();
      state.recording = null;
      el("export").disabled = false; el("pause").disabled = true;
    };
    recorder.start(1000);
    status("Exportando no próprio navegador; mantenha esta aba aberta.");
    await video.play();
    animate();
  } catch (error) {
    status("Falha ao exportar: " + error.message);
    if (state.recording) finishRecording();
    else { el("export").disabled = false; el("pause").disabled = true; }
  }
}
function finishRecording() {
  const job = state.recording;
  if (!job || job.finished) return;
  job.finished = true;
  video.pause();
  if (job.recorder.state !== "inactive") job.recorder.stop();
  el("pause").disabled = true;
  el("progress").value = 100;
}
el("export").onclick = startExport;
el("pause").onclick = async () => {
  const job = state.recording;
  if (!job || job.finished) return;
  if (!job.paused) {
    job.paused = true; video.pause(); job.recorder.pause();
    el("pause").textContent = "Continuar"; status("Exportação pausada nesta aba.");
  } else {
    job.paused = false; job.recorder.resume();
    el("pause").textContent = "Pausar"; status("Exportação retomada.");
    await video.play(); animate();
  }
};
el("save").onclick = async () => {
  const output = state.output;
  if (!output) return;
  if (typeof window.showDirectoryPicker === "function") {
    try {
      const directory = await window.showDirectoryPicker({ mode: "readwrite", id: "autoclips-destino" });
      if (await directory.queryPermission({ mode: "readwrite" }) !== "granted") {
        if (await directory.requestPermission({ mode: "readwrite" }) !== "granted") {
          status("Escrita não autorizada. Use o link de download."); return;
        }
      }
      const handle = await directory.getFileHandle(output.name, { create: true });
      const writable = await handle.createWritable();
      await writable.write(output.blob); await writable.close();
      status("Arquivo salvo na pasta selecionada: " + output.name);
      return;
    } catch (error) {
      if (error.name !== "AbortError") status("Pasta indisponível: " + error.message + ". Use o link de download.");
      return;
    }
  }
  const a = el("output").querySelector("a");
  a?.click();
};
window.addEventListener("beforeunload", () => {
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.output = null;
});
async function initialize() {
  configureWorker();
  try {
    state.db = await openDB();
    state.entries = await listStored();
    for (const entry of state.entries) {
      if (entry.status === "processando localmente") {
        entry.status = "interrompido: reabra o original e exporte novamente";
        await store(entry);
      }
    }
    updateFileList();
  } catch (error) {
    status("IndexedDB indisponível; a fila não persistirá entre sessões: " + error.message);
  }
  if (!worker) status("Web Worker indisponível neste navegador.");
  ctx.fillStyle = "#080a0e"; ctx.fillRect(0, 0, canvas.width, canvas.height);
}
initialize();