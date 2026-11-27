// Live job description for the role panel (#141). Descriptions are never stored (constitution 1.3), so the panel
// asks the employer's job board when a role opens. Only fixed public API hosts are called, built from identifiers
// the scraper stored; the HTML is reduced to plain text blocks, so nothing from the employer's page is rendered.

export type Block = { h: string } | { p: string } | { li: string[] };
export interface Description {
  facts: { k: string; v: string }[];
  blocks: Block[];
}

const TIMEOUT_MS = 8000;
const SEGMENT = /^[A-Za-z0-9._~-]+$/;

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', '#39': "'" };
function decode(text: string): string {
  return text.replace(/&(#x[0-9a-f]+|#\d+|[a-z0-9]+);/gi, (m, e: string) => {
    if (e[0] === '#') {
      const code = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return code > 0 && code < 0x110000 ? String.fromCodePoint(code) : '';
    }
    return ENTITIES[e.toLowerCase()] ?? m;
  });
}

/** Employer HTML to headings, paragraphs and bullet lists of plain text. */
export function htmlToBlocks(html: string): Block[] {
  const blocks: Block[] = [];
  let text = '';
  let kind: 'p' | 'h' | 'li' = 'p';
  let skip = 0; // inside <script>/<style>
  const flush = () => {
    const t = decode(text).replace(/\s+/g, ' ').trim();
    text = '';
    if (!t) return;
    const last = blocks.at(-1);
    if (kind === 'li') {
      if (last && 'li' in last) last.li.push(t);
      else blocks.push({ li: [t] });
    } else if (kind === 'h' || (t.length < 80 && /:$/.test(t))) blocks.push({ h: t.replace(/:$/, '') });
    else blocks.push({ p: t });
  };
  for (const m of html.matchAll(/<(\/?)([a-z0-9]+)[^>]*>|([^<]+)/gi)) {
    if (m[3] !== undefined) {
      if (!skip) text += m[3];
      continue;
    }
    const tag = m[2].toLowerCase();
    if (tag === 'script' || tag === 'style') {
      skip += m[1] ? -1 : 1;
      skip = Math.max(0, skip);
      continue;
    }
    if (/^(p|div|br|li|ul|ol|h[1-6]|section|tr|table)$/.test(tag)) {
      flush();
      kind = m[1] ? 'p' : tag === 'li' ? 'li' : /^h[1-6]$/.test(tag) ? 'h' : 'p';
    }
  }
  flush();
  return blocks.slice(0, 200);
}

/** A whole description as HTML, if a board returns it escaped (Greenhouse does). */
const unescapeIfNeeded = (html: string) => (/&lt;[a-z]/i.test(html) && !/<[a-z]/i.test(html) ? decode(html) : html);

const day = (raw: unknown) => {
  const d = new Date(typeof raw === 'number' || typeof raw === 'string' ? raw : NaN);
  return isNaN(d.getTime()) ? null : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
};
const fact = (k: string, v: unknown) => (typeof v === 'string' && v.trim() ? [{ k, v: v.trim() }] : []);
const label = (raw: unknown) => (typeof raw === 'string' ? raw.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase()) : undefined);

type Fetch = typeof fetch;
async function getJson(fetchImpl: Fetch, url: string, init: RequestInit = {}): Promise<any> {
  const res = await fetchImpl(url, { ...init, signal: AbortSignal.timeout(TIMEOUT_MS), redirect: 'error' });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

/**
 * The posting's description from its job board, or null when the platform has no public single-posting endpoint
 * (Teamtailor, Google) or the identifiers look wrong. Network and HTTP failures throw; the caller shows "couldn't load".
 */
export async function fetchDescription(
  platform: string,
  ident: string,
  externalId: string,
  fetchImpl: Fetch = fetch
): Promise<Description | null> {
  const seg = encodeURIComponent;
  if (platform === 'greenhouse' && SEGMENT.test(ident) && /^\d+$/.test(externalId)) {
    const j = await getJson(fetchImpl, `https://boards-api.greenhouse.io/v1/boards/${seg(ident)}/jobs/${externalId}`);
    return { facts: fact('Updated', day(j.updated_at)), blocks: htmlToBlocks(unescapeIfNeeded(String(j.content ?? ''))) };
  }
  if (platform === 'lever' && SEGMENT.test(ident) && SEGMENT.test(externalId)) {
    const j = await getJson(fetchImpl, `https://api.lever.co/v0/postings/${seg(ident)}/${seg(externalId)}`);
    const lists = (Array.isArray(j.lists) ? j.lists : []).flatMap((l: any) => [`<h4>${l.text ?? ''}</h4>`, `<ul>${l.content ?? ''}</ul>`]);
    return {
      facts: [...fact('Type', j.categories?.commitment), ...fact('Workplace', label(j.workplaceType)), ...fact('Posted', day(j.createdAt))],
      blocks: htmlToBlocks([j.description ?? '', ...lists, j.additional ?? ''].join(''))
    };
  }
  if (platform === 'ashby' && SEGMENT.test(ident) && SEGMENT.test(externalId)) {
    // The same public GraphQL query the scraper uses (scrapers/ashby.py DETAIL_QUERY).
    const query = `query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) { descriptionHtml }
}`;
    const j = await getJson(fetchImpl, 'https://jobs.ashbyhq.com/api/non-user-graphql', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ operationName: 'ApiJobPosting', variables: { organizationHostedJobsPageName: ident, jobPostingId: externalId }, query })
    });
    const html = j?.data?.jobPosting?.descriptionHtml;
    if (typeof html !== 'string') throw new Error('no description'); // Ashby answers throttling with a null payload
    return { facts: [], blocks: htmlToBlocks(html) };
  }
  if (platform === 'smartrecruiters' && SEGMENT.test(ident) && SEGMENT.test(externalId)) {
    const j = await getJson(fetchImpl, `https://api.smartrecruiters.com/v1/companies/${seg(ident)}/postings/${seg(externalId)}`);
    const s = j.jobAd?.sections ?? {};
    const parts = [s.jobDescription, s.qualifications, s.additionalInformation].filter((x) => x?.text);
    return {
      facts: [...fact('Type', j.typeOfEmployment?.label), ...fact('Workplace', j.location?.remote ? 'Remote' : undefined), ...fact('Posted', day(j.releasedDate))],
      blocks: htmlToBlocks(parts.map((x: any) => (x.title ? `<h4>${x.title}</h4>` : '') + x.text).join(''))
    };
  }
  if (platform === 'workday') {
    // tenant|wdN|site (constitution 1.4). One request per opened role; a Cloudflare challenge is a plain failure here.
    const [tenant, wd, site] = ident.split('|');
    if (!/^[a-z0-9-]+$/i.test(tenant ?? '') || !/^wd\d{1,3}$/.test(wd ?? '') || !SEGMENT.test(site ?? '') || !SEGMENT.test(externalId)) return null;
    const j = await getJson(fetchImpl, `https://${tenant}.${wd}.myworkdayjobs.com/wday/cxs/${tenant}/${site}/job/${seg(externalId)}`, {
      headers: { accept: 'application/json' }
    });
    const info = j.jobPostingInfo ?? {};
    return { facts: [...fact('Type', info.timeType), ...fact('Posted', info.postedOn)], blocks: htmlToBlocks(String(info.jobDescription ?? '')) };
  }
  return null;
}
