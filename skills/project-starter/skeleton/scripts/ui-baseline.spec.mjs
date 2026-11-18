// 每页每个宽度一张整页截图，由 node scripts/ui-baseline.mjs shoot | compare 调起，不单独跑。等待和比较规则见 ui-baseline.mjs 开头。
import { expect, test } from '@playwright/test';
import { readPages, ROOT } from './ui-baseline.mjs';

for (const p of readPages(ROOT).pages) {
  for (const width of p.widths) {
    test(`${p.name} @${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(p.url, { waitUntil: 'load' });
      await page.evaluate(() => document.fonts.ready);
      await expect(page).toHaveScreenshot(`${p.name}-${width}.png`, { fullPage: true, mask: p.mask.map(s => page.locator(s)) });
    });
  }
}
