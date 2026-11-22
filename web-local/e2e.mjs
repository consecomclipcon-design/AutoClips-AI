// Executado por CI em Chromium com uma amostra audiovisual gerada somente para teste.
import { chromium } from "playwright";
import { strict as assert } from "node:assert";
import path from "node:path";
const sample = process.env.TEST_VIDEO || "/tmp/autoclips-fixture.mp4";
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--autoplay-policy=no-user-gesture-required"]
});
try {
  const page = await browser.newPage({ acceptDownloads: true });
  const unexpectedPosts = [];
  const errors = [];
  page.on("request", (req) => { if (req.method() !== "GET") unexpectedPosts.push(req.url()); });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("http://127.0.0.1:8080/", { waitUntil: "domcontentloaded" });
  // Every screen from the desktop reference must be visible and navigable.
  assert.equal(await page.locator("#studioWrap").isVisible(), false);
  for (const [screen, heading] of [
    ["overview", "Visão geral"], ["create", "Crie cortes"],
    ["approvals", "Aprovações"], ["production", "Fila de"],
    ["posting", "O que vai"], ["storage", "Pasta atual"],
    ["settings", "Canais e fontes"], ["billing", "Planos e"]
  ]) {
    await page.locator('[data-desktop-page="' + screen + '"]').first().click();
    const content = await page.locator("#ad-" + screen).innerText();
    assert.ok(content.toLowerCase().includes(heading.toLowerCase()), "Tela ausente: " + screen);
    assert.equal(await page.locator("#ad-" + screen).isVisible(), true);
  }
  await page.locator('[data-desktop-page="create"]').first().click();
  await page.locator("#inputFiles").setInputFiles(sample);
  await page.waitForFunction(() => {
    const v = document.getElementById("source");
    return Number.isFinite(v.duration) && v.duration > 2;
  }, null, { timeout: 15000 });
  await page.locator("#adCutStart").fill("0.2");
  await page.locator("#adCutEnd").fill("2.2");
  await page.locator("#adEditRights").check();
  await page.locator("#adExport").click();
  await page.waitForFunction(() => {
    const text = document.getElementById("status")?.textContent || "";
    return text.includes("Corte exportado localmente") ||
      text.includes("Falha ao exportar") ||
      text.includes("não gerou um arquivo válido") ||
      text.includes("Worker indisponível");
  }, null, { timeout: 30000 });
  const status = await page.locator("#status").innerText();
  assert.match(status, /Corte exportado localmente/, status);
  assert.equal(await page.locator("#files button.file").count(), 1);
  assert.equal(unexpectedPosts.length, 0, "Nenhum upload ou POST deve acontecer");
  assert.deepEqual(errors, [], "Não devem ocorrer erros JS de página");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#output a").click();
  const download = await downloadPromise;
  const output = path.join("/tmp", download.suggestedFilename());
  await download.saveAs(output);
  console.log("exported:", output);
} finally {
  await browser.close();
}