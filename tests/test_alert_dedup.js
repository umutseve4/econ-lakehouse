'use strict';

// Offline proof for issue #47.
//
// The dedup decision used to live inline inside two github-script steps,
// where the only way to run it was to let a real scheduled job fail. Both
// copies were wrong in opposite directions and neither was caught. This
// suite runs the extracted decision directly, so the acceptance criteria
// are executed on every push instead of hoped for.
//
// No dependencies, no network. Run with: node tests/test_alert_dedup.js

const assert = require('node:assert/strict');
const path = require('node:path');

const { decideAlertAction } = require(
  path.join(__dirname, '..', '.github', 'scripts', 'alert_dedup.js')
);

const MARKER = '<!-- test-stream:EXAMPLE.SERIES -->';
const TITLE = 'Example alert stream failed';

let checks = 0;
const failures = [];

function check(name, fn) {
  checks += 1;
  try {
    fn();
    console.log(`[PASS] ${name}`);
  } catch (err) {
    failures.push(name);
    console.log(`[FAIL] ${name} - ${err && err.message ? err.message : err}`);
  }
}

// --- Acceptance criterion 1 -------------------------------------------------
// A first failure, with nothing open, creates exactly one issue.

check('criterion 1: no open issues means create', () => {
  const d = decideAlertAction({ openIssues: [], marker: MARKER, title: TITLE });
  assert.equal(d.action, 'create');
  assert.equal(d.issueNumber, null);
});

check('criterion 1: unrelated open issues do not absorb the alert', () => {
  const d = decideAlertAction({
    openIssues: [
      { number: 11, title: 'Something else entirely', body: 'no marker here' },
      { number: 12, title: 'Another unrelated issue', body: '' },
    ],
    marker: MARKER,
    title: TITLE,
  });
  assert.equal(d.action, 'create');
});

// --- Acceptance criterion 2 -------------------------------------------------
// A second failure, with the issue still open, creates zero issues and
// comments on the existing one. This is the path that never ran in
// production for freshness-gate, and never existed at all for pipeline.

check('criterion 2: an open issue carrying the marker gets a comment', () => {
  const d = decideAlertAction({
    openIssues: [{ number: 42, title: TITLE, body: `${MARKER}\nfirst failure` }],
    marker: MARKER,
    title: TITLE,
  });
  assert.equal(d.action, 'comment');
  assert.equal(d.issueNumber, 42);
  assert.equal(d.matchedBy, 'marker');
});

check('criterion 2: a retitled issue still gets the comment', () => {
  // The whole reason the marker exists: an incident record gets renamed by a
  // human, and title matching would then open a duplicate every week.
  const d = decideAlertAction({
    openIssues: [
      { number: 43, title: 'Accepted incident: upstream lag, review 2026-10-05', body: `${MARKER}\n...` },
    ],
    marker: MARKER,
    title: TITLE,
  });
  assert.equal(d.action, 'comment');
  assert.equal(d.issueNumber, 43);
  assert.equal(d.matchedBy, 'marker');
});

check('criterion 2: legacy issue without a marker still matches on title', () => {
  const d = decideAlertAction({
    openIssues: [{ number: 7, title: TITLE, body: 'opened before the marker existed' }],
    marker: MARKER,
    title: TITLE,
  });
  assert.equal(d.action, 'comment');
  assert.equal(d.issueNumber, 7);
  assert.equal(d.matchedBy, 'title');
});

// --- Acceptance criterion 3 -------------------------------------------------
// Once the issue is closed it leaves the open list, so the next failure
// opens a fresh incident rather than commenting into a closed record.

check('criterion 3: a closed issue is absent, so the next failure creates', () => {
  const openAfterClosing = [];
  const d = decideAlertAction({ openIssues: openAfterClosing, marker: MARKER, title: TITLE });
  assert.equal(d.action, 'create');
});

// --- Regressions that produced the original bug -----------------------------

check('an empty marker throws instead of matching every issue', () => {
  // Without this guard `(body || '').includes('')` is true for the first open
  // issue, so every alert would be swallowed by whatever happened to be open.
  assert.throws(
    () => decideAlertAction({ openIssues: [{ number: 1, title: 'x', body: 'y' }], marker: '' }),
    /non-empty marker/
  );
  assert.throws(() => decideAlertAction({ openIssues: [], marker: undefined }), /non-empty marker/);
});

check('a marker match wins over an earlier title match', () => {
  // Order matters: a stale title-only issue listed first must not capture
  // comments that belong on the marker-bearing record.
  const d = decideAlertAction({
    openIssues: [
      { number: 100, title: TITLE, body: 'stale, no marker' },
      { number: 200, title: 'renamed', body: `${MARKER}` },
    ],
    marker: MARKER,
    title: TITLE,
  });
  assert.equal(d.issueNumber, 200);
  assert.equal(d.matchedBy, 'marker');
});

check('a stream with no title fallback never matches on title', () => {
  const d = decideAlertAction({
    openIssues: [{ number: 5, title: TITLE, body: 'no marker' }],
    marker: MARKER,
  });
  assert.equal(d.action, 'create');
});

check('a null body does not throw', () => {
  const d = decideAlertAction({
    openIssues: [{ number: 9, title: 'x', body: null }],
    marker: MARKER,
    title: TITLE,
  });
  assert.equal(d.action, 'create');
});

// --- Harness self-check -----------------------------------------------------
// A suite that silently stops running is indistinguishable from a green one,
// so assert the expected number of checks actually executed.

const EXPECTED_CHECKS = 10;

console.log('===== OTOMATIK KONTROL =====');
console.log(`checks executed: ${checks}`);
console.log(`failures: ${failures.length}`);

if (checks !== EXPECTED_CHECKS) {
  console.log(`RESULT: FAIL (expected ${EXPECTED_CHECKS} checks, ran ${checks})`);
  process.exit(1);
}

if (failures.length > 0) {
  for (const name of failures) {
    console.log(`::error title=alert dedup::${name}`);
  }
  console.log('RESULT: FAIL');
  process.exit(1);
}

console.log('RESULT: PASS');
