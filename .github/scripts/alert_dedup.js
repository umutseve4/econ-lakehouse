'use strict';

/**
 * Decide what a failure-alert job should do, given the issues that are
 * already open.
 *
 * This function is deliberately pure: no network, no Octokit, no context.
 * Everything it needs is an argument, so the three acceptance cases in
 * issue #47 can be exercised offline and deterministically instead of by
 * waiting for a real scheduled failure.
 *
 * The caller is responsible for the lookup itself (label filter, pagination)
 * and for performing the returned action. Keeping those on the outside is
 * what makes this part provable.
 *
 * @param {object} args
 * @param {Array<{number: number, title: string, body: ?string}>} args.openIssues
 *        Issues that are currently open AND carry the alert label. Closed
 *        issues must not be included; their absence is what allows a new
 *        incident to be opened after a previous one was resolved.
 * @param {string} args.marker
 *        Stable HTML-comment marker identifying this alert stream.
 * @param {string} [args.title]
 *        Legacy title fallback, for issues opened before the marker existed.
 *        Optional: a new alert stream should pass none.
 * @returns {{action: 'create'|'comment', issueNumber: ?number, matchedBy: ?string}}
 */
function decideAlertAction(args) {
  const opts = args || {};
  const marker = opts.marker;

  // A missing or empty marker would make `''.includes(marker)` true for every
  // issue, so the very first open issue would silently absorb every alert.
  // Fail loudly instead.
  if (typeof marker !== 'string' || marker.length === 0) {
    throw new Error('decideAlertAction: a non-empty marker is required');
  }

  const openIssues = Array.isArray(opts.openIssues) ? opts.openIssues : [];
  const title = typeof opts.title === 'string' && opts.title.length > 0 ? opts.title : null;

  // Marker match is preferred over title match, and is checked across the
  // whole list first. Otherwise an old title-only issue sitting earlier in
  // the list would win over the marker-bearing one, and comments would land
  // on the stale record.
  for (const issue of openIssues) {
    if ((issue.body || '').includes(marker)) {
      return { action: 'comment', issueNumber: issue.number, matchedBy: 'marker' };
    }
  }

  if (title !== null) {
    for (const issue of openIssues) {
      if (issue.title === title) {
        return { action: 'comment', issueNumber: issue.number, matchedBy: 'title' };
      }
    }
  }

  return { action: 'create', issueNumber: null, matchedBy: null };
}

module.exports = { decideAlertAction };
