/* The mock models do not contact Hugging Face. This proves UI→decoder→Worker→cues
 * with all audio resident in the browser. A genuine Portuguese Whisper test is
 * still required before enabling ASR for paying customers.
 */
import {chromium} from "playwright";
import assert from "node:assert/strict";
const browser = await chromium.launch({headless:true,args:["--no-sandbox","--disable-dev-shm-usage"]});
try {
  const page = await browser.newPage();
  const posts = [], errors = [];
  page.on("request", req => {if (!["GET","HEAD"].includes(req.method())) posts.push(req.url());});
  page.on("pageerror", err=> errors.push(err.message));
  const responseHeaders = {"Access-Control-Allow-Origin":"*","Cache-Control":"no-cache"};
  await page.route("https://cdn.jsdelivr.net/npm/mediabunny@1.66.2/+esm", route => route.fulfill({
    status:200,contentType:"text/javascript",headers:responseHeaders,
    body: `export class BlobSource {constructor(file){this.file=file;}}
export const ALL_FORMATS=[];
export class Input {
  async getPrimaryAudioTrack() {return {canDecode:async()=>true};}
  dispose(){}
}
export class AudioBufferSink {
  async *buffers() {
    const data=new Float32Array(48000);
    for(let i=0;i<data.length;i++)data[i]=i%200<100?0.3:-0.3;
    yield {timestamp:0,buffer:{numberOfChannels:1,sampleRate:16000,length:data.length,getChannelData:()=>data}};
  }
}`
  }));
  await page.route("https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1", route=>route.fulfill({
    status:200,contentType:"text/javascript",headers:responseHeaders,
    body: `export const env={allowLocalModels:false,backends:{onnx:{wasm:{numThreads:1}}}};
export async function pipeline() {
  return async () => ({text:"Olá, este é um teste.",chunks:[{timestamp:[0,2],text:"Olá, este é um teste."}]});
}`
  }));
  await page.goto("http://127.0.0.1:8080/",{waitUntil:"domcontentloaded"});
  await page.locator("#inputFiles").setInputFiles("/tmp/autoclips-fixture.mp4");
  await page.waitForFunction(()=>Number.isFinite(document.querySelector("#source").duration));
  await page.locator("#adTranscribe").click();
  await page.waitForFunction(()=>/falas transcritas|Whisper local falhou|modelo Whisper/i.test(document.querySelector("#adCaptionStatus")?.textContent||""),
    null,{timeout:30000});
  const message=await page.locator("#adCaptionStatus").innerText();
  assert.match(message,/falas transcritas/,message);
  assert.equal(await page.locator("#adSuggestClips").isDisabled(),false);
  assert.deepEqual(posts,[],"Transcription should never POST media");
  assert.deepEqual(errors,[],"No page JS errors");
  console.log("Local transcription with MOCK model: "+message+"; 0 POST requests");
} finally {await browser.close();}
