const { chromium } = require('playwright');
// Store screenshots from the built-in demo. Run: npm run build && npx vite preview --port 5174, then
// node scripts/storeshots.cjs store/screenshots   (needs Playwright with Chromium)
const OUT = process.argv[2] || "store/screenshots";
const sets = [
  { name: 'iphone-6.9', viewport: { width: 440, height: 956 }, dsf: 3 },
  { name: 'android-phone', viewport: { width: 360, height: 640 }, dsf: 3 },
];
(async () => {
  const b = await chromium.launch();
  for (const s of sets) {
    const ctx = await b.newContext({ viewport: s.viewport, deviceScaleFactor: s.dsf, isMobile: true, hasTouch: true,
      geolocation: { latitude: -32.2876, longitude: 22.5287, accuracy: 5 }, permissions: ['geolocation'] });
    const p = await ctx.newPage();
    const errs = [];
    p.on('pageerror', e => errs.push(e.message));
    let n = 0;
    const shot = async (label) => { await p.waitForTimeout(1200); await p.screenshot({ path: `${OUT}/${s.name}-${++n}-${label}.png` }); };
    await p.goto('http://127.0.0.1:5174/');
    await p.click('#demo');
    await p.waitForSelector('[data-flight]');
    await p.click('[data-flight]');
    await p.waitForSelector('.summary .pill');
    await p.waitForTimeout(1500);
    await shot('map');
    await p.click('[data-tab=list]');
    await shot('list');
    await p.click('.hrow >> nth=0');
    await p.waitForSelector('#i-t[src]');
    await shot('hotspot');
    await p.click('[data-act=back]');
    await p.click('#drive');
    await shot('drive');
    const t = await p.evaluate(() => document.querySelector('.dcard span').textContent);
    const [lat, lon] = t.split(',').map(Number);
    await ctx.setGeolocation({ latitude: lat + 0.00012, longitude: lon - 0.0001, accuracy: 4 });
    await shot('arrived');
    await p.click('[data-act=back]');
    await p.click('[data-act=back]');
    await p.click('[data-act=back]');
    await p.waitForSelector('#demo');
    await p.click('[data-go=pair]');
    await shot('pair');
    console.log(s.name, 'errors:', errs);
    await ctx.close();
  }
  await b.close();
})();
