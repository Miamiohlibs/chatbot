// Real axe-core run against the served widget, in a real browser.
//
// The operator computed the contrast pairs by hand and asked for this to be
// verified rather than taken on trust. Contrast is only one of the WCAG 2.1
// criteria a rendered page can be checked against; this covers the
// structural ones too -- roles, names, labels, landmarks, heading order,
// focus -- which hand-checking tends to miss.
//
// Two states are audited, because the chat UI does not exist in the DOM
// until the launcher is opened: the disclaimer, the transcript region and
// the input all live behind that click.

const fs = require('fs');
const puppeteer = require('puppeteer');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

const URL_ = process.argv[2] || 'http://127.0.0.1/smartchatbot/';
const TAGS = ['wcag2a', 'wcag2aa', 'wcag2aaa', 'wcag21a', 'wcag21aa'];

function report(label, results) {
  const v = results.violations;
  console.log(`\n=== ${label}`);
  console.log(`    passes ${results.passes.length}  violations ${v.length}` +
              `  incomplete ${results.incomplete.length}`);
  if (!v.length) { console.log('    no violations'); }
  for (const rule of v) {
    console.log(`\n    [${rule.impact}] ${rule.id} -- ${rule.help}`);
    console.log(`      ${rule.helpUrl}`);
    for (const node of rule.nodes.slice(0, 4)) {
      console.log(`      * ${node.target.join(' ')}`);
      const msg = (node.failureSummary || '').split('\n').filter(Boolean)[1];
      if (msg) console.log(`        ${msg.trim()}`);
    }
    if (rule.nodes.length > 4) {
      console.log(`      ... and ${rule.nodes.length - 4} more element(s)`);
    }
  }
  // Things axe could not decide -- worth a human eye, not a failure.
  const inc = results.incomplete.filter(r => r.id.includes('contrast'));
  for (const rule of inc) {
    console.log(`\n    [needs review] ${rule.id} on ${rule.nodes.length} element(s)`);
  }
  return v;
}

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new', executablePath: '/snap/bin/chromium',
    args: ['--no-sandbox', '--disable-dev-shm-usage',
           // Load it the way a student does -- the real hostname, resolved
           // to this box. Hitting 127.0.0.1 directly left the socket
           // unconnected, and the widget then renders its UNAVAILABLE state,
           // which is a property of the test and not of the product.
           '--host-resolver-rules=MAP chatbot.lib.miamioh.edu 127.0.0.1',
           '--ignore-certificate-errors'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(URL_, { waitUntil: 'networkidle2', timeout: 60000 });
  await new Promise(r => setTimeout(r, 8000));   // let the socket connect

  await page.evaluate(axeSource);
  const closed = await page.evaluate(
    (tags) => axe.run(document, { runOnly: { type: 'tag', values: tags } }), TAGS);
  const vClosed = report('widget as first loaded', closed);

  // Open the chat: the disclaimer and the transcript only exist after this.
  let opened = null;
  // Click the launcher by its accessible name -- the generic 'button'
  // selector hit "Close" first and shut the toast instead.
  const buttons = await page.$$('button');
  for (const el of buttons) {
    const label = await page.evaluate(
      b => (b.getAttribute('aria-label') || b.textContent || '').trim(), el);
    if (!/library chatbot|start|chat with/i.test(label)) continue;
    try { await el.click(); } catch (e) { continue; }
    await new Promise(r => setTimeout(r, 2500));
    const hasInput = await page.$('textarea, input');
    if (hasInput) {
      await page.evaluate(axeSource);
      opened = await page.evaluate(
        (tags) => axe.run(document, { runOnly: { type: 'tag', values: tags } }), TAGS);
      break;
    }
  }
  let vOpen = [];
  if (opened) {
    vOpen = report('chat open (disclaimer, transcript, input)', opened);
  } else {
    console.log('\n=== chat open: could not open the widget -- ' +
                'the interactive state was NOT audited');
  }

  const total = vClosed.length + vOpen.length;
  console.log(`\n  TOTAL violations across both states: ${total}`);
  await browser.close();
  process.exit(total ? 1 : 0);
})().catch(e => { console.error('audit failed:', e.message); process.exit(2); });
