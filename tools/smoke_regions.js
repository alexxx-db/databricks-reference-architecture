#!/usr/bin/env node
'use strict';
const { chromium } = require('playwright');
const { serve, boardReady } = require('./lib_serve');

const results = [];
function check(name, cond, detail) { results.push({ name, ok: !!cond, detail }); console.log((cond ? 'PASS ' : 'FAIL ') + name + (detail ? ' :: ' + detail : '')); }

(async () => {
  const server = await serve();
  const base = 'http://127.0.0.1:' + server.address().port + '/index.html';
  const browser = await chromium.launch();
  const errors = [];
  const open = async (q, width) => {
    const ctx = await browser.newContext({ viewport: { width: width || 1600, height: 1000 } });
    await ctx.addInitScript(() => { try { localStorage.setItem('dbx-arch-tour-v1', '1'); } catch (e) {} });
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + q, { waitUntil: 'networkidle' });
    await boardReady(page);
    await page.waitForTimeout(500);
    return { ctx, page };
  };

  for (const cloud of ['aws', 'azure', 'gcp']) {
    const { ctx, page } = await open('?cloud=' + cloud);
    for (const name of ['Lakebase', 'Genie App Builder', 'AI Search', 'Model Serving', 'Unity Catalog']) {
      const r = await page.evaluate((name) => {
        const id = Object.keys(byId).find(k => byId[k].tile && byId[k].tile.n === name);
        openDetail(id);
        const body = document.getElementById('d-body');
        const out = { line: !!body.querySelector('.d-region, .d-regsum'),
          text: /Available in|Regional availability|Not yet available on/.test(body.textContent) };
        closeDrawer();
        return out;
      }, name);
      check(cloud + ': ' + name + "'s panel shows no regional availability", !r.line && !r.text, JSON.stringify(r));
    }
    const dim = await page.evaluate(() => {
      const cr = REGIONS.clouds[curCloud()], col = cr.features['Lakebase (product page)'];
      const out = cr.regions.find(x => !col[x.code]), inn = cr.regions.find(x => col[x.code]);
      const lakebase = () => [...document.querySelectorAll('.atom')].find(a => byId[a.dataset.id] && byId[a.dataset.id].tile.n === 'Lakebase');
      const res = {};
      if (out) { setRegion(out.code); res.outside = lakebase().classList.contains('rg-off'); }
      if (inn) { setRegion(inn.code); res.inside = lakebase().classList.contains('rg-off'); }
      setRegion('');
      return res;
    });
    if ('outside' in dim) check(cloud + ': a region Lakebase does not list dims it', dim.outside === true);
    if ('inside' in dim) check(cloud + ': a region Lakebase lists keeps it lit', dim.inside === false);
    await ctx.close();
  }

  check('no page errors', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();
  server.close();
  const failed = results.filter(r => !r.ok);
  console.log('\n' + (results.length - failed.length) + '/' + results.length + ' checks passed');
  process.exit(failed.length ? 1 : 0);
})();
