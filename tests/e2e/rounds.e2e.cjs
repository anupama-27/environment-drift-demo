// Rounds view on seed 5. Run with the site served at the given URL:
//   NODE_PATH=$(npm root -g) node tests/e2e/rounds.e2e.cjs http://localhost:8821
const { launch } = require('./helper.cjs');

const base = (process.argv[2] || 'http://localhost:8821').replace(/\/$/, '');
const shots = process.env.E2E_SHOTS || '/tmp/shots/w2';
const failures = [];
const noise = [];

function check(ok, message) {
  if (!ok) failures.push(message);
  console.log((ok ? 'ok    ' : 'FAIL  ') + message);
}

async function rowsInfo(page) {
  return page.$$eval('.rounds tr[data-round]', (rows) => rows.map((r) => ({
    round: Number(r.getAttribute('data-round')),
    check: r.getAttribute('data-check'),
    cause: r.getAttribute('data-cause'),
    text: r.innerText
  })));
}

async function cellText(page, round, column) {
  return page.$eval(`.rounds tr[data-round="${round}"]`, (row, col) => {
    const heads = Array.from(row.closest('table').querySelectorAll('thead th')).map((th) => th.textContent.trim());
    return row.children[heads.indexOf(col)].textContent.trim();
  }, column);
}

(async () => {
  require('fs').mkdirSync(shots, { recursive: true });
  const browser = await launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const fetched = [];
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') noise.push(m.type() + ': ' + m.text());
  });
  page.on('pageerror', (e) => noise.push('page error: ' + e.message));
  page.on('request', (r) => { if (/\.json\.gz$|\.jsonl$/.test(r.url())) fetched.push(r.url()); });

  try {
    await page.goto(base + '/#/workbench/rounds');
    await page.waitForSelector('.rounds tr[data-round]', { timeout: 15000 });

    let rows = await rowsInfo(page);
    check(rows.length === 11, `frozen ledger has 11 rows (got ${rows.length})`);
    const staleFa = rows.filter((r) => r.check === 'false-accept' && r.cause === 'stale').map((r) => r.round);
    check(JSON.stringify(staleFa) === '[5,8,10]', `rounds 5, 8 and 10 are stale-reference false accepts (got ${staleFa})`);
    check(staleFa.every((n) => /false accept/.test(rows[n].text) && /stale reference/.test(rows[n].text)), 'those rows read "false accept" and "stale reference"');
    check(rows[3].check === 'false-accept' && rows[3].cause === 'no_drift' && /no environment change/.test(rows[3].text),
      'round 3 is a false accept without environment change');
    check(/Round 5:/.test(await page.textContent('#rounds-detail-title')), 'default selection is the first stale-reference false accept');

    const chartMarked = await page.evaluate(() => {
      const svg = document.querySelector('.rounds__chart svg');
      svg.daProbe = true;
      return !!svg;
    });
    check(chartMarked, 'the chart is drawn');

    await page.click('.rounds tr[data-round="8"] .rounds__pick');
    await page.waitForFunction(() => /Round 8:/.test(document.querySelector('#rounds-detail-title').textContent));
    check(await cellText(page, 8, 'Stored') === '21 to 18', 'round 8 stored reading is 21 to 18');
    check(await cellText(page, 8, 'Rerun') === '16 to 22', 'round 8 rerun reading is 16 to 22');
    const story = (await page.textContent('.rounds__story')).replace(/\u00a0/g, ' ');
    check(/wins 21 items and loses 18/.test(story) && /wins 16 and loses 22/.test(story), 'the round 8 sentences carry the same numbers' + (/wins 21/.test(story) ? '' : ': ' + story));
    check(await page.evaluate(() => document.querySelector('.rounds__chart svg').daProbe === true), 'selecting a round keeps the drawn chart');
    check(await page.evaluate(() => document.querySelector('.rounds__hit.is-selected').getAttribute('data-hit')) === '8', 'the chart outlines round 8');

    const counts = await page.evaluate(() => ({
      stored: document.querySelectorAll('.plate__grid[data-plate-grid="stored"] .plate__cell').length,
      rerun: document.querySelectorAll('.plate__grid[data-plate-grid="rerun"] .plate__cell').length,
      changedStored: document.querySelectorAll('.plate__grid[data-plate-grid="stored"] .plate__cell.is-changed').length,
      changedRerun: document.querySelectorAll('.plate__grid[data-plate-grid="rerun"] .plate__cell.is-changed').length
    }));
    const truth = await page.evaluate(() => {
      const d = DA.state.get().audit.policies.frozen.decisions.filter((x) => x.round === 8)[0];
      const c = DA.engine.itemCells(DA.library.run(), d);
      let n = 0;
      for (let i = 0; i < c.stored.length; i++) if (c.stored[i] !== c.rerun[i]) n++;
      return { n, stored: c.stored, rerun: c.rerun };
    });
    check(counts.stored === 200 && counts.rerun === 200, `the plate shows 200 cells per reading (${counts.stored}, ${counts.rerun})`);
    check(counts.changedStored === truth.n && counts.changedRerun === truth.n, `changed cells (${counts.changedStored}) match the ${truth.n} differing positions`);

    const before = fetched.length;
    let target = -1;
    for (let i = truth.stored.length - 1; i >= 0; i--) if (truth.stored[i] !== truth.rerun[i]) { target = i; break; }
    await page.click(`.plate__grid[data-plate-grid="stored"] .plate__cell[data-i="${target}"]`);
    await page.waitForFunction((i) => {
      const t = document.querySelector('#rounds-item-title');
      return t && t.textContent.split(' ').slice(0, 2).join(' ') === 'Item ' + (i + 1) && document.querySelectorAll('[data-rounds-item] [data-block][data-right]').length === 3;
    }, target, { timeout: 15000 });
    const item = await page.evaluate(() => ({
      question: (document.querySelector('.rounds__question') || { textContent: '' }).textContent.trim(),
      blocks: Array.from(document.querySelectorAll('[data-rounds-item] [data-block]')).map((b) => ({
        id: b.getAttribute('data-block'), right: b.getAttribute('data-right'), text: b.querySelector('.rounds__out').textContent
      }))
    }));
    const s = truth.stored[target], r = truth.rerun[target];
    const expect = { candidate: s === 'w' || s === 'b', stored: s === 'l' || s === 'b', rerun: r === 'l' || r === 'b' };
    check(item.question.length > 20, 'a changed cell shows its question');
    check(item.blocks.length === 3 && item.blocks.every((b) => b.text.length > 0), 'three outputs are shown');
    check(item.blocks.every((b) => b.right === String(expect[b.id])), `scorer readings agree with the cell (${s}/${r}: ${item.blocks.map((b) => b.id + '=' + b.right).join(', ')})`);

    const afterFirst = fetched.length;
    await page.keyboard.press('ArrowLeft');
    await page.keyboard.press('Enter');
    await page.waitForFunction((i) => document.querySelector('#rounds-item-title').textContent.split(' ').slice(0, 2).join(' ') === 'Item ' + i, target);
    check(true, 'a plate cell is operable from the keyboard');
    await page.click('.rounds tr[data-round="5"] .rounds__pick');
    await page.waitForFunction(() => /Round 5:/.test(document.querySelector('#rounds-detail-title').textContent));
    await page.click('.rounds tr[data-round="8"] .rounds__pick');
    await page.waitForFunction(() => /Round 8:/.test(document.querySelector('#rounds-detail-title').textContent));
    await page.waitForTimeout(300);
    check(new Set(fetched).size === fetched.length, `nothing was fetched twice (${fetched.length} requests, ${afterFirst - before} for the first item)`);
    check(await page.evaluate(() => document.querySelector('.rounds__chart svg').daProbe === true), 'the chart survives round changes');

    await page.screenshot({ path: shots + '/rounds-1440.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check(overflow <= 0, `nothing scrolls sideways at 390px (${overflow}px)`);
    await page.screenshot({ path: shots + '/rounds-390.png', fullPage: true });
    await page.setViewportSize({ width: 1440, height: 900 });

    await page.click('.segmented__option[data-value="env_triggered"]');
    await page.waitForFunction(() => /environment-triggered/.test(document.querySelector('.rounds h1').textContent));
    rows = await rowsInfo(page);
    const promotions = rows.filter((x) => x.check === 'improvement' || x.check === 'false-accept').length;
    const falseAccepts = rows.filter((x) => x.check === 'false-accept').length;
    check(rows.length === 11 && promotions === 3 && falseAccepts === 1, `environment-triggered: 3 promotions and 1 false accept (got ${promotions}, ${falseAccepts})`);

    await page.selectOption('select[name="run"]', '*');
    await page.waitForFunction(() => document.querySelectorAll('.rounds [data-pick-run]').length === 5, null, { timeout: 15000 });
    check(await page.locator('.rounds .plate').count() === 0, 'all runs: no plate');
    check(await page.locator('.rounds [data-pick-run]').count() === 5, 'all runs: five rows');
    await page.click('.rounds [data-pick-run="gsm8k-qwen2.5-1.5b-seed2"]');
    await page.waitForSelector('.rounds tr[data-round]');
    check(await page.inputValue('select[name="run"]') === 'gsm8k-qwen2.5-1.5b-seed2', 'choosing a row selects that run');
  } catch (err) {
    check(false, 'the run stopped: ' + (err && err.message));
  }

  await browser.close();
  noise.forEach((n) => check(false, 'console ' + n));
  console.log(failures.length ? `\n${failures.length} failed` : '\nall passed');
  process.exit(failures.length ? 1 : 0);
})();
