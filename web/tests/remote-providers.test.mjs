// Provider selection and Cloudflare Browser Run's HTTP calls (#129), with fetch stubbed. No network.
import assert from 'node:assert/strict';
import { after, beforeEach, test } from 'node:test';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
after(() => vite.close());
const { getProvider, cloudflare, SESSION_SECONDS } = await vite.ssrLoadModule('/src/lib/server/remoteApply/provider.ts');

const BASE = 'https://api.cloudflare.com/client/v4/accounts/acct/browser-run/devtools';
let calls;
let replies;
const realFetch = globalThis.fetch;
after(() => (globalThis.fetch = realFetch));

beforeEach(() => {
  process.env.CLOUDFLARE_ACCOUNT_ID = 'acct';
  process.env.CLOUDFLARE_BROWSER_RUN_TOKEN = 'tok';
  calls = [];
  replies = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init?.method ?? 'GET', auth: init?.headers?.Authorization });
    const [status, body] = replies.shift() ?? [200, {}];
    return new Response(JSON.stringify(body), { status });
  };
});

test('getProvider picks by name or REMOTE_APPLY_PROVIDER, and refuses unknown names', () => {
  process.env.BROWSERBASE_API_KEY = 'k';
  process.env.BROWSERBASE_PROJECT_ID = 'p';
  delete process.env.REMOTE_APPLY_PROVIDER;
  assert.equal(getProvider().name, 'browserbase');
  process.env.REMOTE_APPLY_PROVIDER = 'cloudflare';
  assert.equal(getProvider().name, 'cloudflare');
  assert.equal(getProvider('browserbase').name, 'browserbase'); // a session's own provider wins
  assert.throws(() => getProvider('other'), /Unknown remote apply provider/);
  delete process.env.REMOTE_APPLY_PROVIDER;
});

test('cloudflare refuses to start without its account and token', () => {
  delete process.env.CLOUDFLARE_BROWSER_RUN_TOKEN;
  assert.throws(() => cloudflare(), /CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_BROWSER_RUN_TOKEN/);
});

test('cloudflare create: one POST with keep_alive and the token; reconnect needs the same token', async () => {
  replies.push([200, { sessionId: 's-1', webSocketDebuggerUrl: 'ignored' }]);
  const { id, connection } = await cloudflare().create();
  assert.equal(id, 's-1');
  // Two minutes past the app's own limit, so the last check at 15 minutes can still reach the page.
  assert.deepEqual(calls, [{ url: `${BASE}/browser?keep_alive=${(SESSION_SECONDS + 120) * 1000}`, method: 'POST', auth: 'Bearer tok' }]);
  assert.equal(connection.url, 'wss://api.cloudflare.com/client/v4/accounts/acct/browser-run/devtools/browser/s-1');
  assert.deepEqual(connection.headers, { Authorization: 'Bearer tok' });
});

test('cloudflare connection: only while the session is listed as running', async () => {
  replies.push([200, [{ sessionId: 's-1' }, { sessionId: 's-2' }]], [200, { sessions: [{ id: 's-2' }] }]);
  const cf = cloudflare();
  assert.ok(await cf.connection('s-1'));
  assert.equal(await cf.connection('s-1'), null); // gone from the list: ended
  assert.ok(calls.every((c) => c.url === `${BASE}/session` && c.method === 'GET'));
});

test('cloudflare release is a DELETE; a 429 carries its status and never the token', async () => {
  await cloudflare().release('s/1');
  assert.deepEqual(calls[0], { url: `${BASE}/browser/s%2F1`, method: 'DELETE', auth: 'Bearer tok' });
  replies.push([429, {}]);
  await assert.rejects(cloudflare().create(), (e) => e.status === 429 && !e.message.includes('tok'));
});
