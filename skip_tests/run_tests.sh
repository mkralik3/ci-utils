#!/bin/bash
# Simple test runner for parse-test-config.sh tests
# Can run without bashunit framework installed

# Do not set -e here as we want to continue running tests even if one fails

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0
TEST_CONFIG_FILE=""
SCRIPT_PATH="$(dirname "$0")/parse-test-config.sh"

# Setup function
function setup() {
    TEST_CONFIG_FILE="$(mktemp /tmp/test-config.XXXXXX.yaml)"

    cat > "$TEST_CONFIG_FILE" << 'EOF'
test_suites:
  pilot:
    skip_tests:
      - name: "TestA"
        reason: "Test A for all midstream"
        skip_in: ['midstream_sail', 'midstream_helm']
      - name: "TestB"
        reason: "Test B for downstream only"
        skip_in: ['downstream']
      - name: "TestC"
        reason: "Test C for midstream_sail only"
        skip_in: ['midstream_sail']
      - name: "TestD"
        reason: "Test D for midstream_sail on master only"
        skip_in: ['midstream_sail']
        skip_branches_only: ['master']
      - name: "TestE"
        reason: "Test E for midstream_helm on release-1.24 only"
        skip_in: ['midstream_helm']
        skip_branches_only: ['release-1.24']
      - name: "TestF"
        reason: "Test F for all environments"
        skip_in: ['midstream_sail', 'midstream_helm', 'downstream']
    skip_subsuites:
      - name: "subsuite1"
        reason: "Subsuite 1 for midstream_sail"
        skip_in: ['midstream_sail']
      - name: "subsuite2"
        reason: "Subsuite 2 for midstream_sail on release-1.28 only"
        skip_in: ['midstream_sail']
        skip_branches_only: ['release-1.28']
    run_tests_only:
      - name: "TestOnlyA"
        reason: "Run only this test in downstream"
        skip_in: ['downstream']
  security:
    skip_tests: []
    skip_subsuites: []
    run_tests_only: []
EOF
}

# Cleanup function
function cleanup() {
    rm -f "$TEST_CONFIG_FILE"
}

# Assertion helpers
function assert_contains() {
    local haystack="$1"
    local needle="$2"
    if echo "$haystack" | grep -q "$needle"; then
        return 0
    else
        echo -e "${RED}    ✗ Expected to contain: '$needle'${NC}"
        echo "    Actual output: $haystack"
        return 1
    fi
}

function assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    if ! echo "$haystack" | grep -q "$needle"; then
        return 0
    else
        echo -e "${RED}    ✗ Expected NOT to contain: '$needle'${NC}"
        return 1
    fi
}

# Run a test
function run_test() {
    local test_name="$1"
    if $test_name; then
        echo -e "${GREEN}✓${NC} $test_name"
        ((PASSED++))
    else
        echo -e "${RED}✗${NC} $test_name"
        ((FAILED++))
    fi
}

# Test functions
function test_invalid_stream_parameter() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot invalid_stream 2>&1) || true
    assert_contains "$output" "Error: stream must be"
}

function test_accepts_midstream_sail() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_sail 2>&1)
    assert_contains "$output" "SKIP_PARSER_SUITE='pilot'"
}

function test_accepts_midstream_helm() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_helm 2>&1)
    assert_contains "$output" "SKIP_PARSER_SUITE='pilot'"
}

function test_accepts_downstream() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot downstream 2>&1)
    assert_contains "$output" "SKIP_PARSER_SUITE='pilot'"
}

function test_filter_midstream_sail_no_branch() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_sail 2>&1)
    assert_contains "$output" "TestA" && \
    assert_contains "$output" "TestC" && \
    assert_contains "$output" "TestF" && \
    assert_not_contains "$output" "TestB" && \
    assert_not_contains "$output" "TestD" && \
    assert_not_contains "$output" "TestE"
}

function test_filter_midstream_helm_no_branch() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_helm 2>&1)
    assert_contains "$output" "TestA" && \
    assert_contains "$output" "TestF" && \
    assert_not_contains "$output" "TestB" && \
    assert_not_contains "$output" "TestC" && \
    assert_not_contains "$output" "TestD" && \
    assert_not_contains "$output" "TestE"
}

function test_filter_downstream_no_branch() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot downstream 2>&1)
    assert_contains "$output" "TestB" && \
    assert_contains "$output" "TestF" && \
    assert_not_contains "$output" "TestA" && \
    assert_not_contains "$output" "TestC"
}

function test_filter_with_master_branch() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_sail master 2>&1)
    assert_contains "$output" "TestA" && \
    assert_contains "$output" "TestC" && \
    assert_contains "$output" "TestD" && \
    assert_contains "$output" "TestF"
}

function test_filter_with_release_branch() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_helm release-1.24 2>&1)
    assert_contains "$output" "TestA" && \
    assert_contains "$output" "TestE" && \
    assert_contains "$output" "TestF"
}

function test_filter_with_non_matching_branch() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_sail release-1.30 2>&1)
    assert_contains "$output" "TestA" && \
    assert_contains "$output" "TestC" && \
    assert_contains "$output" "TestF" && \
    assert_not_contains "$output" "TestD"
}

function test_subsuite_filtering_no_branch() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_sail 2>&1)
    assert_contains "$output" "subsuite1" && \
    assert_not_contains "$output" "subsuite2"
}

function test_subsuite_filtering_with_branch() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_sail release-1.28 2>&1)
    assert_contains "$output" "subsuite1" && \
    assert_contains "$output" "subsuite2"
}

function test_run_tests_only_filtering() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot downstream 2>&1)
    assert_contains "$output" "SKIP_PARSER_RUN_TESTS_ONLY='TestOnlyA'"
}

function test_empty_suite() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" security midstream_sail 2>&1)
    assert_contains "$output" "SKIP_PARSER_SKIP_TESTS=''" && \
    assert_contains "$output" "SKIP_PARSER_SKIP_SUBSUITES=''"
}

function test_output_format() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_sail 2>&1)
    assert_contains "$output" "SKIP_PARSER_SKIP_TESTS=" && \
    assert_contains "$output" "SKIP_PARSER_SKIP_SUBSUITES=" && \
    assert_contains "$output" "SKIP_PARSER_RUN_TESTS_ONLY=" && \
    assert_contains "$output" "SKIP_PARSER_SUITE="
}

function test_eval_compatibility() {
    eval "$($SCRIPT_PATH "$TEST_CONFIG_FILE" pilot midstream_sail 2>&1)"
    [[ "$SKIP_PARSER_SUITE" == "pilot" ]] && [[ -n "$SKIP_PARSER_SKIP_TESTS" ]]
}

# Main execution
echo -e "${YELLOW}Running parse-test-config.sh tests...${NC}"
echo ""

setup

# Run all tests
run_test test_invalid_stream_parameter
run_test test_accepts_midstream_sail
run_test test_accepts_midstream_helm
run_test test_accepts_downstream
run_test test_filter_midstream_sail_no_branch
run_test test_filter_midstream_helm_no_branch
run_test test_filter_downstream_no_branch
run_test test_filter_with_master_branch
run_test test_filter_with_release_branch
run_test test_filter_with_non_matching_branch
run_test test_subsuite_filtering_no_branch
run_test test_subsuite_filtering_with_branch
run_test test_run_tests_only_filtering
run_test test_empty_suite
run_test test_output_format
run_test test_eval_compatibility

cleanup

# Summary
echo ""
echo "================================"
echo -e "Tests: ${GREEN}$PASSED passed${NC}, ${RED}$FAILED failed${NC}"
echo "================================"

if [ $FAILED -gt 0 ]; then
    exit 1
fi
