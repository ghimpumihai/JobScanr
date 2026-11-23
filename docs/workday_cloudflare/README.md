# Workday Cloudflare challenges: the issue and the fix

Written 2026-11-22, updated 2026-11-23. **Status: the first CI run that probed every pod with the fix had no
challenges, and scanned all 1,634 Workday boards.** That is one run on one runner IP, so the fix is promising, not
proven.

Earlier history (digest timeouts, the first measurements, the back-off design) is in
[workday_cloudflare_incident.md](../workday_cloudflare_incident.md).

## Terms

- **Pod:** the shared Workday server group in a board's hostname (`tenant.wd1.myworkdayjobs.com` is on wd1). Challenges
  and back-off are tracked per pod.
- **Challenge:** Cloudflare's bot check. Workday returns HTTP 429 with the header `cf-mitigated: challenge` and an HTML
  page. It looks like a rate limit but is not one, and retrying does not pass it.
- **TLS handshake:** the first message of an HTTPS connection lists the encryption options (cipher suites and others) a
  client supports. Different HTTP clients send different lists, so the list can be used to recognise a client.

## The issue

Since about 16 November 2026, Workday's Cloudflare has challenged many automated clients. Unrelated projects reported
failures starting that day ([504 of 547 employers](https://github.com/jeaninek74/remote-pm-radar/pull/47),
[16 of 16 tenants](https://github.com/career-ops-hq/career-ops/issues/7182)), so our traffic is probably not what
started it. No Workday or Cloudflare announcement was found.

Impact in our CI, run of 2026-11-22 16:39 UTC (before the fix):

- 96 list requests sent
- nine pods challenged us, including wd1, wd3 and wd5
- 1,609 of 1,634 Workday boards were not scraped

## The likely cause

| Explanation | Evidence | Verdict |
|---|---|---|
| TLS handshake | On one machine in the same minute, Node `fetch` got 429 while `node:https` and curl got 200. [One handshake change flipped the result](https://github.com/career-ops-hq/career-ops/issues/7182). | Well supported, exact trait unknown |
| Python's short cipher list | Through one proxy, [stock httpx got 6/15 and OpenSSL `DEFAULT` ciphers 15/15](https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/374). Our local test contradicts it as the only cause. | Possible factor |
| IP reputation | [The same code passed 10/10 on another runner](https://github.com/Riley-Dorrington/job-board-aggregator/pull/77). wd3 challenged our CI but answered a local machine. | Possible factor |
| Request rate | [Refusals continued after 20 s and 40 s waits](https://github.com/JonathanPhungESCP/marketnotes2027/pull/69). Our local test was challenged on the first request to a pod. | Not the main cause |
| User-Agent | No difference in [two](https://github.com/mitz131/jobseeker/issues/35) [reports](https://github.com/career-ops-hq/career-ops/issues/7182). | Not the cause |

Most of this is one-off reports less than a week old. The cause is not established.

## The fix

[PR #120](https://github.com/ghimpumihai/JobScanr/pull/120), squash-merged as `c4b9886`:

- `make_http_client()` in [scrapers/base.py](../../scrapers/base.py) offers OpenSSL's standard `DEFAULT` cipher list to
  `*.myworkdayjobs.com`. Python's own default, which CI uses, is shorter (17 suites).
- [workday.yml](../../.github/workflows/workday.yml) prints the OpenSSL version and Python's default cipher count.
- [tests/test_scrapers_base.py](../../tests/test_scrapers_base.py) checks that only Workday gets the new list and that
  certificate checks stay on.

```python
tls = httpx.create_ssl_context()
tls.set_ciphers("DEFAULT")
# ...
mounts = {"all://*.myworkdayjobs.com": httpx.AsyncHTTPTransport(verify=tls, limits=limits)}
```

Unchanged: the `JobScanr/0.1` User-Agent, certificate and hostname checks, 1 s pacing per pod, the 1-day back-off after
a challenge, and TLS settings for every other platform.

## Test results so far

| Test | Result | What it means |
|---|---|---|
| Offline handshake, short list forced | Other hosts see 18 suites, Workday 31 | The change reaches the wire |
| Unit tests, ruff, mypy, seed check | All pass (442 tests) | No regression found |
| Local probe, 8 requests, 22 Nov 19:28 UTC | wd1 and wd5 challenged on the first request with `DEFAULT`; wd3 answered 3/3 with each list | `DEFAULT` alone does not pass on that connection |
| CI run, 22 Nov 19:40 UTC (with the fix) | 11 list requests, no challenges, 1,608 of 1,634 boards not scraped | **Inconclusive:** eight pods, including wd1, wd3 and wd5, were in back-off |
| Three scheduled CI runs, 22 Nov 21:37 to 23 Nov 14:12 UTC | 23 list requests in all, no challenges | Same as above: the eight pods were still in back-off |
| [CI run, 23 Nov 18:19 UTC](https://github.com/ghimpumihai/JobScanr/actions/runs/45237145128) (first probe of every pod) | **No challenges.** 7,445 list and 280 detail requests, 0 boards skipped, 85,633 postings, 28 matches (9 new), 6 failures | **First real pass.** The eight backed-off pods all answered |

Before and after, in CI:

| | 22 Nov 16:39 (before) | 23 Nov 18:19 (with the fix) |
|---|---|---|
| Pods that challenged us | 9 | 0 |
| Boards not scraped | 1,609 of 1,634 | 0 |
| List requests sent | 96 | 7,445 |

- CI's Python offers 17 cipher suites by default (OpenSSL 3.5.5), so the fix changes the handshake there.
- The 6 failures were not challenges. They are boards that failed for other reasons and are listed for manual review in
  [issue #127](https://github.com/ghimpumihai/JobScanr/issues/127).
- **Not ruled out:** Cloudflare may have relaxed its rule at about the same time. Whether other projects recovered on
  23 Nov was not checked.
- The local machine's Python already offered the `DEFAULT` suites, so it could not give a before/after comparison.
- CI has OpenSSL 3.5.5 and the local machine 3.0.13, so their handshakes may differ beyond the cipher list.
- The local probe went to wd1, wd3 and wd5 while CI's recorded back-off for them was active. It stopped at each pod's
  first challenge but did not check that record. Check it before any future probe.

## What to watch next

Results have varied by runner IP, so check the scheduled `workday` runs for several days. In each log, find:

1. `hosts that challenged this run: ...`, or `Workday pod ... challenged us`
2. `N of 1634 companies were not scraped` (the line is absent when nothing was skipped)
3. `Workday list requests sent: N`. Runs with a fresh cache should send far fewer than the 7,445 of the first full scan.

If wd1 and wd5 are challenged again in most runs, the fix is not enough. Revert it and try the options below:

```bash
git revert c4b9886
```

Do not clear the back-off to test sooner: the constitution requires a day without requests after a challenge.

## Risks and limits

- **It can stop working at any time.** Cloudflare can change its rules.
- **Request volume.** A full scan sends thousands of requests in under an hour, even at 1 request per second per pod.
  Volume may count towards a challenge too.
- **Slightly wider TLS options.** `DEFAULT` also allows some older TLS 1.2 ciphers for Workday, if the server picks one.
- **The link-repair step is not covered.** `scripts/scan_and_fix_links.py` uses its own HTTP client, so its Workday
  checks may still be challenged.
- **Policy conflict, undecided.** The change is meant to avoid triggering the challenge, while section 6 of the incident
  document says "No evasion". One of the two should be updated.
- **Not used:** browser impersonation, stealth browsers, challenge solvers and proxies. Section 6 excludes them.

## If the fix stops working

None of these is built. The first two keep querying Workday directly:

1. [Web Bot Auth](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/), Cloudflare's
   sanctioned way for a bot to identify itself. It needs a hosted key directory, and the site owner still decides.
2. Asking Workday or specific employers for access.
3. An official job API such as Adzuna, whose [terms](https://developer.adzuna.com/docs/terms_of_service) allow personal
   job search. Its Workday coverage is unknown.
