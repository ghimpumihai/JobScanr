// The panel's start: a session that finishes starting after the drawer closed is ended, not left running (#129).
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
after(() => vite.close());
const { startUnlessClosed } = await vite.ssrLoadModule('/src/lib/remoteFillStart.ts');

const started = { sessionId: 900, liveViewUrl: 'https://live.example/x' };

test('panel still open: the session is returned and not ended', async () => {
  const ended = [];
  const r = await startUnlessClosed(async () => started, async (id) => ended.push(id), () => true);
  assert.equal(r, started);
  assert.deepEqual(ended, []);
});

test('panel closed while starting: the session is ended at once and nothing is returned', async () => {
  let open = true;
  const ended = [];
  const r = await startUnlessClosed(
    async () => {
      open = false; // the user closes the drawer during the fill
      return started;
    },
    async (id) => ended.push(id),
    () => open
  );
  assert.equal(r, null);
  assert.deepEqual(ended, [900]);
});

test('a failed end is swallowed: the provider timeout still ends that session', async () => {
  const r = await startUnlessClosed(async () => started, async () => { throw new Error('offline'); }, () => false);
  assert.equal(r, null);
});
