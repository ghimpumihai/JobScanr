// Remote browser providers for the apply spike (#129): Browserbase and Cloudflare Browser Run, chosen with
// REMOTE_APPLY_PROVIDER. Plain provider browsers: no stealth, no proxies, no captcha solving (constitution 1.5).
import Browserbase from '@browserbasehq/sdk';
import { chromium } from 'playwright-core';

/** How to reach a session over CDP. Headers carry credentials, so a Connection is never logged or stored. */
export interface Connection {
  url: string;
  headers?: Record<string, string>;
}

export interface RemoteProvider {
  readonly name: ProviderName;
  create(): Promise<{ id: string; connection: Connection }>;
  /** How to reconnect to a running session, or null when it has ended. */
  connection(id: string): Promise<Connection | null>;
  /** Short-lived URL of the interactive live view; never stored or logged. */
  liveViewUrl(id: string): Promise<string>;
  release(id: string): Promise<void>;
  listRunning(): Promise<string[]>;
}

export const PROVIDERS = ['browserbase', 'cloudflare'] as const;
export type ProviderName = (typeof PROVIDERS)[number];
// The app ends sessions at 15 minutes (Browserbase's free plan caps them there).
export const SESSION_SECONDS = 15 * 60;
// Providers keep a session 2 minutes longer, so the app's last check at 15 minutes can still read the page.
const PROVIDER_SECONDS = SESSION_SECONDS + 120;

export function getProvider(name: string = process.env.REMOTE_APPLY_PROVIDER || 'browserbase'): RemoteProvider {
  if (name === 'browserbase') return browserbase();
  if (name === 'cloudflare') return cloudflare();
  throw new Error(`Unknown remote apply provider: ${name}`);
}

export function browserbase(): RemoteProvider {
  const apiKey = process.env.BROWSERBASE_API_KEY;
  const projectId = process.env.BROWSERBASE_PROJECT_ID;
  if (!apiKey || !projectId) throw new Error('BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID must be set');
  const bb = new Browserbase({ apiKey });
  // Recording and logging off was accepted on the free plan (Task 0.3); REMOTE_APPLY_ALLOW_RECORDING=true turns it
  // back on if that ever changes, and pilot users must then be told.
  const recordingOff = process.env.REMOTE_APPLY_ALLOW_RECORDING !== 'true';
  return {
    name: 'browserbase',
    async create() {
      const s = await bb.sessions.create({
        projectId,
        keepAlive: true, // survives the disconnect between server actions
        api_timeout: PROVIDER_SECONDS,
        ...(recordingOff ? { browserSettings: { recordSession: false, logSession: false } } : {})
      });
      return { id: s.id, connection: { url: s.connectUrl } };
    },
    async connection(id) {
      const s = await bb.sessions.retrieve(id);
      return s.status === 'RUNNING' && s.connectUrl ? { url: s.connectUrl } : null;
    },
    async liveViewUrl(id) {
      return (await bb.sessions.debug(id, { expiresIn: SESSION_SECONDS })).debuggerFullscreenUrl;
    },
    async release(id) {
      await bb.sessions.update(id, { status: 'REQUEST_RELEASE', projectId });
    },
    async listRunning() {
      return (await bb.sessions.list({ status: 'RUNNING' })).map((s) => s.id);
    }
  };
}

export function cloudflare(): RemoteProvider {
  const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
  const token = process.env.CLOUDFLARE_BROWSER_RUN_TOKEN;
  if (!accountId || !token) throw new Error('CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_BROWSER_RUN_TOKEN must be set');
  const base = `https://api.cloudflare.com/client/v4/accounts/${accountId}/browser-run/devtools`;
  const headers = { Authorization: `Bearer ${token}` };
  const connectionFor = (id: string): Connection => ({ url: `${base.replace('https:', 'wss:')}/browser/${encodeURIComponent(id)}`, headers });

  async function api(path: string, method = 'GET'): Promise<Response> {
    const res = await fetch(`${base}${path}`, { method, headers });
    // The status only: a 429 means the free plan's daily minutes are used up.
    if (!res.ok) throw Object.assign(new Error(`Cloudflare Browser Run returned ${res.status}`), { status: res.status });
    return res;
  }
  async function listRunning(): Promise<string[]> {
    const body = await (await api('/session')).json();
    const sessions: any[] = Array.isArray(body) ? body : (body?.sessions ?? body?.result ?? []);
    return sessions.map((s) => (typeof s === 'string' ? s : (s.sessionId ?? s.id))).filter(Boolean);
  }

  return {
    name: 'cloudflare',
    async create() {
      // keep_alive: the session outlives each server action's connection. Recording is off unless asked for.
      const { sessionId } = await (await api(`/browser?keep_alive=${PROVIDER_SECONDS * 1000}`, 'POST')).json();
      return { id: sessionId, connection: connectionFor(sessionId) };
    },
    async connection(id) {
      return (await listRunning()).includes(id) ? connectionFor(id) : null;
    },
    async liveViewUrl(id) {
      // Cloudflare hands out live views over CDP, so this connects briefly; "tab" mode is the interactive one.
      const browser = await chromium.connectOverCDP(connectionFor(id).url, { headers }).catch((e) => {
        // A refused WebSocket only says 429 in its message; give it the status the quota handling looks for.
        throw /\b429\b/.test(String(e?.message)) ? Object.assign(new Error('Cloudflare Browser Run returned 429'), { status: 429 }) : e;
      });
      try {
        const context = browser.contexts()[0];
        const page = context?.pages().at(-1);
        if (!context || !page) throw new Error('no page in the session');
        const cdp = await context.newCDPSession(page);
        const { devtoolsFrontendUrl } = (await cdp.send('Cloudflare.getLiveView' as any, {
          mode: 'tab',
          expiresInMs: SESSION_SECONDS * 1000
        })) as { devtoolsFrontendUrl: string };
        return devtoolsFrontendUrl;
      } finally {
        await browser.close().catch(() => {});
      }
    },
    async release(id) {
      await api(`/browser/${encodeURIComponent(id)}`, 'DELETE');
    },
    listRunning
  };
}
