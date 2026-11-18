import { expect, Page } from "@playwright/test";
import { join } from "node:path";

export const demoVideo = () => join(process.env.E2E_DATA_DIR!, "demo.mp4");

/** Upload the demo recording and wait for the highlights to appear. */
export async function uploadDemo(page: Page) {
  await page.goto("/");
  await page.setInputFiles("input[type=file]", demoVideo());
  await page.getByRole("button", { name: "Find my highlights" }).click();
  await page.waitForURL(/\/videos\//);
  await expect(page.locator("#highlights-heading")).toBeVisible({ timeout: 90_000 });
}
