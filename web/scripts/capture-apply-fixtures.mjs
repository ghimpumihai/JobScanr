// Saves the rendered application form of real apply pages as offline test fixtures (#129, Task 3.4).
// Live: opens each page once in local headless Chromium, types nothing, clicks nothing, submits nothing.
// Usage: node scripts/capture-apply-fixtures.mjs --confirm-live <platform> <url> [<platform> <url> ...]
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

const args = process.argv.slice(2);
if (args[0] !== '--confirm-live' || args.length < 3 || args.length % 2 === 0) {
  console.error('Refusing to run: pass --confirm-live followed by <platform> <url> pairs.');
  process.exit(2);
}
const OUT = new URL('../tests/fixtures/apply/', import.meta.url);
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
/** Next unused <platform>-<n>.html, so a second run never overwrites earlier captures. */
function nextFile(platform) {
  for (let n = 1; ; n += 1) if (!existsSync(new URL(`${platform}-${n}.html`, OUT))) return `${platform}-${n}.html`;
}
try {
  for (let i = 1; i < args.length; i += 2) {
    const [platform, url] = [args[i], args[i + 1]];
    const page = await browser.newPage();
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.locator('input[type=file]').first().waitFor({ state: 'attached', timeout: 20000 });
      // The smallest element holding every input, stripped of scripts, frames, external resources and handlers.
      const html = await page.evaluate(() => {
        const inputs = [...document.querySelectorAll('input, textarea, select')];
        let root = inputs[0]?.closest('form') ?? inputs[0]?.parentElement ?? document.body;
        while (root && !inputs.every((el) => root.contains(el))) root = root.parentElement;
        const copy = (root ?? document.body).cloneNode(true);
        copy.querySelectorAll('script, iframe, link, style, img, svg, noscript, object, embed').forEach((el) => el.remove());
        // Country and location lists can hold thousands of options; 50 keep the shape without megabytes.
        copy.querySelectorAll('select').forEach((s) => [...s.options].slice(50).forEach((o) => o.remove()));
        // Hidden inputs can carry whole page state (Lever: ~1 MB); the fill engine never reads them.
        copy.querySelectorAll('input[type=hidden]').forEach((el) => el.value.length > 2000 && el.setAttribute('value', ''));
        for (const el of [copy, ...copy.querySelectorAll('*')]) {
          for (const attr of [...el.attributes]) {
            if (/^on/i.test(attr.name) || ((attr.name === 'href' || attr.name === 'src' || attr.name === 'action') && !attr.value.startsWith('#'))) {
              el.removeAttribute(attr.name);
            }
          }
        }
        return copy.outerHTML;
      });
      const file = nextFile(platform);
      writeFileSync(new URL(file, OUT), `<!-- source: ${url} | captured ${new Date().toISOString().slice(0, 10)} -->\n${html}\n`);
      console.log(`saved ${file} (${html.length} chars) from ${url}`);
    } catch (err) {
      console.log(`skipped ${url}: ${String(err).split('\n')[0]}`);
    } finally {
      await page.close();
    }
    await new Promise((r) => setTimeout(r, 2000)); // one page at a time, paced
  }
} finally {
  await browser.close();
}
