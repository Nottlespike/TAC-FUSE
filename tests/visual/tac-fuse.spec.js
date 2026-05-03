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

  await expect(page.locator("#pov-title")).toContainText("POV");
  await expect(page.locator(".capability-strip")).toContainText("Laptop fusion node");
  await expect(page.locator("#field-condition-label")).toContainText(/feeds fused/);
  await expect(page.locator("#npu-label")).not.toContainText(/NPU|Intel/i);

  const commandBox = await page.locator(".command-panel").boundingBox();
  const metricsBox = await page.locator(".metric-strip").boundingBox();
  const povBox = await page.locator(".pov-shell").boundingBox();
  const lowerGridBox = await page.locator(".right-grid").boundingBox();

  expect(commandBox).not.toBeNull();
  expect(metricsBox).not.toBeNull();
  expect(povBox).not.toBeNull();
  expect(lowerGridBox).not.toBeNull();
  expect(metricsBox.height).toBeLessThan(commandBox.height * 0.75);
  expect(povBox.height).toBeGreaterThan(lowerGridBox.height * 1.15);

  const first = await canvasHash(page, "#pov-canvas");
  await page.waitForTimeout(900);
  const second = await canvasHash(page, "#pov-canvas");

  expect(first.litPixels).toBeGreaterThan(250);
  expect(first.variedPixels).toBeGreaterThan(180);
  expect(second.hash).not.toBe(first.hash);

  await page.screenshot({
    path: "test-results/tac-fuse-operator-desktop.png",
    fullPage: true,
  });
});
