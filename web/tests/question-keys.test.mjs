// normalizeQuestion must give the same keys as normalize_question in Python (answer memory): one shared fixture.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
after(() => vite.close());
const { normalizeQuestion } = await vite.ssrLoadModule('/src/lib/server/remoteApply/fill.ts');
const { cases } = JSON.parse(readFileSync(new URL('../../tests/fixtures/question_keys.json', import.meta.url), 'utf8'));

test('question keys match the shared fixture', () => {
  for (const [text, key] of cases) assert.equal(normalizeQuestion(text), key, JSON.stringify(text));
});
