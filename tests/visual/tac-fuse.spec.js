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

test("operator surface is dense and the selected POV is animated", async ({ page }) => {
  await page.goto(demoUrl);
  await page.waitForTimeout(900);

  await expect(page.locator("#pov-title")).toContainText("3D Field View");
  await expect(page.locator("#frame-counter")).toContainText("Field C2 View");
  await expect(page.locator("#mode-status")).toContainText("Fusion Node Authority");
  await expect(page.locator("#fusion-badge")).toContainText("Route Guard");
  await expect(page.locator(".metric-strip")).toContainText("Power");
  await expect(page.locator(".metric-strip")).toContainText("Sync");
  await expect(page.locator(".metric-strip")).not.toContainText(/object pass|objects quantified|restricted object|CPU route check/i);
  await expect(page.locator("#asset-list .feed-latency").first()).toHaveText(/^\d{1,3} ms$/);
  await expect(page.locator("#asset-list")).not.toContainText(/\d+\.\d{2,}\s*ms/);
  const labelCount = await page.locator(".target-label").count();
  expect(labelCount).toBeGreaterThan(0);
  expect(labelCount).toBeLessThanOrEqual(3);
  await expect(page.locator(".target-label").first()).toContainText(/%/);
  await expect(page.locator(".target-label").first()).toContainText(/\d+ m/);
  const targetClasses = (await page.locator(".target-label strong").allTextContents()).join(" ");
  expect(targetClasses).toMatch(/Wheeled Vehicle|RF Source|Personnel|Small UAS|Quadrotor|Fixed Wing/);

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
