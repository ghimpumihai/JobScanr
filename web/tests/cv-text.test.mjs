// Redraft's CV reader (#142) on real PDF bytes: the other redraft tests swap it out, so this one runs unpdf itself.
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
after(() => vite.close());
const { redraftDeps } = await vite.ssrLoadModule('/src/lib/server/remoteApply/redraft.ts');
const cvText = redraftDeps.cvText; // the real reader, read before any test could swap it

/** A one-page PDF with these lines of text, built by hand so no fixture file is needed. */
function pdf(lines) {
  const stream = 'BT /F1 11 Tf 50 750 Td 14 TL ' + lines.map((l) => `(${l}) Tj T*`).join(' ') + ' ET';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
  ];
  let body = '%PDF-1.4\n';
  const offsets = objects.map((o, i) => {
    const at = body.length;
    body += `${i + 1} 0 obj\n${o}\nendobj\n`;
    return at;
  });
  const xref = body.length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n` + offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('');
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, 'latin1');
}

const CV = [
  'Jane Doe - Backend Engineer',
  'Experience: Acme Payments, 2022 to 2025, built Go and Python services for card billing.',
  'Moved the ledger to PostgreSQL logical replication and cut reconciliation time by half.',
  'Education: BSc Computer Science, University of Manchester, 2022.',
  'Skills: Go, Python, PostgreSQL, Kafka, Kubernetes, observability with Grafana.'
];

test('a text PDF is read into its lines, whitespace collapsed, as the pipeline reads it', async () => {
  const text = await cvText({ name: 'Jane Doe CV.PDF', buffer: pdf(CV) });
  assert.ok(text, 'the PDF was not read');
  for (const line of CV) assert.ok(text.includes(line), `missing: ${line}`);
  assert.doesNotMatch(text, /\s{2,}/);
});

test('too little text, a broken file or a Word CV gives null, so Redraft says it cannot read the CV', async () => {
  assert.equal(await cvText({ name: 'cv.pdf', buffer: pdf(['Jane Doe']) }), null); // under MIN_CV_CHARS
  assert.equal(await cvText({ name: 'cv.pdf', buffer: Buffer.from('not a pdf') }), null);
  assert.equal(await cvText({ name: 'cv.docx', buffer: pdf(CV) }), null); // shortcut in redraft.ts: DOCX not read yet
});
