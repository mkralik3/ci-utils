# Testing Documentation

This directory contains unit tests for the `parse-test-config.sh` script.

## Quick Start

### Simple Test Runner (No Dependencies)

The simplest way to run tests without installing anything:

```bash
cd skip_tests
./run_tests.sh
```

This uses a standalone test runner that doesn't require any external frameworks.

## What's Tested

### Stream Validation
- ✅ Accepts `midstream_sail` as valid stream
- ✅ Accepts `midstream_helm` as valid stream
- ✅ Accepts `downstream` as valid stream
- ✅ Rejects invalid stream values

### Filtering Logic
- ✅ Filters tests by `midstream_sail` stream
- ✅ Filters tests by `midstream_helm` stream
- ✅ Filters tests by `downstream` stream
- ✅ Correctly handles multiple streams in `skip_in` arrays

### Branch Filtering
- ✅ Excludes tests with `skip_branches_only` when no branch specified
- ✅ Includes tests with matching `skip_branches_only` when branch matches
- ✅ Excludes tests with non-matching `skip_branches_only` when branch doesn't match
- ✅ Handles master branch filtering
- ✅ Handles release branch filtering (release-1.24, release-1.28)

### Subsuite Handling
- ✅ Filters subsuites correctly without branch
- ✅ Filters subsuites correctly with branch
- ✅ Respects `skip_branches_only` for subsuites

### Output Format
- ✅ All required environment variables present
- ✅ Multiple tests are pipe-separated
- ✅ Output is compatible with `eval`

### Edge Cases
- ✅ Empty test suites return empty results
- ✅ Non-existent config file error handling
- ✅ run_tests_only filtering

## Test Results

Current status: ✅ **All 16 tests passing**

```
✓ test_invalid_stream_parameter
✓ test_accepts_midstream_sail
✓ test_accepts_midstream_helm
✓ test_accepts_downstream
✓ test_filter_midstream_sail_no_branch
✓ test_filter_midstream_helm_no_branch
✓ test_filter_downstream_no_branch
✓ test_filter_with_master_branch
✓ test_filter_with_release_branch
✓ test_filter_with_non_matching_branch
✓ test_subsuite_filtering_no_branch
✓ test_subsuite_filtering_with_branch
✓ test_run_tests_only_filtering
✓ test_empty_suite
✓ test_output_format
✓ test_eval_compatibility
```

## Adding New Tests

### Using run_tests.sh (Simple)

Add a function starting with `test_` to `run_tests.sh`:

```bash
function test_my_new_feature() {
    local output
    output=$("$SCRIPT_PATH" "$TEST_CONFIG_FILE" pilot midstream_sail 2>&1)
    assert_contains "$output" "expected_value"
}
```

Then add it to the main execution section:

```bash
run_test test_my_new_feature
```
