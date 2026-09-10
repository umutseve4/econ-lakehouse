#!/usr/bin/env bash
# Mutation check for tests/test_alert_dedup.js.
#
# A passing suite proves the file executed. It does not prove the assertions
# are load-bearing: a suite that asserts nothing is also green. So mutate the
# behaviour the suite claims to protect and require the suite to notice.
#
# Three exits are asserted, not one:
#   baseline  0        the suite passes on the real module
#   mutated   non-zero the suite fails once the behaviour is removed
#   restored  0        the mutation was undone cleanly
#
# GitHub starts `shell: bash` steps with -e already inherited, and a later
# `set -uo pipefail` does not clear it. This harness must record non-zero
# exits rather than die on them, so -e is turned off explicitly.
set +e

MODULE=".github/scripts/alert_dedup.js"
SUITE="tests/test_alert_dedup.js"
BACKUP="$(mktemp)"

cp "$MODULE" "$BACKUP"

node "$SUITE" > /dev/null 2>&1
baseline=$?

# The marker branch is what makes a retitled incident keep receiving comments
# instead of spawning a weekly duplicate. Mislabel its match and the suite
# must go red.
hits=$(grep -c "matchedBy: 'marker' }" "$MODULE")
sed -i "s/matchedBy: 'marker' }/matchedBy: 'title' }/" "$MODULE"

node "$SUITE" > /dev/null 2>&1
mutated=$?

cp "$BACKUP" "$MODULE"
rm -f "$BACKUP"

node "$SUITE" > /dev/null 2>&1
restored=$?

echo "===== OTOMATIK KONTROL ====="
echo "mutation_sites_found: $hits"
echo "baseline_exit: $baseline"
echo "mutated_exit:  $mutated"
echo "restored_exit: $restored"

# hits must be exactly 1. Zero means the anchor drifted and nothing was
# mutated, which would make this check silently vacuous; more than one means
# the mutation is broader than described.
if [ "$hits" -eq 1 ] && [ "$baseline" -eq 0 ] && [ "$mutated" -ne 0 ] && [ "$restored" -eq 0 ]; then
  echo "RESULT: PASS"
  exit 0
fi

echo "RESULT: FAIL"
exit 1
