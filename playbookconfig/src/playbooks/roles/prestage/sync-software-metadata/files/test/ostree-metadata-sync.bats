#
# Copyright (c) 2026 Wind River Systems, Inc.
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


# ---------------------------------------------------------------------------
# test3 data: 26.10.0 component-based release
#
# Unlike test1/test2 (legacy per-state metadata directories:
# deployed/available/deploying/unavailable), 26.10.0 uses the component-based
# metadata layout:
#   - central: flat file "${METADATA_SYNC_METADATA_DIR}/starlingx-<sw_version>-metadata.xml"
#   - subcloud: flat "${METADATA_DIR}" (releases/metadata), no legacy state subdirs
#
# The fixture models a fresh subcloud prestage of 26.10.0 where the subcloud
# has no prior metadata for this release (i.e. it must become "available").
# ---------------------------------------------------------------------------

init_metadata_dir_26_10() {
    local test_dir_base=$1

    # test3 is not copied by the shared setup() (which only stages
    # test1/test2), so stage it here, scoped to these 26.10.0 tests only.
    if [ ! -d "${test_dir_base}" ]; then
        cp -r /code/test/metadata/test3 "$(dirname "${test_dir_base}")" || fail 'cp failed'
    fi

    export METADATA_DIR="${test_dir_base}"/metadata
    export METADATA_SYNC_DIR="${test_dir_base}"/tmp/metadata-sync

    export MAJOR_SW_VERSION="26.10"
    export SW_VERSION="26.10.0"
    export SC_SW_VERSION="26.10.0"

    export DRY_RUN=1

    # initialize_env() shells out to `source /etc/build.info` (via a nested
    # bash -c) to determine the subcloud release version. In the test
    # container this file does not exist, and its absence is fatal under
    # bats' error trapping. Provide a minimal stand-in scoped to this test.
    if [ ! -f /etc/build.info ]; then
        echo "SW_VERSION=${SW_VERSION}" > /etc/build.info
        BUILD_INFO_CREATED_BY_TEST=1
    fi

    initialize_env
}

cleanup_build_info_26_10() {
    if [ "${BUILD_INFO_CREATED_BY_TEST:-}" = "1" ]; then
        rm -f /etc/build.info
        unset BUILD_INFO_CREATED_BY_TEST
    fi
}

@test "test3 data: 26.10.0 utilities" {
    init_metadata_dir_26_10 "${TEST_METADATA_BASE}"/test3

    local id="starlingx-26.10.0"
    local sw_version="26.10.0"
    local test_central_metadata_file="${METADATA_SYNC_METADATA_DIR}/${id}-metadata.xml"

    local commit_hash="cdc21aadaff849ce48b4ea5dce6eadd7be9f1e81f3e0bb28eed979cfbb4359fa"

    # xml_attrib_metadata() shells out to python to parse the metadata XML.
    # python is not provisioned in this test container, so mock the
    # attribute lookups against the known contents of the test3 fixture
    # (see metadata/test3/tmp/metadata-sync/metadata/starlingx-26.10.0-metadata.xml).
    xml_attrib_metadata() {
        case "$3" in
            id) echo "${id}" ;;
            sw_version) echo "${sw_version}" ;;
            contents/ostree/commit1/commit) echo "${commit_hash}" ;;
            *) echo "" ;;
        esac
    }

    run xml_attrib_metadata "${test_central_metadata_file}" "get" "id"
    assert_output "${id}"
    run xml_attrib_metadata "${test_central_metadata_file}" "get" "sw_version"
    assert_output "${sw_version}"

    local commit_hashes=()
    get_commit_hashes_from_metadata commit_hashes "${test_central_metadata_file}"
    assert_equal "${commit_hashes}" "${commit_hash}"

    run get_central_metadata_file_for_release "${id}"
    assert_output "${test_central_metadata_file}"

    run version_ge "${MAJOR_SW_VERSION}" "26.10"
    assert_success
    run version_le "${SUBCLOUD_MAJOR_VERSION}" "26.03"
    assert_failure

    unmock_command xml_attrib_metadata
    cleanup_build_info_26_10
}

@test "test3 data: sync subcloud metadata for 26.10.0 (component-based)" {
    init_metadata_dir_26_10 "${TEST_METADATA_BASE}"/test3

    # Avoid touching the real system/network during ostree repo configuration and sync.
    mock_command_exit_code configure_ostree_repo_for_central_pull 0
    mock_command_exit_code sync_ostree_repo 0

    # xml_attrib_metadata() shells out to python to parse XML, which is not
    # provisioned in this test container. Mock it generically (grep/sed based,
    # same implementation used by the TC1-TC3 tests below).
    xml_attrib_metadata() {
        local meta_file="$1" action="$2" attrib="$3" value="${4:-}"
        local tag="${attrib##*/}"
        if [ "${action}" == "get" ]; then
            sed -n "s:.*<${tag}>\\(.*\\)</${tag}>.*:\\1:p" "${meta_file}" | head -1
        elif [ "${action}" == "set" ]; then
            sed -i "s:<${tag}>[^<]*</${tag}>:<${tag}>${value}</${tag}>:" "${meta_file}"
        fi
    }

    run sync_subcloud_metadata "${SW_VERSION}" "${SC_SW_VERSION}"
    assert_success
    assert_output --partial "starlingx-26.10.0"
    # Since the subcloud has no prior 26.10.0 metadata, it must be staged as "available".
    assert_output --partial "Does not exist in Subcloud. Setting state to available."
    # Component-based dest dir does not use the legacy per-state subdirectories.
    assert_output --partial "releases/metadata"

    unmock_command configure_ostree_repo_for_central_pull
    unmock_command sync_ostree_repo
    unmock_command xml_attrib_metadata

    cleanup_build_info_26_10
}

# ---------------------------------------------------------------------------
# TC1-TC3: subcloud prestage scenarios for component-based releases (>= 26.10)
#
# These scenarios exercise sync_subcloud_metadata() across the different
# subcloud/system-controller relative release combinations:
#
#   TC1: N-2 subcloud - prestage 26.10.0, subcloud at 25.09,   sc at 26.10.0
#   TC2: N-1 subcloud - prestage 26.10.0, subcloud at 26.03,   sc at 26.10.0
#   TC3: Re-prestage N subcloud - prestage 26.10.1 (subcloud already has
#        26.10.0 deployed), subcloud at 26.10,   sc at 26.10.0
#   TC4 and TC5: Unavailable release on System Controller, but available on
#                Subcloud.
#
# Fixture layout (files/test/metadata/test3/tc<N>/):
#   build.info               - stand-in for the subcloud's /etc/build.info
#   metadata/                 - subcloud's own metadata dir (METADATA_DIR)
#   tmp/metadata-sync/metadata/ - copy of the system controller's metadata
#                                 dir, as staged by ansible (METADATA_SYNC_DIR)
#
# xml_attrib_metadata() shells out to python to parse XML, which is not
# provisioned in this test container (see test3 "utilities" test above for
# the same limitation). It is mocked here with a grep/sed based
# implementation that works generically against any of the XML fixtures
# used in these tests.
# ---------------------------------------------------------------------------

# Fake xml_attrib_metadata() that reads/writes simple, non-nested XML tags
# using grep/sed, sufficient for the flat tags used in the test fixtures
# (id, sw_version, prepatched_iso) and the nested commit path used by
# get_commit_hashes_from_metadata (contents/ostree/commit1/commit).
xml_attrib_metadata_fake() {
    local meta_file="$1"
    local action="$2"
    local attrib="$3"
    local value="${4:-}"
    local tag="${attrib##*/}"

    if [ "${action}" == "get" ]; then
        sed -n "s:.*<${tag}>\\(.*\\)</${tag}>.*:\\1:p" "${meta_file}" | head -1
    elif [ "${action}" == "set" ]; then
        sed -i "s:<${tag}>[^<]*</${tag}>:<${tag}>${value}</${tag}>:" "${meta_file}"
    fi
}

init_metadata_dir_tc() {
    # usage: init_metadata_dir_tc <tc_name> <sw_version> <sc_sw_version>
    local tc_name=$1
    local test_dir_base="${TEST_METADATA_BASE}/test3-${tc_name}"

    cp -r "/code/test/metadata/test3/${tc_name}" "${test_dir_base}" || fail 'cp failed'

    export METADATA_DIR="${test_dir_base}"/metadata
    export METADATA_SYNC_DIR="${test_dir_base}"/tmp/metadata-sync

    export SW_VERSION="$2"
    export SC_SW_VERSION="$3"
    export MAJOR_SW_VERSION
    MAJOR_SW_VERSION=$(get_major_release_version "${SW_VERSION}")

    export DRY_RUN=1

    # Stand in for the subcloud's /etc/build.info, scoped to this test.
    if [ -f /etc/build.info ]; then
        cp /etc/build.info /tmp/build.info.orig.bak
        BUILD_INFO_BACKED_UP=1
    fi
    cp "${test_dir_base}/build.info" /etc/build.info
    BUILD_INFO_CREATED_BY_TEST=1

    initialize_env

    xml_attrib_metadata() { xml_attrib_metadata_fake "$@"; }
}

cleanup_metadata_dir_tc() {
    if [ "${BUILD_INFO_CREATED_BY_TEST:-}" = "1" ]; then
        rm -f /etc/build.info
        unset BUILD_INFO_CREATED_BY_TEST
    fi
    if [ "${BUILD_INFO_BACKED_UP:-}" = "1" ]; then
        mv /tmp/build.info.orig.bak /etc/build.info
        unset BUILD_INFO_BACKED_UP
    fi
    unmock_command xml_attrib_metadata
    unmock_command configure_ostree_repo_for_central_pull
    unmock_command sync_ostree_repo
}

@test "test3 data: find_component_metadata_files_for_release_sorted" {
    # Uses the tc3 fixture, which has product + metapackage metadata for both
    # 26.10.0 (under deployed/) and 26.10.1 (also under
    # metapackages/deployed/), i.e. two minor releases under the same major.
    local test_dir_base="${TEST_METADATA_BASE}/test3-fcmffrs"
    cp -r /code/test/metadata/test3/tc3 "${test_dir_base}" || fail 'cp failed'

    export METADATA_SYNC_METADATA_DIR="${test_dir_base}/tmp/metadata-sync/metadata"

    xml_attrib_metadata() { xml_attrib_metadata_fake "$@"; }

    # Searching by major version, with no state_dirs filter, returns both
    # minor releases' product files, sorted ascending.
    run find_component_metadata_files_for_release_sorted "26.10" "${METADATA_SYNC_METADATA_DIR}"
    assert_output "${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.0-metadata.xml
${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.1-metadata.xml"

    # Searching by exact minor version only returns that release's product file.
    run find_component_metadata_files_for_release_sorted "26.10.0" "${METADATA_SYNC_METADATA_DIR}"
    assert_output "${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.0-metadata.xml"

    # Both 26.10.0 and 26.10.1 have metapackage evidence under deployed/,
    # so filtering by state_dirs="deployed" keeps both product releases.
    run find_component_metadata_files_for_release_sorted "26.10" "${METADATA_SYNC_METADATA_DIR}" "deployed"
    assert_output "${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.0-metadata.xml
${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.1-metadata.xml"

    # Filtering by a state with no matching metapackage evidence (e.g.
    # "available") drops every release: none of the fixture's metapackage
    # files live under available/.
    run find_component_metadata_files_for_release_sorted "26.10" "${METADATA_SYNC_METADATA_DIR}" "available"
    assert_output ""

    # A release with no matching product files at all returns nothing.
    run find_component_metadata_files_for_release_sorted "26.09" "${METADATA_SYNC_METADATA_DIR}"
    assert_output ""

    unmock_command xml_attrib_metadata
}

@test "test3 TC1: prestage 26.10.0 to N-2 subcloud (25.09)" {
    init_metadata_dir_tc "tc1" "26.10.0" "25.09.0"

    mock_command_exit_code configure_ostree_repo_for_central_pull 0
    mock_command_exit_code sync_ostree_repo 0

    run sync_subcloud_metadata "${SW_VERSION}" "${SC_SW_VERSION}"
    assert_success
    # Origin (system controller): tmp/metadata-sync/metadata/starlingx-26.10.0-metadata.xml
    assert_output --partial "starlingx-26.10.0"
    # Fresh prestage: subcloud has no prior metadata for this release.
    assert_output --partial "Does not exist in Subcloud. Setting state to available."
    # Legacy subcloud (25.09 <= 26.03): product release goes to BOTH
    # /opt/software/metadata/available AND /opt/software/releases/metadata/.
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.0-metadata.xml /opt/software/releases/metadata"
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.0-metadata.xml /opt/software/metadata/available"
    # Metapackage releases are staged from the central "deployed" copy (sw_version >
    # sc_sw_version: only trust central's deployed evidence), but land on the
    # subcloud's own /opt/software/releases/metadata/available (fresh prestage).
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/deployed/base_26.10.0-metadata.xml /opt/software/releases/metadata/available"

    cleanup_metadata_dir_tc
}

@test "test3 TC2: prestage 26.10.0 to N-1 subcloud (26.03)" {
    init_metadata_dir_tc "tc2" "26.10.0" "26.03.0"

    mock_command_exit_code configure_ostree_repo_for_central_pull 0
    mock_command_exit_code sync_ostree_repo 0

    run sync_subcloud_metadata "${SW_VERSION}" "${SC_SW_VERSION}"
    assert_success
    # Origin (system controller): tmp/metadata-sync/metadata/starlingx-26.10.0-metadata.xml
    assert_output --partial "starlingx-26.10.0"
    assert_output --partial "Does not exist in Subcloud. Setting state to available."
    # Legacy subcloud (26.03 <= 26.03): product release goes to BOTH
    # /opt/software/metadata/available AND /opt/software/releases/metadata/.
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.0-metadata.xml /opt/software/releases/metadata"
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.0-metadata.xml /opt/software/metadata/available"
    # Metapackage releases are staged from the central "deployed" copy (sw_version >
    # sc_sw_version: only trust central's deployed evidence), but land on the
    # subcloud's own /opt/software/releases/metadata/available (fresh prestage).
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/deployed/base_26.10.0-metadata.xml /opt/software/releases/metadata/available"

    cleanup_metadata_dir_tc
}

@test "test3 TC3: re-prestage 26.10.1 to N subcloud (26.10, already has 26.10.0 deployed)" {
    init_metadata_dir_tc "tc3" "26.10.1" "26.10.0"

    mock_command_exit_code configure_ostree_repo_for_central_pull 0
    mock_command_exit_code sync_ostree_repo 0

    run sync_subcloud_metadata "${SW_VERSION}" "${SC_SW_VERSION}"
    assert_success
    # Origin (subcloud's own prior state): metadata/deployed/starlingx-26.10.0-metadata.xml
    # 26.10.0 is already deployed on the subcloud, so it stays "deployed".
    assert_output --partial "starlingx-26.10.0"
    assert_output --partial "Setting state to deployed."
    # Origin (system controller): tmp/metadata-sync/metadata/starlingx-26.10.1-metadata.xml
    # 26.10.1 is the new patch being prestaged and does not exist on the subcloud yet.
    assert_output --partial "starlingx-26.10.1"
    assert_output --partial "Does not exist in Subcloud. Setting state to available."
    # Component-based subcloud (26.10 > 26.03): no legacy dual-write.
    refute_output --partial "/opt/software/metadata/available"
    refute_output --partial "/opt/software/metadata/deployed"
    # Product releases go only to /opt/software/releases/metadata/.
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.0-metadata.xml /opt/software/releases/metadata"
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/starlingx-26.10.1-metadata.xml /opt/software/releases/metadata"
    # Metapackage for 26.10.0 goes to .../releases/metadata/deployed (already deployed).
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/deployed/base_26.10.0-metadata.xml /opt/software/releases/metadata/deployed"
    # Metapackage for 26.10.1 goes to .../releases/metadata/available (newly staged).
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/deployed/base_26.10.1-metadata.xml /opt/software/releases/metadata/available"

    cleanup_metadata_dir_tc
}

@test "test3 TC4: subcloud rehomed from SC-A to SC-B, SC-B lacks a patch SC-A had prestaged (available drops out)" {
    # A subcloud is running 25.09 and was rehomed from SC-A to SC-B. SC-A had prestaged
    # 26.03.100 onto the subcloud as "available" (staged ahead for a future release,
    # never deployed), but SC-B does not have that patch at all (only the 26.03.0
    # base release). Since 26.03.100 was never installed (only staged) and SC-B does
    # not offer it, it must not surface at all when SC-B prestages the subcloud for
    # 26.03: subcloud_metadata_files only looks at "deployed"/"unavailable" states,
    # so a merely "available" release the subcloud had is simply dropped. 26.03.0,
    # which SC-B does offer and the subcloud never had, becomes "available".
    init_metadata_dir_tc "tc4" "26.03.0" "25.09.0"

    mock_command_exit_code configure_ostree_repo_for_central_pull 0
    mock_command_exit_code sync_ostree_repo 0

    run sync_subcloud_metadata "${SW_VERSION}" "${SC_SW_VERSION}"
    assert_success
    # Origin (system controller SC-B): tmp/metadata-sync/metadata/deployed/starlingx-26.03.0-metadata.xml
    assert_output --partial "starlingx-26.03.0"
    assert_output --partial "Does not exist in Subcloud. Setting state to available."
    # 26.03.0 is copied from SC-B's synced central metadata.
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/deployed/starlingx-26.03.0-metadata.xml /opt/software/metadata/available"
    # 26.03.100 (only "available" on the subcloud, from SC-A, and not offered by
    # SC-B at all) must not appear in the sync output in any form.
    refute_output --partial "starlingx-26.03.100"

    cleanup_metadata_dir_tc
}

@test "test3 TC5: subcloud rehomed with a deployed release SC-B lacks (demoted to unavailable)" {
    # A subcloud is running 25.09.300 (deployed) and was rehomed from SC-A
    # to SC-B. SC-B offers 25.09.400 (a newer patch), but does not have
    # 25.09.300 at all. Since SC-B has no matching copy, 25.09.300 must be
    # reclassified as "unavailable" - a rehome to a central controller that
    # lacks the currently deployed patch demotes it, sourced from the
    # subcloud's own metadata backup via get_subcloud_metadata_file_for_release().
    # 25.09.400, which SC-B offers and the subcloud never had, becomes "available".
    init_metadata_dir_tc "tc5" "25.09.400" "25.09.300"

    mock_command_exit_code configure_ostree_repo_for_central_pull 0
    mock_command_exit_code sync_ostree_repo 0

    run sync_subcloud_metadata "${SW_VERSION}" "${SC_SW_VERSION}"
    assert_success
    # Origin (subcloud's own prior state): metadata/deployed/starlingx-25.09.300-metadata.xml
    assert_output --partial "starlingx-25.09.300"
    assert_output --partial "Does not exist in SystemController. Setting state to unavailable."
    assert_output --partial "Using subcloud_metadata_file:"
    # 25.09.300 is copied from the subcloud's own backup, not central, since SC-B never had it.
    assert_output --partial "/metadata/deployed/starlingx-25.09.300-metadata.xml /opt/software/metadata/unavailable"
    refute_output --partial "${METADATA_SYNC_METADATA_DIR}/deployed/starlingx-25.09.300-metadata.xml"
    # Origin (system controller SC-B): tmp/metadata-sync/metadata/deployed/starlingx-25.09.400-metadata.xml
    assert_output --partial "starlingx-25.09.400"
    assert_output --partial "Does not exist in Subcloud. Setting state to available."
    assert_output --partial "DRY_RUN: cp ${METADATA_SYNC_METADATA_DIR}/deployed/starlingx-25.09.400-metadata.xml /opt/software/metadata/available"

    cleanup_metadata_dir_tc
}
