/* Browser integration test with MOCK Google and AutoClips endpoints.
   Proves media travels to YouTube endpoint only, not SaaS API.
   This is NOT a real OAuth or YouTube upload test.
*/
import { chromium } from "playwright";
import assert from "node:assert/strict";

const orgId = "11111111-1111-4111-8111-111111111111";
const channelId = "22222222-2222-4222-8222-222222222222";
const jobId = "33333333-3333-4333-8333-333333333333";
const googleChannel = "UC1234567890123456789012";
const youtubeId = "abcDEF123_-";
const browser = await chromium.launch({
  headless: true, args: ["--no-sandbox", "--disable-dev-shm-usage", "--autoplay-policy=no-user-gesture-required"]
});
const calls = { youtubeBinaryBytes: 0, saasBinaryBytes: 0, approved: 0, captured: 0 };
const record = { wallet: { available: 100, reserved: 0, total_purchased: 100 }, jobs: [] };
const page = await browser.newPage({ acceptDownloads: true });
const json = (route, body, status = 200, extraHeaders = {}) => route.fulfill({
  status, contentType: "application/json",
  headers: { "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-YouTube-Access-Token, X-Upload-Content-Type, X-Upload-Content-Length, Content-Range",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Expose-Headers": "Location, Range", ...extraHeaders },
  body: JSON.stringify(body)
});
try {
  await page.addInitScript(() => {
    window.google = {
      accounts: { oauth2: {
        initTokenClient({ callback }) {
          return {
            requestAccessToken() {
              callback({
                access_token: "google-test-token",
                scope: "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload",
                expires_in: 3600
              });
            }
          };
        },
        hasGrantedAllScopes() { return true; }
      } }
    };
  });
  await page.route("https://accounts.google.com/gsi/client", route =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: "" }));
  await page.route("https://sample.supabase.co/**", route =>
    route.request().method() === "OPTIONS" ? json(route, {}, 204) :
    json(route, { access_token: "test-supabase-session", user: { id: orgId } }));

  await page.route(/https:\/\/api\.example\.com\/v1\//, async route => {
    const req = route.request();
    if (req.method() === "OPTIONS") return json(route, {}, 204);
    const url = new URL(req.url()), path = url.pathname;
    const body = req.postData() || "";
    if (body.length > 32768 || /video\//.test(req.headers()["content-type"] || "")) {
      calls.saasBinaryBytes += body.length;
      throw Error("Video media was sent to the AutoClips backend");
    }
    if (path === "/v1/organizations" && req.method() === "GET") {
      return json(route, [{ id: orgId, name: "Test studio", role: "owner" }]);
    }
    if (path === "/v1/wallet") return json(route, { ...record.wallet });
    if (path === "/v1/channels") {
      return json(route, [{ id: channelId, youtube_channel_id: googleChannel,
        title: "Own channel", active: true }]);
    }
    if (path === "/v1/sources") return json(route, []);
    if (path === "/v1/jobs" && req.method() === "GET") return json(route, record.jobs);
    if (path === "/v1/jobs" && req.method() === "POST") {
      const requestData = JSON.parse(body);
      assert.equal(requestData.channel_id, channelId);
      assert.equal(requestData.sha256.length, 64);
      assert.ok(requestData.size_bytes > 1024);
      record.jobs = [{ id: jobId, org_id: orgId, channel_id: channelId,
        title: requestData.title, status: "ready", credit_state: "none",
        youtube_video_id: null }];
      return json(route, record.jobs[0], 201);
    }
    if (path.endsWith("/approve")) {
      calls.approved += 1;
      record.wallet.available -= 1; record.wallet.reserved += 1;
      record.jobs[0].status = "queued"; record.jobs[0].credit_state = "reserved";
      return json(route, record.jobs[0]);
    }
    if (path.endsWith("/begin")) {
      assert.equal(record.jobs[0].status, "queued");
      record.jobs[0].status = "uploading";
      return json(route, record.jobs[0]);
    }
    if (path.endsWith("/complete")) {
      assert.equal(req.headers()["x-youtube-access-token"], "google-test-token");
      assert.equal(JSON.parse(body).youtube_video_id, youtubeId);
      record.wallet.reserved -= 1;
      record.jobs[0].status = "published";
      record.jobs[0].credit_state = "captured";
      record.jobs[0].youtube_video_id = youtubeId;
      calls.captured += 1;
      return json(route, record.jobs[0]);
    }
    if (path.endsWith("/uncertain")) throw Error("No ambiguous upload expected");
    throw Error("Unexpected SaaS endpoint: " + req.method() + " " + path);
  });
  await page.route("https://www.googleapis.com/**", async route => {
    const req = route.request(), url = new URL(req.url());
    if (req.method() === "OPTIONS") return json(route, {}, 204);
    if (url.pathname === "/youtube/v3/channels") {
      return json(route, { items: [{ id: googleChannel, snippet: { title: "Own channel" } }] });
    }
    if (url.pathname === "/upload/youtube/v3/videos" && req.method() === "POST") {
      const data = JSON.parse(req.postData() || "{}");
      assert.equal(data.status.privacyStatus, "private");
      assert.ok(data.snippet.title);
      return json(route, {}, 200, {
        "Location": "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=mocked"
      });
    }
    if (url.pathname === "/upload/youtube/v3/videos" && req.method() === "PUT") {
      const payload = req.postDataBuffer();
      calls.youtubeBinaryBytes += payload.length;
      assert.ok(payload.length > 1024);
      return json(route, { id: youtubeId }, 201);
    }
    throw Error("Unexpected Google request: " + req.method() + " " + url.pathname);
  });

  const errors = [];
  page.on("pageerror", err => errors.push(err.message));
  await page.goto("http://127.0.0.1:8080/", { waitUntil: "domcontentloaded" });
  await page.locator('[data-view="channels"]').first().click();
  await page.locator("#saasApi").fill("https://api.example.com");
  await page.locator("#saasSupabase").fill("https://sample.supabase.co");
  await page.locator("#saasPublishable").fill("sb_publishable_test");
  await page.locator("#saasGoogleClientId").fill("123456789-test.apps.googleusercontent.com");
  await page.locator("#saasEmail").fill("owner@example.com");
  await page.locator("#saasPassword").fill("test-password");
  await page.locator("#saasLogin").click();
  await page.waitForFunction(() => !!document.querySelector("#saasChannel option"));
  await page.locator('[data-view="studio"]').first().click();

  await page.locator("#inputFiles").setInputFiles("/tmp/autoclips-fixture.mp4");
  await page.waitForFunction(() => {
    const v = document.getElementById("source");
    return Number.isFinite(v.duration) && v.duration >= 3;
  });
  await page.locator("#start").fill("0.2");
  await page.locator("#end").fill("2.2");
  await page.locator("#rights").check();
  await page.locator("#export").click();
  await page.waitForFunction(() =>
    document.getElementById("status")?.textContent.includes("Corte exportado localmente"), null, { timeout: 30000 });

  await page.locator("#saasApprovalCheck").check();
  await page.locator("#saasTitle").fill("Corte de teste autorizado");
  await page.locator("#saasPrepare").click();
  await page.waitForFunction(() => !document.querySelector("#saasPublish").disabled);
  await page.locator("#saasPublish").click();
  await page.waitForFunction(() =>
    document.getElementById("saasFeedback")?.textContent.includes("Publicado em modo privado"), null,
    { timeout: 20000 });

  assert.equal(calls.approved, 1);
  assert.equal(calls.captured, 1);
  assert.ok(calls.youtubeBinaryBytes > 1024);
  assert.equal(calls.saasBinaryBytes, 0);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("autoclips:wallet", {
    detail: { wallet: { available: 0, reserved: 0, total_purchased: 100 }, jobs: [] }
  })));
  await page.locator("#creditModal").waitFor({ state: "visible" });
  assert.match(await page.locator("#creditModalTitle").innerText(), /créditos acabaram/i);
  await page.locator("#creditModalBuy").click();
  assert.equal(await page.locator("#view-payments").isVisible(), true);
  assert.equal(await page.locator(".plan-card").count(), 4);
  assert.equal(await page.locator("#paymentsCredits").innerText(), "0");
  assert.deepEqual(errors, []);
  console.log("ZERO MEDIA PROVED (MOCK): bytes to Google:", calls.youtubeBinaryBytes,
    "bytes to AutoClips API:", calls.saasBinaryBytes);
} finally {
  await browser.close();
}
