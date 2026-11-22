/* Legendas locais: dados de vídeo/transcrição nunca são transmitidos à API SaaS. */
export function parseTimestamp(value) {
  const v = String(value || "").trim().replace(",", ".");
  const p = v.split(":");
  if (p.length < 2 || p.length > 3 || !p.every(x => /^\d+(?:\.\d+)?$/.test(x))) return NaN;
  const numbers = p.map(Number);
  const seconds = p.length === 3 ?
    numbers[0] * 3600 + numbers[1] * 60 + numbers[2] :
    numbers[0] * 60 + numbers[1];
  return Number.isFinite(seconds) ? seconds : NaN;
}
export function parseSubtitles(raw, duration = Infinity) {
  if (typeof raw !== "string" || raw.length > 2_000_000) throw Error("Arquivo de legenda vazio ou acima de 2 MB.");
  const content = raw.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  const blocks = content.split(/\n\s*\n/);
  const cues = [];
  for (const block of blocks) {
    const lines = block.trim().split("\n");
    const idx = lines.findIndex(x => x.includes("-->"));
    if (idx < 0) continue;
    const [a, b] = lines[idx].split(/\s+-->\s+/);
    if (!b) continue;
    const start = parseTimestamp(a);
    const end = parseTimestamp(b.split(/\s+/)[0]);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || start < 0 || start >= duration) continue;
    const text = lines.slice(idx + 1)
      .filter(line => !/^(NOTE|STYLE|REGION)(\s|$)/.test(line))
      .join(" ")
      .replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
    if (text) cues.push({start, end: Math.min(end, duration), text: text.slice(0, 400)});
  }
  if (!cues.length) throw Error("Não há legendas SRT/VTT com tempo válido neste arquivo.");
  return cues.sort((a, b) => a.start - b.start);
}
export function captionAt(cues, time) {
  if (!Number.isFinite(time)) return "";
  // A sequência é cronológica, mas trechos sobrepostos também são aceitos.
  for (let i = cues.length - 1; i >= 0; --i) {
    const cue = cues[i];
    if (cue.start <= time) return time < cue.end ? cue.text : "";
  }
  return "";
}
export function suggestClips(cues, duration, count = 3) {
  if (!Array.isArray(cues) || !cues.length || !(duration > 0)) return [];
  const candidates = [];
  const hookWords = /(?:mas|porém|porque|como|quando|então|nunca|sempre|incrível|maior|melhor|importante|descobri|sabia|segredo|resultado|surpresa|verdade|problema)/i;
  for (let i = 0; i < cues.length; i++) {
    const start = Math.max(0, cues[i].start - 1);
    const bestLimit = Math.min(duration, start + 55);
    let end = cues[i].end, words = 0, text = "", speechEnd = end;
    for (let j = i; j < cues.length && cues[j].start < bestLimit; j++) {
      end = Math.min(bestLimit, cues[j].end);
      words += cues[j].text.split(/\s+/).length;
      text += " " + cues[j].text;
      speechEnd = end;
      const len = end - start;
      if (len >= 13 && len <= 45) {
        const score = (hookWords.test(text) ? 7 : 0) +
          (/[?!]/.test(text) ? 4 : 0) + Math.min(10, words / 10) -
          Math.abs(len - 28) * 0.1;
        candidates.push({start, end: speechEnd, score,
          hook: cues[i].text.replace(/\s+/g, " ").slice(0, 62)});
      }
    }
  }
  candidates.sort((a, b) => b.score - a.score);
  const chosen = [];
  for (const clip of candidates) {
    if (chosen.every(prev => clip.end <= prev.start || clip.start >= prev.end)) {
      chosen.push({start: Math.round(clip.start * 10) / 10,
        end: Math.round(clip.end * 10) / 10, hook: clip.hook});
      if (chosen.length >= Math.min(3, Math.max(1, count))) break;
    }
  }
  return chosen.sort((a, b) => a.start - b.start);
}
