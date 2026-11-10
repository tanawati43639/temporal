#!/bin/bash
# End-to-end RBAC verification for the mTLS + claim mapper + authorizer stack.
#
# Runs the `temporal` CLI inside the temporal-admin-tools container (PKI is
# mounted at /pki there), so no temporal binary is needed on the host.
#
# Usage: ./scripts/verify-authz.sh [JWT]
#   JWT  Entra ID token for a user holding the `uat:reader` app role.
#        Without it only the certificate checks run; token checks are skipped.
#
# Exit status: 0 only when every executed check passed, 1 otherwise.
#
# Deliberately no `set -e`: an expected failure must not end the script.
set -u

usage() { echo "usage: $0 [JWT]" >&2; }

if [ "$#" -gt 1 ]; then usage; exit 2; fi
TOKEN=${1:-}

CONTAINER=temporal-admin-tools
ADDRESS=temporal-frontend:7233
SERVER_NAME=temporal-frontend
PKI=/pki

PASSED=0; FAILED=0; INCONCLUSIVE=0; SKIPPED=0
# Positive controls: set to 1 when the matching positive check passed.
CHECK1_OK=0; CHECK3_OK=0

# The one place the connection flag list lives.
#   run_temporal <cert-basename> [--token] <temporal args...>
# Sets OUT (combined stdout/stderr, token scrubbed) and RC.
run_temporal() {
  local cred=$1; shift
  local meta=()
  if [ "${1:-}" = "--token" ]; then
    shift
    meta=(--grpc-meta "authorization=Bearer $TOKEN")
  fi
  OUT=$(docker exec "$CONTAINER" temporal "$@" \
    --address "$ADDRESS" --tls \
    --tls-cert-path "$PKI/$cred.pem" --tls-key-path "$PKI/$cred-key.pem" \
    --tls-ca-path "$PKI/ca.pem" --tls-server-name "$SERVER_NAME" \
    "${meta[@]+"${meta[@]}"}" 2>&1)
  RC=$?
  # Never let the token reach the terminal, even if something echoes it.
  if [ -n "$TOKEN" ]; then OUT=${OUT//"$TOKEN"/<redacted>}; fi
}

pass() { echo "PASS  check $1: $2"; PASSED=$((PASSED + 1)); }
fail() {
  echo "FAIL  check $1: $2"
  echo "      $3"
  printf '%s\n' "$OUT" | sed 's/^/      | /'
  FAILED=$((FAILED + 1))
}
# A denial proves nothing when its positive control failed: the server returns
# the same 'Request unauthorized.' for a dead token or a deny-everything stack
# as for a genuine role denial. Counted separately, and makes the run exit 1.
inconclusive() { # num desc reason
  echo "INCONCLUSIVE  check $1: $2"
  echo "      $3"
  printf '%s\n' "$OUT" | sed 's/^/      | /'
  INCONCLUSIVE=$((INCONCLUSIVE + 1))
}
skip() { echo "SKIP  check $1: $2 ($3)"; SKIPPED=$((SKIPPED + 1)); }

# Must succeed (exit 0).
expect_success() { # num desc
  if [ "$RC" -eq 0 ]; then pass "$1" "$2"; LAST_OK=1
  else fail "$1" "$2" "expected success, got exit code $RC"; LAST_OK=0; fi
}

# Must fail AND the failure must be an authorization denial. Any other failure
# (container down, bad cert path, connection refused, TLS error) is a FAIL,
# otherwise a broken stack would look like a passing security test.
#
# Gated on a positive control (arg 3: 1 = control passed, 0 = it did not).
expect_denied() { # num desc control-ok control-name
  if [ "$3" -ne 1 ]; then
    inconclusive "$1" "$2" "positive control (check $4) did not pass, so this denial proves nothing about authorization scoping"
  elif [ "$RC" -eq 0 ]; then
    fail "$1" "$2" "expected a permission denial, but the command succeeded"
  elif printf '%s' "$OUT" | grep -q 'Request unauthorized'; then
    pass "$1" "$2"
  else
    fail "$1" "$2" "command failed (exit $RC) but not with 'Request unauthorized.'; this is not a permission denial"
  fi
}

if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" != "true" ]; then
  echo "ERROR: container '$CONTAINER' is not running; start the stack first." >&2
  exit 2
fi

echo "== Certificate checks (no token) =="
run_temporal admin operator namespace list
expect_success 1 "admin.pem can 'operator namespace list'"
CHECK1_OK=$LAST_OK

run_temporal client operator namespace list
expect_denied 2 "client.pem without a token is denied 'operator namespace list'" "$CHECK1_OK" 1

echo "== Token checks (client.pem + bearer token) =="
if [ -z "$TOKEN" ]; then
  skip 3 "token can 'workflow list -n uat'" "no JWT given"
  skip 4 "token is denied 'workflow list -n dev'" "no JWT given"
  skip 5 "token can 'operator cluster describe' (assumed GetClusterInfo)" "no JWT given"
  echo "NOTICE: token checks skipped; pass a JWT as \$1 to run them."
else
  run_temporal client --token workflow list -n uat
  expect_success 3 "uat:reader token can 'workflow list -n uat'"
  CHECK3_OK=$LAST_OK

  run_temporal client --token workflow list -n dev
  expect_denied 4 "uat:reader token is denied 'workflow list -n dev'" "$CHECK3_OK" 3

  # Regression: a namespace-scoped user must be allowed the read-only
  # cluster-scoped API class, or the UI's /api/v1/cluster-info returns 403.
  # TODO(unverified): that `temporal operator cluster describe` calls
  # GetClusterInfo is NOT confirmed (recalled from the CLI source, matched by
  # its help text only). To confirm: run it with an admin cert while watching
  # the frontend/authorizer for the API name, or read the CLI source
  # (temporalio/cli, operator cluster describe). If it calls something else,
  # swap the command; until then this check may not guard the regression.
  run_temporal client --token operator cluster describe
  expect_success 5 "uat:reader token can 'operator cluster describe' (assumed to exercise GetClusterInfo; unverified)"
fi

echo "== Summary: $PASSED passed, $FAILED failed, $INCONCLUSIVE inconclusive, $SKIPPED skipped =="
# Inconclusive means something was not proven, so it fails the run too.
[ "$FAILED" -eq 0 ] && [ "$INCONCLUSIVE" -eq 0 ]
