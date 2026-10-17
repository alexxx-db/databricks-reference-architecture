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
    for (const name of ['Lakebase', 'Genie App Builder', 'AI Search', 'Model Serving']) {
      const r = await page.evaluate((name) => {
        const cr = REGIONS.clouds[curCloud()], src = REGIONS.sources[curCloud()];
        const want = REGIONS.alias[name];
        const label = want ? Object.keys(cr.features).find(l => l.toLowerCase().startsWith(want.toLowerCase())) : null;
        const total = cr.regions.length;
        const count = label ? cr.regions.filter(x => cr.features[label][x.code]).length : total;
        const own = label && cr.feature_sources && cr.feature_sources[label];
        const cl = cloudLabelNow();
        const text = count === 0 ? 'Not yet available on ' + cl
          : count === total ? 'Available in all ' + total + ' ' + cl + ' regions'
          : 'Available in ' + count + ' of ' + total + ' ' + cl + ' regions';
        const href = own || (count === total ? src.supported : src.feature);
        const id = Object.keys(byId).find(k => byId[k].tile && byId[k].tile.n === name);
        openDetail(id);
        const pill = document.querySelector('#d-body .d-regsum');
        const got = { text: pill ? pill.textContent.replace(/\u2197/g, '').replace(/\s+/g, ' ').trim() : null, href: pill && pill.getAttribute('href') };
        closeDrawer();
        return { want: { text, href }, got, own: !!own };
      }, name);
      check(cloud + ': ' + name + ' shows what its source publishes', r.got.text === r.want.text, r.got.text);
      check(cloud + ': ' + name + ' links to that source' + (r.own ? ' (its own page)' : ''), r.got.href === r.want.href, r.got.href);
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

  {
    const { ctx, page } = await open('', 1600);
    const r = await page.evaluate(() => { const a = document.getElementById('ai-link'); return { shown: getComputedStyle(a).display !== 'none', href: a.href, title: a.title }; });
    check('the public board shows the AI assistant pointer', r.shown && /#ai-architecture-assistant-appai$/.test(r.href) && /Databricks App/.test(r.title), r.href);
    const inApp = await page.evaluate(() => { const f = document.createElement('button'); f.id = 'ai-fab'; document.body.appendChild(f); return getComputedStyle(document.getElementById('ai-link')).display; });
    check('the pointer hides where the AI app is running', inApp === 'none', inApp);
    await ctx.close();
  }
  {
    const { ctx, page } = await open('', 1200);
    const d = await page.evaluate(() => getComputedStyle(document.getElementById('ai-link')).display);
    check('the pointer steps aside on narrow headers', d === 'none', d);
    await ctx.close();
  }

  check('no page errors', errors.length === 0, errors.slice(0, 3).join(' | '));
  await browser.close();
  server.close();
  const failed = results.filter(r => !r.ok);
  console.log('\n' + (results.length - failed.length) + '/' + results.length + ' checks passed');
  process.exit(failed.length ? 1 : 0);
})();
