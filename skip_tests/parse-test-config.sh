#!/bin/bash
# Parse test configuration from YAML file
# Usage: ./parse-test-config.sh <config_file> <suite> [stream]
# Example: ./parse-test-config.sh test-config-full.yaml security midstream_sail

set -e

CONFIG_FILE=$1
SKIP_PARSER_SUITE=$2
STREAM=$3
BRANCH=${4:-""}

if [ -z "$CONFIG_FILE" ] || [ -z "$SKIP_PARSER_SUITE" ] || [ -z "$STREAM" ]; then
    echo "Usage: $0 <config_file> <suite> <stream> [branch]" >&2
    echo "  config_file: path to YAML config" >&2
    echo "  suite: pilot, ambient, telemetry, security, or helm" >&2
    echo "  stream: midstream_sail, midstream_helm, or downstream - returns only tests with this value in skip_in" >&2
    echo "  branch: (optional) branch name - filters by branches_only/skip_branches_only fields" >&2
    exit 1
fi

# Validate stream parameter
if [ "$STREAM" != "midstream_sail" ] && [ "$STREAM" != "midstream_helm" ] && [ "$STREAM" != "downstream" ]; then
    echo "Error: stream must be 'midstream_sail', 'midstream_helm', or 'downstream', got: '$STREAM'" >&2
    exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file '$CONFIG_FILE' not found"
    exit 1
fi

# Check if yq is available
if ! command -v yq &> /dev/null; then
    echo "Error: 'yq' is required but not installed."
    echo "Install with: brew install yq (macOS) or snap install yq (Linux)"
    exit 1
fi

# Build yq filter to return tests that have the specified stream in their skip_in array
# Since skip_in is now required, we only select tests where skip_in contains the specified stream
if [ -n "$BRANCH" ]; then
    # With branch filtering:
    # - skip_branches_only: if set, skip ONLY on those branches (include if branch matches)
    # - If not set: skip on all branches (no branch-specific filtering)

    # Step 1: Filter by stream - get as array
    TEMP_SKIP_TESTS=$(yq eval "[.test_suites.$SKIP_PARSER_SUITE.skip_tests[] | select(.skip_in[] == \"$STREAM\")]" "$CONFIG_FILE" 2>/dev/null)
    TEMP_SKIP_SUBSUITES=$(yq eval "[.test_suites.$SKIP_PARSER_SUITE.skip_subsuites[] | select(.skip_in[] == \"$STREAM\")]" "$CONFIG_FILE" 2>/dev/null)
    TEMP_RUN_TESTS_ONLY=$(yq eval "[.test_suites.$SKIP_PARSER_SUITE.run_tests_only[] | select(.skip_in[] == \"$STREAM\")]" "$CONFIG_FILE" 2>/dev/null)

    # Step 2: Filter by branch rules using a helper function
    filter_by_branch() {
        local item="$1"
        local has_skip_branches_only=$(echo "$item" | yq eval 'has("skip_branches_only")' -)

        # Check skip_branches_only: if set, must contain current branch to be included
        if [ "$has_skip_branches_only" = "true" ]; then
            local in_skip_branches=$(echo "$item" | yq eval ".skip_branches_only[] | select(. == \"$BRANCH\")" - 2>/dev/null)
            if [ -z "$in_skip_branches" ]; then
                return 1  # Branch not in skip_branches_only, exclude (don't skip this test)
            fi
        fi
        # If skip_branches_only is not set, include (skip on all branches)

        return 0  # Include this test
    }

    # Process skip_tests
    SKIP_PARSER_SKIP_TESTS=""
    test_count=$(echo "$TEMP_SKIP_TESTS" | yq eval '. | length' - 2>/dev/null)
    if [ "$test_count" != "0" ] && [ "$test_count" != "null" ] && [ -n "$test_count" ]; then
        i=0
        while [ $i -lt $test_count ]; do
            test_item=$(echo "$TEMP_SKIP_TESTS" | yq eval ".[$i]" - 2>/dev/null)
            if filter_by_branch "$test_item"; then
                test_name=$(echo "$test_item" | yq eval '.name' -)
                if [ -z "$SKIP_PARSER_SKIP_TESTS" ]; then
                    SKIP_PARSER_SKIP_TESTS="$test_name"
                else
                    SKIP_PARSER_SKIP_TESTS="$SKIP_PARSER_SKIP_TESTS|$test_name"
                fi
            fi
            i=$((i + 1))
        done
    fi

    # Process skip_subsuites
    SKIP_PARSER_SKIP_SUBSUITES=""
    test_count=$(echo "$TEMP_SKIP_SUBSUITES" | yq eval '. | length' - 2>/dev/null)
    if [ "$test_count" != "0" ] && [ "$test_count" != "null" ] && [ -n "$test_count" ]; then
        i=0
        while [ $i -lt $test_count ]; do
            test_item=$(echo "$TEMP_SKIP_SUBSUITES" | yq eval ".[$i]" - 2>/dev/null)
            if filter_by_branch "$test_item"; then
                test_name=$(echo "$test_item" | yq eval '.name' -)
                if [ -z "$SKIP_PARSER_SKIP_SUBSUITES" ]; then
                    SKIP_PARSER_SKIP_SUBSUITES="$test_name"
                else
                    SKIP_PARSER_SKIP_SUBSUITES="$SKIP_PARSER_SKIP_SUBSUITES|$test_name"
                fi
            fi
            i=$((i + 1))
        done
    fi

    # Process run_tests_only
    SKIP_PARSER_RUN_TESTS_ONLY=""
    test_count=$(echo "$TEMP_RUN_TESTS_ONLY" | yq eval '. | length' - 2>/dev/null)
    if [ "$test_count" != "0" ] && [ "$test_count" != "null" ] && [ -n "$test_count" ]; then
        i=0
        while [ $i -lt $test_count ]; do
            test_item=$(echo "$TEMP_RUN_TESTS_ONLY" | yq eval ".[$i]" - 2>/dev/null)
            if filter_by_branch "$test_item"; then
                test_name=$(echo "$test_item" | yq eval '.name' -)
                if [ -z "$SKIP_PARSER_RUN_TESTS_ONLY" ]; then
                    SKIP_PARSER_RUN_TESTS_ONLY="$test_name"
                else
                    SKIP_PARSER_RUN_TESTS_ONLY="$SKIP_PARSER_RUN_TESTS_ONLY|$test_name"
                fi
            fi
            i=$((i + 1))
        done
    fi

    # Skip the normal extraction since we already have the values
    SKIP_EXTRACTION=true
else
    # Without branch filtering - only filter by stream and exclude items with skip_branches_only
    # (items with skip_branches_only are branch-specific and should only apply when a branch is specified)
    FILTER_SKIP_TESTS=".test_suites.$SKIP_PARSER_SUITE.skip_tests[] | select(.skip_in[] == \"$STREAM\") | select(has(\"skip_branches_only\") | not) | .name"
    FILTER_SKIP_SUBSUITES=".test_suites.$SKIP_PARSER_SUITE.skip_subsuites[] | select(.skip_in[] == \"$STREAM\") | select(has(\"skip_branches_only\") | not) | .name"
    FILTER_RUN_TESTS_ONLY=".test_suites.$SKIP_PARSER_SUITE.run_tests_only[] | select(.skip_in[] == \"$STREAM\") | select(has(\"skip_branches_only\") | not) | .name"
    SKIP_EXTRACTION=false
fi

# Extract tests (skip if already done with branch filtering)
if [ "$SKIP_EXTRACTION" != "true" ]; then
    SKIP_PARSER_SKIP_TESTS=$(yq eval "$FILTER_SKIP_TESTS" "$CONFIG_FILE" 2>/dev/null | paste -sd '|' -)
    SKIP_PARSER_SKIP_SUBSUITES=$(yq eval "$FILTER_SKIP_SUBSUITES" "$CONFIG_FILE" 2>/dev/null | paste -sd '|' -)
    SKIP_PARSER_RUN_TESTS_ONLY=$(yq eval "$FILTER_RUN_TESTS_ONLY" "$CONFIG_FILE" 2>/dev/null | paste -sd '|' -)
fi

# Handle null/empty values
[ "$SKIP_PARSER_SKIP_TESTS" = "null" ] && SKIP_PARSER_SKIP_TESTS=""
[ "$SKIP_PARSER_SKIP_SUBSUITES" = "null" ] && SKIP_PARSER_SKIP_SUBSUITES=""
[ "$SKIP_PARSER_RUN_TESTS_ONLY" = "null" ] && SKIP_PARSER_RUN_TESTS_ONLY=""

# Output as shell variables (to stdout for eval)
echo "SKIP_PARSER_SKIP_TESTS=error"
echo "SKIP_PARSER_SKIP_SUBSUITES='$SKIP_PARSER_SKIP_SUBSUITES'"
echo "SKIP_PARSER_RUN_TESTS_ONLY='$SKIP_PARSER_RUN_TESTS_ONLY'"
echo "SKIP_PARSER_SUITE='$SKIP_PARSER_SUITE'"

# Example usage in another script:
# Midstream Sail:
#   eval $(./parse-test-config.sh test-config-full.yaml security midstream_sail)
# Midstream Helm:
#   eval $(./parse-test-config.sh test-config-full.yaml security midstream_helm)
# Downstream with branch:
#   eval $(./parse-test-config.sh test-config-full.yaml security downstream master)
# Midstream Sail with branch:
#   eval $(./parse-test-config.sh test-config-full.yaml helm midstream_sail release-1.24)
# Midstream Helm with branch:
#   eval $(./parse-test-config.sh test-config-full.yaml helm midstream_helm release-1.24)
# Then run:
#   integ-suite-ocp.sh "$SKIP_PARSER_SUITE" "$SKIP_PARSER_SKIP_TESTS" "$SKIP_PARSER_SKIP_SUBSUITES" "$SKIP_PARSER_RUN_TESTS_ONLY"
