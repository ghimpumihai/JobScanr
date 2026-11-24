// Browserbase sessions for the remote-browser apply spike (#129). Plain provider browser: no stealth, no proxies,
// no captcha solving (constitution 1.5).
import Browserbase from '@browserbasehq/sdk';

export interface RemoteProvider {
  readonly name: string;
  create(): Promise<{ id: string; connectUrl: string }>;
  /** WebSocket URL to reconnect to a running session, or null when it has ended. */
  connectUrl(id: string): Promise<string | null>;
  /** Short-lived URL of the interactive live view; never stored or logged. */
  liveViewUrl(id: string): Promise<string>;
  release(id: string): Promise<void>;
  listRunning(): Promise<string[]>;
}

export const SESSION_SECONDS = 15 * 60;

export function browserbase(): RemoteProvider {
  const apiKey = process.env.BROWSERBASE_API_KEY;
  const projectId = process.env.BROWSERBASE_PROJECT_ID;
  if (!apiKey || !projectId) throw new Error('BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID must be set');
  const bb = new Browserbase({ apiKey });
  // Recording and logging off needs a plan that allows it (Task 0.3); set REMOTE_APPLY_ALLOW_RECORDING=true otherwise,
  // and tell pilot users their session is recorded.
  const recordingOff = process.env.REMOTE_APPLY_ALLOW_RECORDING !== 'true';
  return {
    name: 'browserbase',
    async create() {
      const s = await bb.sessions.create({
        projectId,
        keepAlive: true, // survives the disconnect between server actions
        api_timeout: SESSION_SECONDS,
        ...(recordingOff ? { browserSettings: { recordSession: false, logSession: false } } : {})
      });
      return { id: s.id, connectUrl: s.connectUrl };
    },
    async connectUrl(id) {
      const s = await bb.sessions.retrieve(id);
      return s.status === 'RUNNING' && s.connectUrl ? s.connectUrl : null;
    },
    async liveViewUrl(id) {
      return (await bb.sessions.debug(id, { expiresIn: SESSION_SECONDS })).debuggerFullscreenUrl;
    },
    async release(id) {
      await bb.sessions.update(id, { status: 'REQUEST_RELEASE', projectId });
    },
    async listRunning() {
      const sessions = await bb.sessions.list({ status: 'RUNNING' });
      return sessions.map((s) => s.id);
    }
  };
}
