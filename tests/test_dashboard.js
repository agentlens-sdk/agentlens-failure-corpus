// Runs the real inline script from site/index.html against one or more stats.json files, with
// minimal DOM stubs. Catches the things that actually break this dashboard between nightly runs:
// a missing field, a null pass_rate, a chart built from a series that does not exist yet.
//
// Run: node tests/test_dashboard.js [stats.json ...]     (defaults to site/stats.json)
// Optional: needs node, which the corpus itself does not.
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const HTML = fs.readFileSync(path.join(ROOT, 'site/index.html'), 'utf8');
const SCRIPT = HTML.match(/<script>([\s\S]*?)<\/script>\s*<\/body>/)[1];
const files = process.argv.slice(2).length ? process.argv.slice(2) : [path.join(ROOT, 'site/stats.json')];

function render(stats) {
  const els = {};
  const mk = id => (els[id] = { id, textContent: '', hidden: undefined, style: {}, html: [],
    insertAdjacentHTML(_, s) { this.html.push(s); } });
  ['stopped', 'headline', 'gauge', 'fam', 'lab', 'flake', 'spend'].forEach(mk);
  const charts = [];
  global.Chart = class { constructor(el, cfg) { charts.push({ el: el.id, cfg }); } };
  global.document = { getElementById: id => els[id] || mk(id), body: {} };
  global.getComputedStyle = () => ({ getPropertyValue: () => '#000' });
  global.fetch = () => Promise.resolve({ json: () => Promise.resolve(stats) });
  eval(SCRIPT);
  return new Promise(r => setTimeout(() => r({ els, charts }), 50));
}

(async () => {
  let bad = 0;
  for (const f of files) {
    const stats = JSON.parse(fs.readFileSync(f, 'utf8'));
    const state = stats.episodes === 0 ? 'empty' : (stats.stopped ? 'stopped' : 'running');
    console.log(`\n${path.basename(f)}  [${state}]  ${stats.episodes} episodes`);
    const { els, charts } = await render(stats);
    const say = (ok, msg) => { console.log((ok ? '  ok   ' : '  FAIL ') + msg); if (!ok) bad++; };
    const text = els.headline.textContent;

    say(/\d/.test(text) && !/NaN|undefined/.test(text), `headline: ${JSON.stringify(text)}`);
    say(/^\d+(\.\d+)?%$/.test(els.gauge.style.width), `gauge width ${els.gauge.style.width}`);
    say(stats.stopped ? els.stopped.hidden === false : els.stopped.hidden === undefined,
        stats.stopped ? 'stopped banner shown' : 'stopped banner hidden');
    say(els.fam.html.length === stats.by_family.length, `${els.fam.html.length} family rows`);
    say(els.lab.html.length === stats.labels.length, `${els.lab.html.length} label rows`);
    say(!/(NaN|undefined)/.test(els.fam.html.join('') + els.lab.html.join('')), 'no NaN/undefined in tables');
    say(charts.length === 2, 'both charts constructed');

    const flake = charts.find(c => c.el === 'flake');
    const pts = flake.cfg.data.datasets.flatMap(d => d.data).filter(v => v !== null);
    const weeks = new Set(stats.flakiness.map(x => x.week)).size;
    say(flake.cfg.data.labels.length === weeks, `flakiness chart: ${flake.cfg.data.datasets.length} series x ${weeks} weeks`);
    say(pts.every(v => v >= 0 && v <= 100), `${pts.length} flakiness points, all 0-100`);
    say(stats.flakiness.length === 0 || pts.length > 0, 'flakiness data reaches the chart');

    const spend = charts.find(c => c.el === 'spend');
    say(spend.cfg.data.labels.length === stats.nightly.length, `${stats.nightly.length} nightly bars`);
    say(!spend.cfg.data.datasets[0].data.some(v => v == null), 'no missing nightly spend values');
  }
  console.log(bad ? `\n${bad} problems` : '\ndashboard renders clean in every state');
  process.exit(bad ? 1 : 0);
})();
