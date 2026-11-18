import { expect, test } from "@playwright/test";

import { uploadDemo } from "./helpers";

test("upload, find highlights, export and download a clip", async ({ page }) => {
  await uploadDemo(page);
  const cards = page.locator("section[aria-labelledby=highlights-heading] button:has(img)");
  await expect(cards).toHaveCount(3);
  await expect(page.getByText("Shootout").first()).toBeVisible();

  await page.getByRole("button", { name: "Export clip" }).click();
  const download = page.getByRole("link", { name: "Download", exact: true });
  await expect(download).toBeVisible({ timeout: 90_000 });
  const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);
  expect(file.suggestedFilename()).toMatch(/^clipwizard-.*\.mp4$/);
});

test("captions can be reviewed and edited before export", async ({ page }) => {
  await uploadDemo(page);
  await page.getByRole("button", { name: "Review words" }).click();
  const first = page.getByLabel("Caption line 1");
  await expect(first).toBeVisible();
  await first.fill("NO WAY");
  const request = page.waitForRequest((r) => r.url().endsWith("/clips") && r.method() === "POST");
  await page.getByRole("button", { name: "Export clip" }).click();
  const body = (await request).postDataJSON();
  expect(body.caption_words[0].text).toBe("NO");
  expect(body.caption_words[1].text).toBe("WAY");
});

test("keyboard shortcuts set the clip range", async ({ page }) => {
  await uploadDemo(page);
  await page.locator("h1").click();
  await page.evaluate(() => (document.querySelector("video")!.currentTime = 3));
  await page.waitForTimeout(300);
  await page.keyboard.press("i");
  await page.evaluate(() => (document.querySelector("video")!.currentTime = 11));
  await page.waitForTimeout(300);
  await page.keyboard.press("o");
  await expect(page.getByLabel("Start", { exact: true })).toHaveValue("0:03.0");
  await expect(page.getByLabel("End", { exact: true })).toHaveValue("0:11.0");
});

test("unknown pages show a not-found message", async ({ page }) => {
  await page.goto("/definitely/not/here");
  await expect(page.getByText("That page doesn't exist.")).toBeVisible();
});

test("timeline handles trim the clip by dragging or with arrow keys", async ({ page }) => {
  await uploadDemo(page);
  const strip = (await page.getByLabel("Video timeline").boundingBox())!;
  const end = (await page.getByLabel("Clip end").boundingBox())!;
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2);
  await page.mouse.down();
  await page.mouse.move(strip.x + strip.width * (40 / 90), end.y + end.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByLabel("End", { exact: true })).toHaveValue("0:40.0");

  await page.getByLabel("Clip start").focus();
  await page.keyboard.press("Shift+ArrowLeft");
  await page.keyboard.press("Shift+ArrowLeft");
  await expect(page.getByLabel("Start", { exact: true })).toHaveValue("0:19.0");
});
