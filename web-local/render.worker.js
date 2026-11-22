/* Worker isolado: recebe somente ImageBitmap de arquivos autorizados.
   Composição em OffscreenCanvas. A captura acontece no navegador principal. */
const WIDTH = 540, HEIGHT = 960, SPLIT = Math.round(HEIGHT * 0.57);
const canvas = new OffscreenCanvas(WIDTH, HEIGHT);
const ctx = canvas.getContext("2d", { alpha: false, desynchronized: true });
let lowerImage = null;
let config = { white: "UM MOMENTO", red: "INCRÍVEL", subtitle: "" };

function cover(bitmap, x, y, w, h, focusX = 0.5, focusY = 0.5) {
  const scale = Math.max(w / bitmap.width, h / bitmap.height);
  const cropW = w / scale, cropH = h / scale;
  const left = Math.max(0, Math.min(bitmap.width - cropW, (bitmap.width - cropW) * focusX));
  const top = Math.max(0, Math.min(bitmap.height - cropH, (bitmap.height - cropH) * focusY));
  ctx.drawImage(bitmap, left, top, cropW, cropH, x, y, w, h);
}
function title(text, y, color, size = 63) {
  if (!text) return;
  ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.lineJoin = "round";
  ctx.shadowColor = "#000c"; ctx.shadowBlur = 9; ctx.shadowOffsetY = 4;
  for (let fontSize = size; fontSize >= 23; fontSize -= 2) {
    ctx.font = "900 italic " + fontSize + "px Arial, sans-serif";
    if (ctx.measureText(text).width <= WIDTH - 28 || fontSize <= 23) break;
  }
  ctx.strokeStyle = "#080808"; ctx.lineWidth = 10;
  ctx.strokeText(text, WIDTH / 2, y);
  ctx.fillStyle = color; ctx.fillText(text, WIDTH / 2, y);
  ctx.shadowBlur = 0; ctx.shadowOffsetY = 0;
}
function compose(frame) {
  ctx.fillStyle = "#080a0e"; ctx.fillRect(0, 0, WIDTH, HEIGHT);
  cover(frame, 0, 0, WIDTH, SPLIT);
  cover(lowerImage || frame, 0, SPLIT, WIDTH, HEIGHT - SPLIT);
  const gradient = ctx.createLinearGradient(0, SPLIT - 95, 0, SPLIT + 95);
  gradient.addColorStop(0, "#0000"); gradient.addColorStop(0.5, "#0008");
  gradient.addColorStop(1, "#0000");
  ctx.fillStyle = gradient; ctx.fillRect(0, SPLIT - 95, WIDTH, 190);
  if (config.subtitle) title(config.subtitle.slice(0, 65), SPLIT - 136, "#fff", 28);
  title(config.white.slice(0, 65).toUpperCase(), SPLIT - 23, "#fff");
  title(config.red.slice(0, 65).toUpperCase(), SPLIT + 46, "#ef233c");
}
self.onmessage = (event) => {
  const data = event.data;
  if (data.type === "configure") {
    config = { white: String(data.white || "").trim(), red: String(data.red || "").trim(),
      subtitle: String(data.subtitle || "").trim() };
  } else if (data.type === "photo") {
    lowerImage?.close(); lowerImage = data.bitmap || null;
  } else if (data.type === "reset-photo") {
    lowerImage?.close(); lowerImage = null;
  } else if (data.type === "frame") {
    try {
      compose(data.bitmap);
      const output = canvas.transferToImageBitmap();
      self.postMessage({ type: "composed", seq: data.seq, bitmap: output }, [output]);
    } catch (err) {
      self.postMessage({ type: "error", message: String(err?.message || err) });
    } finally { data.bitmap.close(); }
  }
};