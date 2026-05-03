const path = require("node:path");
const { expect, test } = require("@playwright/test");

const demoUrl = `file://${path.resolve(__dirname, "../../web/index.html")}`;

async function canvasHash(page, selector) {
  return page.locator(selector).evaluate((canvas) => {
    const ctx = canvas.getContext("2d");
    const { width, height } = canvas;
    const sample = ctx.getImageData(0, 0, width, height).data;
    let hash = 2166136261;
    let litPixels = 0;
    let variedPixels = 0;

    for (let index = 0; index < sample.length; index += 64) {
      const red = sample[index];
      const green = sample[index + 1];
      const blue = sample[index + 2];
      const alpha = sample[index + 3];
      if (alpha > 0 && red + green + blue > 30) litPixels += 1;
      if (Math.max(red, green, blue) - Math.min(red, green, blue) > 8) variedPixels += 1;
      hash ^= red + green * 3 + blue * 7 + alpha * 11 + index;
      hash = Math.imul(hash, 16777619);
    }

    return { hash: hash >>> 0, litPixels, variedPixels, width, height };
  });
}

test("offline swarm control: commands queue, sync gate holds, degraded works", async ({ page }) => {
  await page.goto(demoUrl);
  await page.waitForTimeout(900);

  // Verify initial offline mode — sync gate is "Closed Local"
  await expect(page.locator("#mode-status")).toContainText("Fusion Node Authority");
  await expect(page.locator("#mode-offline")).toHaveClass(/active/);
  await expect(page.locator("#sync-gate-label")).toContainText("Closed");

  // Issue commands while offline via Local C2 buttons
  await page.locator("#patrol-area").click();
  await page.waitForTimeout(200);
  await page.locator("#replan-route").click();
  await page.waitForTimeout(200);
  await page.locator("#hold-position").click();
  await page.waitForTimeout(200);
  await page.locator("#return-home").click();
  await page.waitForTimeout(200);

  // Verify commands staged in sync queue (sync-count should be > 0)
  const stagedCount = await page.locator("#sync-count").textContent();
  expect(parseInt(stagedCount)).toBeGreaterThan(0);

  // Sync gate now shows "Held" (offline + spoolDepth > 0)
  await expect(page.locator("#sync-gate-label")).toContainText("Held");

  // Switch to degraded mode
  await page.locator("#mode-degraded").click();
  await expect(page.locator("#mode-status")).toContainText("Local C2 Active");
  await expect(page.locator("#mode-degraded")).toHaveClass(/active/);

  // Verify commands still work in degraded mode
  await page.locator("#resume-mission").click();
  await page.waitForTimeout(200);

  // Sync gate shows "Queued" in degraded mode
  await expect(page.locator("#sync-gate-label")).toContainText("Queued");

  // Verify more commands queued
  const stagedCount2 = await page.locator("#sync-count").textContent();
  expect(parseInt(stagedCount2)).toBeGreaterThanOrEqual(parseInt(stagedCount));

  // Switch to online mode
  await page.locator("#mode-online").click();
  await expect(page.locator("#mode-status")).toContainText("Enterprise Sync Enabled");
  await expect(page.locator("#mode-online")).toHaveClass(/active/);

  // Sync gate opens when online — shows "Releasable" or "Open"
  const onlineLabel = await page.locator("#sync-gate-label").textContent();
  expect(onlineLabel).toMatch(/Releasable|Open/);

  await page.screenshot({
    path: "test-results/tac-fuse-offline-swarm-control.png",
    fullPage: true,
  });
});

test("operator surface is dense and the selected POV is animated", async ({ page }) => {
  await page.goto(demoUrl);
  await page.waitForTimeout(900);

  await expect(page.locator("#pov-title")).toContainText("3D Field View");
  await expect(page.locator("#frame-counter")).toContainText("Field C2 View");
  await expect(page.locator("#frame-counter")).toContainText("Command Reachback Lost");
  await expect(page.locator("#mission-evidence")).toContainText("Route Guard Live");
  await expect(page.locator("#mission-evidence")).toContainText("Working System");
  await expect(page.locator("#mission-evidence")).toContainText("Route Continuity");
  await expect(page.locator("#mission-evidence")).toContainText("Edge Authority");
  await expect(page.locator("#mission-evidence")).toContainText("Drone NPUs");
  await expect(page.locator("#mission-evidence")).not.toContainText(/Problem Statement 2|Technical Demo 35%|Military Impact 30%|Creativity 25%/);
  await expect(page.locator("#mode-status")).toContainText("Fusion Node Authority");
  await expect(page.locator("#fusion-badge")).toContainText("Route Guard");
  await expect(page.locator(".metric-strip")).toContainText("Power");
  await expect(page.locator(".metric-strip")).toContainText("Sync");
  await expect(page.locator(".metric-strip")).toContainText("Plan");
  await expect(page.locator(".metric-strip")).not.toContainText(/object pass|objects quantified|restricted object|CPU route check/i);
  await expect(page.locator("#replan-route")).toContainText("Replan Route");
  await expect(page.locator("body")).not.toContainText("Route Solve");
  await expect(page.locator("#asset-list .feed-latency").first()).toHaveText(/^\d{1,3} ms$/);
  await expect(page.locator("#asset-list")).not.toContainText(/\d+\.\d{2,}\s*ms/);
  const labelCount = await page.locator(".target-label").count();
  expect(labelCount).toBeGreaterThan(0);
  expect(labelCount).toBeLessThanOrEqual(3);
  await expect(page.locator(".target-label").first()).toContainText(/%/);
  await expect(page.locator(".target-label").first()).toContainText(/\d+ m/);
  const targetClasses = (await page.locator(".target-label strong").allTextContents()).join(" ");
  expect(targetClasses).toMatch(/Unknown Ground Contact|Unknown Air Contact|Wheeled Vehicle|RF Source|Personnel|Small UAS|Quadrotor|Fixed Wing/);

  const commandBox = await page.locator(".command-panel").boundingBox();
  const metricsBox = await page.locator(".metric-strip").boundingBox();
  const povBox = await page.locator(".pov-shell").boundingBox();

  expect(commandBox).not.toBeNull();
  expect(metricsBox).not.toBeNull();
  expect(povBox).not.toBeNull();
  await expect(page.locator(".right-grid")).toBeHidden();
  expect(commandBox.width).toBeGreaterThan(520);
  expect(commandBox.height).toBeLessThan(90);
  expect(metricsBox.width).toBeGreaterThan(240);
  expect(metricsBox.height).toBeLessThan(82);
  expect(povBox.width).toBeGreaterThan(520);
  expect(povBox.height).toBeGreaterThan(410);

  const first = await canvasHash(page, "#pov-canvas");
  await page.locator("#replan-route").click();
  await expect(page.locator("#bvh-label")).toContainText(/Replanned|Caution Plan|Hold Pending ID/);
  await expect(page.locator("#staged-packet")).toContainText("Replan");
  await page.waitForTimeout(900);
  const second = await canvasHash(page, "#pov-canvas");

  expect(first.litPixels).toBeGreaterThan(250);
  expect(first.variedPixels).toBeGreaterThan(180);
  expect(second.hash).not.toBe(first.hash);

  await page.locator("#mode-degraded").click();
  await expect(page.locator("#mode-status")).toContainText("Local C2 Active");
  await expect(page.locator("#mode-degraded")).toHaveClass(/active/);

  await page.screenshot({
    path: "test-results/tac-fuse-operator-desktop.png",
    fullPage: true,
  });
});
