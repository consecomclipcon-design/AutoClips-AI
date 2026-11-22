/* Transcrição Whisper somente no Worker local do cliente.
 * Nenhum áudio/arquivo é enviado aos servidores do AutoClips.
 * O próprio navegador baixa e mantém em cache o modelo público da Hugging Face.
 */
import {env, pipeline} from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1";
env.allowLocalModels = false;
env.backends.onnx.wasm.numThreads = 1;
let recognizer = null;
let loadingPromise = null;

async function getRecognizer() {
  if (!loadingPromise) {
    loadingPromise = pipeline("automatic-speech-recognition", "Xenova/whisper-base", {
      revision: "64da57285918e20ea79ea5c88eed7197933abaa8",
      dtype: "q8",
      device: "wasm"
    }).then(pipe => {recognizer = pipe; return pipe;}).catch(error => {
      loadingPromise = null;
      throw error;
    });
  }
  return loadingPromise;
}
self.addEventListener("message", async ({data}) => {
  const {id, pcm} = data || {};
  if (!Number.isInteger(id) || !(pcm instanceof Float32Array) || pcm.length === 0) return;
  try {
    if (!recognizer) self.postMessage({id, loading: true});
    const pipe = await getRecognizer();
    const response = await pipe(pcm, {
      return_timestamps: true,
      language: "portuguese",
      task: "transcribe",
    });
    const chunks = Array.isArray(response.chunks) ? response.chunks :
      [{timestamp: [0, pcm.length / 16000], text: response.text || ""}];
    self.postMessage({id, chunks});
  } catch (error) {
    self.postMessage({id, error: "Whisper local falhou: " + (error?.message || String(error))});
  }
});
