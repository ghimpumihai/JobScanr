# Bug Assessment: Remote fill misses required fields and misclassifies long select questions

**Bug Slug**: `remote-fill-plan-gaps`
**Status**: Fixed and verified in Browserbase (all three parts)
**Issue Reference**: #137

## 1. Symptom & Reported Behavior
First production remote fill (Databricks, Greenhouse embed form, Browserbase, 2026-11-26): `fields_planned=3,
fields_filled=2, fields_unfilled=1`. Three defects:
1. The planned `single_select` "Are you legally authorized to work…" → "Yes" stayed at "Select…".
2. Required built-in fields (Country, Phone, Education: School, Degree, End date month/year) were neither filled nor
   listed under "Left for you".
3. Long-labelled selects and checkbox groups (sponsorship, two sanctions questions) were sent to `for_user` as
   `open_ended`, skipping `map_screening_question` and answer memory.

Minor: the email input showed a red error outline after the fill.

## 2. Minimal Reproduction
- Part 3: `build_plan([ScreeningQuestion(label=<120-char sponsorship text>, question_type=SINGLE_SELECT, …)], user, url)`
  puts it in `for_user` with `reason="open_ended"`, even when `screening_defaults.requires_sponsorship` is set.
- Part 2: fill the saved Databricks form `web/tests/fixtures/apply/greenhouse-6.html` with any plan. Country, School,
  Degree and End date are required (`aria-required="true"`) but appear in neither `fields` nor `for_user`: the
  Greenhouse question API (`GreenhouseSubmitter.parse_questions`) returns only `questions`, not the built-in
  location and education sections.
- Part 1, reproduced live on 2026-11-26 (local headless Chromium, the spike's fake persona, submit blocked, Databricks
  embed form for posting 8805655002):
  - Normal page load: both dropdowns filled ("Yes" and "No"). A fake CV with real text and 250 ms per step (`slowMo`)
    gave the same result.
  - The page's `.js` held back 12 s, like a cold remote browser: both dropdowns stayed at "Select…", the CV was
    reported attached, and the text fields filled. That is the production pattern.

## 3. Root Cause Analysis
- Part 3: `jobs/apply/fill_plan.py` `build_plan` used `LONG_TEXT or len(label) > 100`, so the label length outranked
  the question type. Only caller: `build_fill_plans`. `map_screening_question` has its own length check, but that only
  returns "not confident", so letting selects reach it is safe.
- Part 2: the plan comes from the question API only. Nothing at fill time looked at the live form for required
  fields, so anything outside `questions` was invisible to both the plan and the drawer.
- Found while fixing part 3: `fill.ts` `setValue` treated every checkbox as a boolean. A planned multi-select answer
  (an option id) matched the group's first box by name and called `setChecked(false)`. That unticked the box and
  counted the field as filled. Part 3 sends more checkbox groups through mapping, so this had to be fixed too.
- Part 1: `fillPage` started as soon as an input existed (`session.ts` waits only for `domcontentloaded` and the first
  input). Greenhouse's embed form is rendered on the server, so its inputs exist before its scripts load and React
  takes over. Until then a react-select dropdown cannot open, and typed text and an attached CV reach only the DOM,
  not the form's own state. In a slow remote browser the CV wait (up to 5 s of `networkidle`) ended before the scripts
  ran. The red email outline is probably the same: a value typed before React took over that React then treats as
  empty. Not confirmed: with the fix the outline never appeared. In Browserbase the field typed last (LinkedIn) showed
  a red underline with `aria-invalid="false"`. That is Greenhouse's focus style, so the production "red outline" on
  Email, the last field typed there, was most likely focus, not a validation error.
- Part 1, second cause (Browserbase, 2026-11-26): with the settle wait, the first Browserbase run filled the
  authorization dropdown but not the sponsorship one; a second run filled both. A traced run showed one dropdown click
  taking ~2.5 s in Browserbase, because every actionability step of a Playwright click is a round trip to the remote
  browser. Clicks and typing used `STEP_MS` (2 s), so they timed out at random.

## 4. Minimal Proposed Fix
- Part 3: open-ended means `LONG_TEXT`, or `SHORT_TEXT` over 100 characters. Selects, checkboxes and booleans go
  through confident mapping and answer memory whatever their label length.
- Part 2: `fill.ts` `requiredEmpty` runs once after the fill over the live DOM and returns labels of required, visible,
  still-empty controls:
  - react-select counts as empty while `aria-describedby` points at its placeholder;
  - a checkbox or radio group counts once, under its legend (Lever: its `.application-label`);
  - react-select's `aria-hidden` stand-in input is ignored.
  `session.ts` appends these to `leftForUser`, deduplicated by `normalizeQuestion`.
- Checkbox: a non-boolean planned value ticks only the box whose `value` matches; with no match the field is reported
  unfilled and no box is changed.
- Part 1: `fillPage` first waits for `networkidle`, capped at 15 s (`SETTLE_MS`), so that every caller (sessions and
  the spike runner) fills only after the page's scripts have loaded. A page that never goes quiet is filled after
  15 s anyway.
- Part 1, second cause: clicks, typing and checkbox ticks get `ACTION_MS` (10 s); waits for an option that may not
  exist keep `STEP_MS` (2 s), so a dropdown with no matching option still gives up quickly.

## 5. Verification Verdict
- **Result**: Verified (locally and in Browserbase, against the live Databricks form; nothing submitted)
- **Regression Tests**:
  - `tests/test_fill_plan.py::test_build_plan_classifies_long_labels_by_question_type`
  - `web/tests/fill-fixtures.test.mjs`: "saved Databricks form: required fields outside the question API are listed
    for the user, each once (#137)"; "required-field check: chosen dropdowns, ticked groups and hidden inputs are not
    listed; empty ones are (#137)"; "a planned multi-select answer ticks its own box of the group and never unticks
    another (#137)"
  - `web/tests/remote-apply-actions.test.mjs`: "start: required fields the plan never saw are left for the user,
    each once (#137)"
  - `web/tests/fill-fixtures.test.mjs`: "a server-rendered form is filled only once its scripts have loaded (#137)"
    (fails without the wait); "a dropdown that takes more than 2 s to click is still filled (#137, Browserbase)"
    (fails with the old 2 s timeout)
- Live re-run with the fix and scripts held back 12 s: 8 of 8 planned fields filled, both dropdowns set, the CV shown
  in Greenhouse's own upload widget, fill 21 s. Without the delay: 8 of 8, fill 2.7 s. Nothing submitted.
- Gates: ruff check and format, mypy, pytest (594 passed), web `npm test` (122 passed), svelte-check (0 errors).
- Browserbase, fake persona, no submit, after both fixes: two runs, 8 of 8 each (fill 22 s and 20 s), authorization
  "Yes" and sponsorship "No" visible in the screenshot, CV shown in Greenhouse's upload widget, no captcha.
- Not checked: a production session with a real user's profile and CV.
