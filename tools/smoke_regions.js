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
    const every = await page.evaluate(() => {
      const cr = REGIONS.clouds[curCloud()], out = { cases: 0, bad: [] };
      const atom = n => [...document.querySelectorAll('.atom')].find(a => byId[a.dataset.id] && byId[a.dataset.id].tile.n === n);
      for (const name of Object.keys(REGIONS.alias)) {
        const el = atom(name);
        if (!el) continue;
        const t = byId[el.dataset.id].tile, lab = regionFeatureLabel(t);
        if (!lab || stageKey(stageFor(t)) === 'soon') continue;
        const col = cr.features[lab];
        for (const [r, want] of [[cr.regions.find(x => !col[x.code]), true], [cr.regions.find(x => col[x.code]), false]]) {
          if (!r) continue;
          setRegion(r.code);
          out.cases++;
          if (atom(name).classList.contains('rg-off') !== want) out.bad.push(name + (want ? ' stays lit in ' : ' dims in ') + r.code);
        }
      }
      setRegion('');
      return out;
    });
    check(cloud + ': every mapped product dims where its docs column says no and stays lit where it says yes (' + every.cases + ' cases)',
      every.cases > 0 && !every.bad.length, every.bad.slice(0, 4).join(', '));
    if (cloud === 'azure') {
      const qatar = await page.evaluate(() => {
        const dimmed = n => { const a = [...document.querySelectorAll('.atom')].find(x => byId[x.dataset.id] && byId[x.dataset.id].tile.n === n); return a && a.classList.contains('rg-off'); };
        setRegion('qatarcentral');
        const out = { serverless: dimmed('Serverless Compute'), serving: dimmed('Model Serving'), uc: dimmed('Unity Catalog') };
        setRegion('westeurope');
        out.westServerless = dimmed('Serverless Compute');
        setRegion('');
        return out;
      });
      check('azure: Qatar Central dims Serverless Compute and Model Serving and keeps Unity Catalog; West Europe keeps serverless',
        qatar.serverless === true && qatar.serving === true && qatar.uc === false && qatar.westServerless === false, JSON.stringify(qatar));
    }
    await ctx.close();
  }

  check('no page errors', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();
  server.close();
  const failed = results.filter(r => !r.ok);
  console.log('\n' + (results.length - failed.length) + '/' + results.length + ' checks passed');
  process.exit(failed.length ? 1 : 0);
})();
