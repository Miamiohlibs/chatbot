# Accessibility audit

A real axe-core run against the served widget, in a real browser, in both
states -- as first loaded, and with the chat open. The second state is the
one that matters most and the easiest to miss: the disclaimer, the
transcript region and the message input do not exist in the DOM until the
launcher is clicked.

## Why it is here rather than a checklist

Contrast pairs were computed by hand during the WCAG work. That is worth
doing and it is not the same as running the page. A rendered audit also
covers the structural criteria -- roles, accessible names, labels,
landmarks, heading order, `lang`, duplicate ids, ARIA validity -- which are
most of WCAG 2.1 and which hand-checking tends to skip.

## Running it

Puppeteer's bundled Chrome is x86_64 only and this box is arm64
(t4g/Graviton), so the browser comes from snap:

```bash
sudo snap install chromium
mkdir -p /tmp/a11y && cd /tmp/a11y
npm init -y && npm install puppeteer axe-core
node /opt/chatbot/ai-core/scripts/a11y/axe_audit.js \
     https://chatbot.lib.miamioh.edu/smartchatbot/
```

Load it by the real hostname. Hitting 127.0.0.1 directly leaves the socket
unconnected, and the widget then renders its UNAVAILABLE state -- which is a
property of the test, not of the product. On this box add
`--host-resolver-rules=MAP chatbot.lib.miamioh.edu 127.0.0.1` (already in
the script) so the name resolves locally.

Exit code is non-zero when there are violations.

## What it does NOT cover

A screen reader. Nothing automated substitutes for running the widget with
one, and no such test has been done. axe finds roughly a third to a half of
what a manual audit finds -- treat a clean run as the floor, not the ceiling.
