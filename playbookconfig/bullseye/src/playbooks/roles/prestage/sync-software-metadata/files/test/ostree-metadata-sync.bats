#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# vim: set filetype=bash :

# bats unit tests: https://github.com/bats-core
bats_require_minimum_version 1.5.0

# source the script under test
. /code/ostree-metadata-sync.sh

TEST_METADATA_BASE=/tmp/ostree-metadata-sync-test

# The setup function is automatically called before each test
setup() {
    echo "Running setup"
    bats_load_library bats-support
    bats_load_library bats-assert
    bats_load_library bats-file

    mkdir "${TEST_METADATA_BASE}" || fail 'mkdir failed'
    cp -r /code/test/metadata/test1 "${TEST_METADATA_BASE}" || fail 'cp failed'
    cp -r /code/test/metadata/test2 "${TEST_METADATA_BASE}" || fail 'cp failed'
}

init_metadata_dir() {
    local test_dir_base=$1
    export METADATA_DIR="${test_dir_base}"/metadata
    export METADATA_SYNC_DIR="${test_dir_base}"/tmp/metadata-sync

    export MAJOR_SW_VERSION="24.03"
    export MINOR_SW_VERSION="24.03.1"
    export SW_VERSION=$MAJOR_SW_VERSION

    export DRY_RUN=1

    initialize_env
}

mock_command() {
    # usage: mock_command <command> <mock output>
    local command=$1
    shift
    eval "export MOCK_OUTPUT_${command}=\"$*\""
    eval "${command}() { echo \"\${MOCK_OUTPUT_${command}}\"; }"
}

mock_command_exit_code() {
    # mocks a command which only returns 0/1
    # usage: mock_command_exit_code <command> <exit_code>
    local command=$1
    local exit_code=$2
    eval "${command}() { return ${exit_code}; }"
}

unmock_command() {
    local command=$1
    eval "unset -f ${command}"
}

# The teardown function runs after each individual test in a file, regardless of test success or failure
teardown() {
    if [ -n "${TEST_METADATA_BASE}" ]; then
        rm -rf  "${TEST_METADATA_BASE}" || fail 'rmdir failed'
    fi
}

@test "test infrastructure and mocking" {
    # this is a test of functions defined in bash-template.sh
    run log_info "Testing log_info"
    assert_output --partial "Testing log_info"
    run log_warn "Testing log_warn"
    assert_output --partial "Testing log_warn"
    run log_progress "Testing log_progress"
    assert_output --partial "Testing log_progress"
    run log_error "Testing log_error (ignore)"
    assert_output --partial "Testing log_error (ignore)"

    mock_command testmock "testing mock"
    run testmock
    assert_output "testing mock"
    unmock_command testmock
    run -127 testmock

    mock_command ostree "ostree output"
    run ostree
    assert_output "ostree output"
    unmock_command ostree
    run -127 ostree

    mock_command_exit_code testexit 0
    run -0 testexit
    unmock_command textexit
    run -127 textexit
    mock_command_exit_code testexit 1
    run -1 testexit
    unmock_command textexit
    run -127 textexit
}

@test "test1 utilities" {
    init_metadata_dir "${TEST_METADATA_BASE}"/test1

    # Test standalone utilities

    local id="starlingx-24.03.0"
    local sw_version="24.03.0"
    local test_metadata_file="${METADATA_DIR}/deployed/${id}-metadata.xml"

    run find_metadata_files_for_release_sorted "${SW_VERSION}"
    assert_output "${test_metadata_file}"

    run get_simple_xml_attrib_from_metadata "${test_metadata_file}" "id"
    assert_output "${id}"
    run get_simple_xml_attrib_from_metadata "${test_metadata_file}" "sw_version"
    assert_output "${sw_version}"
    run get_simple_xml_attrib_from_metadata "${test_metadata_file}" "commit"
    assert_output ""

    run get_usm_state_from_path "${test_metadata_file}"
    assert_output deployed

    run find_metadata_file_for_attrib_val "id" "starlingx-24.03.0" "${METADATA_DIR}"
    assert_output "${test_metadata_file}"

    local test_central_metadata_file="${METADATA_SYNC_METADATA_DIR}/deployed/${id}-metadata.xml"
    run translate_central_metadata_path "${test_metadata_file}"
    assert_output "${test_central_metadata_file}"

    run find_all_ostree_commits_for_release "${SW_VERSION}"
    assert_output "${METADATA_DIR}/deployed/starlingx-24.03.0-metadata.xml:-"
}

@test "test1 data: sync subcloud metadata" {
    init_metadata_dir "${TEST_METADATA_BASE}"/test1

    # mock
    mock_command_exit_code pull_ostree_commit_on_subcloud 0
    mock_command_exit_code ostree_commit_exists 0
    run sync_subcloud_metadata
    assert_success

    unmock_command pull_ostree_commit_on_subcloud
    unmock_command ostree_commit_exists
}

@test "test2 data: find operations on major release" {
    init_metadata_dir "${TEST_METADATA_BASE}"/test2

    run find_metadata_files_for_release_sorted  "${SW_VERSION}"
    assert_output "/tmp/ostree-metadata-sync-test/test2/metadata/deployed/starlingx-24.03.0-metadata.xml
/tmp/ostree-metadata-sync-test/test2/metadata/deployed/starlingx-24.03.1-metadata.xml
/tmp/ostree-metadata-sync-test/test2/metadata/deploying/starlingx-24.03.2-metadata.xml
/tmp/ostree-metadata-sync-test/test2/metadata/available/starlingx-24.03.3-metadata.xml"

    run find_all_ostree_commits_for_release "${SW_VERSION}"
    assert_output "${METADATA_DIR}/deployed/starlingx-24.03.0-metadata.xml:-
${METADATA_DIR}/deployed/starlingx-24.03.1-metadata.xml:db313865837f9512b024a2356bd76106140ebcea783f8183e5fcc8d5cd28783b
${METADATA_DIR}/deploying/starlingx-24.03.2-metadata.xml:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
${METADATA_DIR}/available/starlingx-24.03.3-metadata.xml:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}

@test "test2 data: find operations on minor release" {
    init_metadata_dir "${TEST_METADATA_BASE}"/test2

    export SW_VERSION=$MINOR_SW_VERSION

    run find_metadata_files_for_release_sorted  "${SW_VERSION}"
    assert_output "/tmp/ostree-metadata-sync-test/test2/metadata/deployed/starlingx-24.03.1-metadata.xml"

    run find_all_ostree_commits_for_release "${SW_VERSION}"
    assert_output "${METADATA_DIR}/deployed/starlingx-24.03.1-metadata.xml:db313865837f9512b024a2356bd76106140ebcea783f8183e5fcc8d5cd28783b"
}

