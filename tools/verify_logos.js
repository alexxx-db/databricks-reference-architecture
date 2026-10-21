#!/usr/bin/env node
'use strict';
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { serve, boardReady } = require('./lib_serve');

const LOGO_DIR = path.join(__dirname, '..', 'app', 'resources', 'logos');
const CLOUDS = ['aws', 'azure', 'gcp'];
const UNSAFE = /<(image|script|foreignObject)\b|\bhref="(https?:|data:|javascript:)|\son[a-z]+=/i;

const results = [];
function check(name, cond, detail) { results.push({ name, ok: !!cond, detail }); console.log((cond ? 'PASS ' : 'FAIL ') + name + (detail ? ' :: ' + detail : '')); }

function audit() {
  const set = LOGO_SETS[curCloud()] || { tiles: {}, art: {} };
  const label = document.querySelector('#cloud .cloud-lbl');
  const wrong = [], missing = [], marksMissing = [], plates = new Set();
  let logos = 0;
  for (const el of document.querySelectorAll('.atom')) {
    const rec = byId[el.dataset.id], t = rec && rec.tile;
    if (!t) continue;
    const icons = [...el.querySelectorAll('svg')].filter(s => s.closest('.atom') === el && !s.closest('.zx, .badge-dot, .addbtn'));
    const own = icons.filter(s => s.classList.contains('logo'));
    const want = !!set.tiles[t.n] && !shownByCategory(t) && !PRODUCT_MARKS[t.mark || t.n] && !t.fmt && !t.brand;
    if (own.length) { logos++; own.forEach(s => plates.add(s.querySelector('rect').getAttribute('fill'))); }
    if (want && !own.length && icons.length) missing.push(t.n);
    if (!want && own.length) wrong.push(t.n);
    if (icons.length && !t.fmt && !t.brand && PRODUCT_MARKS[t.mark || t.n] && !icons.some(s => s.classList.contains('mark'))) marksMissing.push(t.n);
  }
  const prov = label && label.querySelector('svg.provlogo');
  return { cloud: curCloud(), provLabel: prov ? prov.getAttribute('aria-label') : null, chip: !!(label && label.querySelector('.provchip')),
    provPlate: prov ? prov.querySelector('rect').getAttribute('fill') : null, logos, missing: [...new Set(missing)], wrong: [...new Set(wrong)],
    marksMissing: [...new Set(marksMissing)], plates: [...plates] };
}

(async () => {
  for (const cloud of CLOUDS) {
    const b = JSON.parse(fs.readFileSync(path.join(LOGO_DIR, cloud + '.json'), 'utf8'));
    const dangling = Object.entries(b.tiles).filter(([, k]) => !b.art[k]).map(([n]) => n);
    const unused = Object.keys(b.art).filter(k => !Object.values(b.tiles).includes(k));
    const unsourced = Object.keys(b.art).filter(k => !b.src || !b.src[k]);
    const unsafe = Object.keys(b.art).filter(k => UNSAFE.test(b.art[k]));
    check(cloud + ' bundle: every tile points at artwork, every artwork is used and names its source',
      !dangling.length && !unused.length && !unsourced.length, JSON.stringify({ dangling, unused, unsourced }));
    check(cloud + ' bundle: no artwork carries an external reference or a script', !unsafe.length, unsafe.join(', '));
  }

  const server = await serve();
  const base = 'http://127.0.0.1:' + server.address().port + '/index.html';
  const browser = await chromium.launch();
  const errors = [];
  const open = async (q, dark) => {
    const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, colorScheme: dark ? 'dark' : 'light' });
    await ctx.addInitScript(() => { try { localStorage.setItem('dbx-arch-tour-v1', '1'); } catch (e) {} });
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(base + q, { waitUntil: 'networkidle' });
    await boardReady(page);
    if (dark) await page.evaluate(() => applyTheme(true, false));
    await page.waitForTimeout(300);
    return { ctx, page };
  };
  const labels = { aws: 'AWS', azure: 'Azure', gcp: 'GCP' };

  for (const cloud of CLOUDS) {
    for (const [q, label] of [['?cloud=' + cloud, 'generic board'], ['?industry=banking&display=branded&cloud=' + cloud, 'banking, branded'],
                              ['?industry=banking&display=category&cloud=' + cloud, 'banking, categorized']]) {
      const { ctx, page } = await open(q);
      const r = await page.evaluate(audit);
      const tag = cloud + ', ' + label;
      check(tag + ': the band label shows the ' + labels[cloud] + ' logo on a light plate, not a text chip',
        r.provLabel === labels[cloud] && !r.chip && r.provPlate === '#ffffff', JSON.stringify({ prov: r.provLabel, chip: r.chip, plate: r.provPlate }));
      check(tag + ': every cloud tile that shows its own name shows its official icon', !r.missing.length, r.missing.join(', '));
      check(tag + ': no tile outside the cloud set, and no tile showing a category, carries a logo', !r.wrong.length, r.wrong.join(', '));
      check(tag + ': every Databricks box with an official mark shows it', !r.marksMissing.length, r.marksMissing.join(', '));
      check(tag + ': logos drawn and every plate is white', r.logos > 0 && r.plates.every(p => p === '#ffffff'), 'logos=' + r.logos + ' plates=' + r.plates.join(','));
      await ctx.close();
    }
  }

  {
    const { ctx, page } = await open('?industry=banking&display=branded&cloud=gcp', true);
    const r = await page.evaluate(audit);
    check('dark theme: the plates stay white and the logos still draw', r.logos > 0 && r.plates.every(p => p === '#ffffff') && r.provPlate === '#ffffff',
      'logos=' + r.logos + ' plates=' + r.plates.join(',') + ' label=' + r.provPlate);
    await ctx.close();
  }

  {
    const { ctx, page } = await open('?cloud=aws');
    const before = await page.evaluate(() => Object.keys(LOGO_SETS));
    await page.click('#cloud-seg button:has-text("Azure")');
    await page.waitForFunction(() => !!LOGO_SETS.azure && document.querySelectorAll('svg.logo').length > 0 && curCloud() === 'azure', null, { timeout: 8000 }).catch(() => {});
    const r = await page.evaluate(audit);
    check('a cloud switch loads only that cloud\'s icons, then draws them', before.join() === 'aws' && r.cloud === 'azure' && r.provLabel === 'Azure' && !r.missing.length && r.logos > 0,
      JSON.stringify({ before, cloud: r.cloud, prov: r.provLabel, missing: r.missing, logos: r.logos }));
    const doc = await page.evaluate(() => exportHtmlDoc());
    const frozen = JSON.parse((doc.match(/<script type="application\/json" id="frozen-resources">([\s\S]*?)<\/script>/) || [, '{}'])[1]);
    check('the offline HTML export freezes the logo sets it has loaded', frozen.logos && frozen.logos.azure && frozen.logos.aws, Object.keys(frozen.logos || {}).join(','));
    await ctx.close();
    const file = path.join(os.tmpdir(), 'verify_logos_export.html');
    fs.writeFileSync(file, doc);
    const op = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
    op.on('pageerror', e => errors.push('offline: ' + e.message));
    op.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|Fetch API cannot load file:/.test(m.text())) errors.push('offline: ' + m.text()); });
    await op.goto('file://' + file, { waitUntil: 'load' });
    await boardReady(op);
    await op.waitForTimeout(800);
    const o = await op.evaluate(() => ({ logos: document.querySelectorAll('svg.logo').length, prov: !!document.querySelector('#cloud svg.provlogo'), cloud: curCloud() }));
    check('the exported file, opened from disk where no resource can be fetched, draws the cloud logos', o.logos > 0 && o.prov, JSON.stringify(o));
    await op.close();
    fs.unlinkSync(file);
  }

  check('no page or console errors, so every icon path parses', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();
  server.close();
  const failed = results.filter(r => !r.ok);
  console.log((failed.length ? 'FAIL ' : 'PASS ') + (results.length - failed.length) + '/' + results.length);
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
