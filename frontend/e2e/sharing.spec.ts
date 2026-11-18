import { expect, test } from "@playwright/test";

import { uploadDemo } from "./helpers";

test("workspaces are private, and a share link works for anyone", async ({ page, browser }) => {
  await uploadDemo(page);
  await page.getByRole("button", { name: "Export clip" }).click();
  await expect(page.getByRole("link", { name: "Download", exact: true })).toBeVisible({ timeout: 90_000 });
  const sessionUrl = page.url();

  // A different browser can't see the session...
  const stranger = await browser.newContext();
  const other = await stranger.newPage();
  await other.goto(sessionUrl);
  await expect(other.getByText("That session doesn't exist.")).toBeVisible();

  // ...but can open a shared clip, which carries link-preview tags.
  const shared = await page.request.post(
    `/api/clips/${(await page.request.get(`${sessionUrl.replace("/videos/", "/api/videos/")}/clips`).then((r) => r.json()))[0].id}/share`,
  );
  const shareUrl = (await shared.json()).share_url as string;
  await other.goto(shareUrl);
  await expect(other.getByRole("link", { name: "Download clip" })).toBeVisible();
  expect(await other.locator('meta[property="og:video"]').count()).toBe(1);
  await stranger.close();
});
