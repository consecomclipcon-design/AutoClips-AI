/* Whisper ASR exclusivamente no dispositivo do usuário.
 * Original e PCM não saem do navegador AutoClips; os pesos do modelo são baixados
 * diretamente pelo cliente do Hugging Face/CDN na primeira utilização.
 * Mediabunny decodifica blocos de áudio sem ler o original inteiro em RAM.
 */
const SAMPLE_RATE = 16000;
const BLOCK_SECONDS = 28;
const BLOCK_SAMPLES = SAMPLE_RATE * BLOCK_SECONDS;

export async function transcribeVideo(file, duration, {signal, onProgress = () => {}} = {}) {
  if (!(file instanceof Blob)) throw Error("Escolha um arquivo de vídeo autorizado.");
  if (!Number.isFinite(duration) || duration <= 0) throw Error("Duração do vídeo inválida.");
  if (!Number.isFinite(file.size) || file.size <= 0) throw Error("O vídeo está vazio.");
  signal?.throwIfAborted();
  onProgress("Abrindo áudio no próprio navegador…");
  const { Input, BlobSource, ALL_FORMATS, AudioBufferSink } =
    await import("https://cdn.jsdelivr.net/npm/mediabunny@1.66.2/+esm");
  signal?.throwIfAborted();

  const media = new Input({source: new BlobSource(file), formats: ALL_FORMATS});
  const worker = new Worker("./transcribe.worker.js", {type: "module"});
  const cues = [];
  let cursor = 0;
  let blockStart = 0;
  let used = 0;
  let pcm = new Float32Array(BLOCK_SAMPLES);
  let taskId = 0;
  try {
    const track = await media.getPrimaryAudioTrack();
    if (!track) throw Error("Não há áudio no vídeo selecionado.");
    if (!(await track.canDecode())) throw Error("Áudio incompatível com este navegador. Importe SRT/VTT ou use MP4 com AAC.");

    const inferBlock = async () => {
      signal?.throwIfAborted();
      const segmentDuration = used / SAMPLE_RATE;
      if (used < SAMPLE_RATE / 2) { used = 0; return; }
      const input = pcm.slice(0, used);
      // Evita transcrever ruído quase silencioso.
      let energy = 0;
      for (let i = 0; i < used; i += 160) energy += Math.abs(input[i]);
      if (energy / Math.ceil(used / 160) < 0.0018) { used = 0; return; }
      const id = ++taskId;
      const chunks = await new Promise((resolve, reject) => {
        const abort = () => {cleanup(); reject(signal?.reason || new DOMException("Cancelado", "AbortError"));};
        const cleanup = () => {
          worker.removeEventListener("message", message);
          worker.removeEventListener("error", error);
          signal?.removeEventListener("abort", abort);
        };
        const message = event => {
          const data = event.data || {};
          if (data.id !== id) return;
          if (data.loading) { onProgress("Carregando Whisper localmente (primeira execução pode baixar o modelo)…"); return; }
          cleanup();
          if (data.error) reject(Error(String(data.error)));
          else resolve(Array.isArray(data.chunks) ? data.chunks : []);
        };
        const error = () => { cleanup(); reject(Error("O Worker de transcrição não pôde iniciar.")); };
        if (signal?.aborted) return abort();
        worker.addEventListener("message", message);
        worker.addEventListener("error", error);
        signal?.addEventListener("abort", abort, {once:true});
        worker.postMessage({id, pcm: input}, [input.buffer]);
      });
      for (const row of chunks) {
        const [from, to] = Array.isArray(row.timestamp) ? row.timestamp : [null, null];
        if (!Number.isFinite(from)) continue;
        const start = Math.max(0, blockStart / SAMPLE_RATE + from);
        const end = Math.min(duration, blockStart / SAMPLE_RATE +
          (Number.isFinite(to) ? Math.min(to, segmentDuration) : segmentDuration));
        const text = String(row.text || "").trim();
        if (end > start && text) cues.push({start, end, text});
      }
      onProgress("Transcrevendo no seu computador… " +
        Math.min(100, Math.round((blockStart + used) / (duration * SAMPLE_RATE) * 100)) + "%");
      used = 0;
    };

    // AudioBufferSink fornece os buffers por ordem de apresentação e descarta
    // os buffers anteriores. Nenhum original ou PCM é enviado à API AutoClips.
    for await (const {buffer, timestamp} of new AudioBufferSink(track).buffers(0, duration)) {
      signal?.throwIfAborted();
      if (!Number.isFinite(timestamp) || buffer.length === 0) continue;
      const channels = Array.from({length: buffer.numberOfChannels}, (_, i) => buffer.getChannelData(i));
      if (!channels.length) continue;
      const ratio = buffer.sampleRate / SAMPLE_RATE;
      const first = Math.max(0, Math.round(timestamp * SAMPLE_RATE));
      const last = Math.min(Math.round(duration * SAMPLE_RATE),
        first + Math.round(buffer.length / ratio));
      for (let absolute = Math.max(first, cursor); absolute < last; absolute++) {
        if (absolute >= blockStart + BLOCK_SAMPLES) {
          await inferBlock();
          blockStart = Math.floor(absolute / BLOCK_SAMPLES) * BLOCK_SAMPLES;
          pcm = new Float32Array(BLOCK_SAMPLES);
        }
        const position = (absolute - first) * ratio;
        const lo = Math.min(Math.max(0, Math.floor(position)), buffer.length - 1);
        const hi = Math.min(lo + 1, buffer.length - 1);
        const fraction = Math.max(0, Math.min(1, position - lo));
        let value = 0;
        for (const channel of channels) value += channel[lo] + (channel[hi] - channel[lo]) * fraction;
        pcm[absolute - blockStart] = value / channels.length;
        used = Math.max(used, absolute - blockStart + 1);
      }
      cursor = Math.max(cursor, last);
    }
    if (used) await inferBlock();
    if (!cues.length) throw Error("Nenhuma fala reconhecida. Verifique se há voz em português ou importe uma legenda SRT/VTT.");
    return cues.sort((a, b) => a.start - b.start);
  } finally {
    worker.terminate();
    media.dispose();
  }
}
