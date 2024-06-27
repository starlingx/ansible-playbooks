#!/bin/bash
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# vim: filetype=sh shiftwidth=4 softtabstop=4 expandtab

set -o nounset;  # Do not allow use of undefined vars. Use ${VAR:-} to use an undefined VAR. Same as 'set -u'
set -o pipefail; # Catch the error in case a piped command fails
# set -o xtrace;   # Turn on traces, useful while debugging (short form: on: 'set -x' off: 'set +x')

################################################################################
#
# Testing:
# This script has unit tests. Run the unit tests manually via: ./test/run-bats.sh
#
################################################################################
#
# Structure:
# This script has two top-level modes of operation, based on the subcommands:
# - get-commits    (implementation: find_all_ostree_commits_for_release)
# - sync-subcloud  (implementation: sync_subcloud_metadata)
#
################################################################################

################################################################################
# Helpers
#

# shellcheck disable=SC2155
readonly SCRIPTNAME=$(basename "$0")
# shellcheck disable=SC2155,SC2034
#readonly SCRIPTDIR=$(readlink -m "$(dirname "$0")")

SW_VERSION=${SW_VERSION:-}

DEBUG=${DEBUG:-}
DRY_RUN=${DRY_RUN:-}

help() {
cat<<EOF
ostree metadata synchronization utilities.
This script is invoked via ansible.

USAGE:
  $SCRIPTNAME <options> [ get-commits | sync-subcloud ]

The script behaves differently depending on the 'get-commits' or 'sync-subcloud' subcommand:

  get-commits :   For the given major software version, get a list of all metadata file + ostree commit hash
                  Returns a list of: <metadata_file>:<ostree_commit_hash>
                  If the ostree_commit_hash is not known then this field is set to '-'

  sync-subcloud : Synchronize /opt/software/metadata directory on the subcloud.
                  This subcommand *must be run as root*, and is executed on the subcloud
                  via ansible, after setting up proper contents of the \$METADATA_SYNC_DIR
                  See documentation in sync_metadata_on_subcloud() for algorithm details.

OPTIONS:

  -o|--output <file> : Save script output to file.
  -v|--sw-version <version> : Software version being synchronized.

  -D|--debug: Show extra debug information.
  --dry-run:  Dry run. Makes no changes.
  -h|--help: print this help

EXAMPLES:

  $SCRIPTNAME --sw-version 24.09 get-commits
  sudo $SCRIPTNAME --sw-version 24.09 sync-subcloud
EOF
exit 1
}

# Logging: these all log to stderr
die() { >&2 colorecho red "FATAL: $*"; exit 1; }
die_with_rc() { local rc=$1; shift; >&2 colorecho red "FATAL: $*, rc=$rc"; exit "$rc"; }
check_rc_die() { local rc=$1; shift; [ "$rc" != "0" ] && die_with_rc "$rc" "$@"; return 0; }
check_rc_err() { local rc=$1; shift; [ "$rc" != "0" ] && log_error "$*, rc=$rc"; return 0; }
log_error() { >&2 colorecho red "ERROR: $*"; }
log_warn() { >&2 colorecho orange "WARN: $*"; }
log_info() { >&2 echo "$*"; }
log_info_l() {
    local line spacer=''
    for line in "$@"; do
        [ -n "${line}" ] && >&2 echo "${spacer}${line}"
        spacer='    '
    done
}
log_debug() { if [ -n "$DEBUG" ]; then >&2 echo "DEBUG: $*"; fi; }
log_debug_l() {
    [ -z "$DEBUG" ] && return
    local line spacer=''
    for line in "$@"; do
        [ -n "${line}" ] && >&2 echo "${spacer}${line}"
        spacer='    '
    done
}
log_progress() { >&2 colorecho green "$*"; }
get_logdate() { date '+%Y-%m-%d %H:%M:%S'; }  # eg: log_info "$(get_logdate) My log message"
# Optionals to log output to file (see http://mywiki.wooledge.org/BashFAQ/106)
_init_log() { LOG_FILE="${LOG_FILE:-$(pwd)/${SCRIPTNAME%.*}.log}"; log_progress "$(get_logdate) Logging output to $LOG_FILE"; }
# output to file only:
redirect_output_to_file() { _init_log; exec &> "$LOG_FILE"; }
# output to console and file:
tee_output_to_file_single_process() { _init_log; exec &> >(exec tee "$LOG_FILE"); } # see https://superuser.com/a/1534702
tee_output_to_file() { _init_log; exec &> >(tee "$LOG_FILE"); }

colorecho() {  # usage: colorecho <colour> <text> or colorecho -n <colour> <text>
    local echo_arg=
    if [ "$1" = "-n" ]; then
        echo_arg="-n"; shift
    fi
    local colour="$1"; shift
    case "${colour}" in
        red) echo $echo_arg -e "$(tput setaf 1)$*$(tput sgr0)"; ;;
        green) echo $echo_arg -e "$(tput setaf 2)$*$(tput sgr0)"; ;;
        green-bold) echo $echo_arg -e "$(tput setaf 2; tput bold)$*$(tput sgr0)"; ;;
        yellow) echo $echo_arg -e "$(tput setaf 3; tput bold)$*$(tput sgr0)"; ;;
        orange) echo $echo_arg -e "$(tput setaf 3)$*$(tput sgr0)"; ;;
        blue) echo $echo_arg -e "$(tput setaf 4)$*$(tput sgr0)"; ;;
        purple) echo $echo_arg -e "$(tput setaf 5)$*$(tput sgr0)"; ;;
        cyan) echo $echo_arg -e "$(tput setaf 6)$*$(tput sgr0)"; ;;
        bold) echo $echo_arg -e "$(tput bold)$*$(tput sgr0)"; ;;
        normal|*) echo $echo_arg -e "$*"; ;;
    esac
}


################################################################################
#
# Utilities
#
################################################################################

initialize_env() {
    if [ -f /etc/platform/openrc ]; then
        # shellcheck disable=SC1091
        source /etc/platform/openrc
    else
        # unit testing
        log_warn "not found: /etc/platform/openrc"
    fi

    export METADATA_DIR=${METADATA_DIR:-/opt/software/metadata}
    export METADATA_SYNC_DIR=${METADATA_SYNC_DIR:-/opt/software/tmp/metadata-sync}
    export METADATA_SYNC_METADATA_DIR=${METADATA_SYNC_DIR}/metadata

    # shellcheck disable=SC1091
    if [ -z "${SW_VERSION}" ]; then
        source /etc/build.info
    fi
    export SW_VERSION

    local version_array
    IFS='.' read -ra version_array <<< "${SW_VERSION}"
    MAJOR_SW_VERSION=$(get_major_release_version "${SW_VERSION}")
    export MAJOR_SW_VERSION

    export OSTREE_REPO="/var/www/pages/feed/rel-${MAJOR_SW_VERSION}/ostree_repo"
    export OSTREE_REMOTE=starlingx
    export OSTREE_BRANCH=starlingx
    export OSTREE_LOCAL_REF="${OSTREE_REMOTE}"
    export OSTREE_REMOTE_REF="${OSTREE_REMOTE}:${OSTREE_BRANCH}"
    export OSTREE_HTTP_PORT=8080
    export OSTREE_HTTPS_PORT=8443

    log_debug_l "SW_VERSION: ${SW_VERSION}"\
        "MAJOR_SW_VERSION: ${MAJOR_SW_VERSION}"\
        "OSTREE_REPO: ${OSTREE_REPO}"\
        "OSTREE_LOCAL_REF: ${OSTREE_LOCAL_REF}"\
        "OSTREE_REMOTE_REF: ${OSTREE_REMOTE_REF}"\
        "METADATA_DIR: ${METADATA_DIR}"\
        "METADATA_SYNC_DIR: ${METADATA_SYNC_DIR}"
}


trim() {
    # Trim whitespace from string
    # see https://stackoverflow.com/a/3352015
    local var="$*"
    # remove leading whitespace characters
    var="${var#"${var%%[![:space:]]*}"}"
    # remove trailing whitespace characters
    var="${var%"${var##*[![:space:]]}"}"
    printf '%s' "$var"
}

get_major_release_version() {
    # The given sw_version may be in form YY.MM.nn or just YY.MM
    # Get the major release (YY.MM) by splitting on '.' into an
    # array then constructing MAJOR_SW_VERSION from it
    local sw_version=$1
    local version_array
    IFS='.' read -ra version_array <<< "${sw_version}"
    echo "${version_array[0]}.${version_array[1]}"
}

find_metadata_files_for_release_sorted() {
    # Find all metadata files for given software release (major, e.g YY.MM or minor YY.MM.nn)
    # The files are sorted in order of minor release version, ascending
    # For minor release we should only find one metadata file
    #
    local sw_version=${1:-$SW_VERSION}
    local metadata_dir=${2:-$METADATA_DIR}

    # 1) Get all the sw_version metadata files matching the major/minor software version we're given
    #    Storing in a associative array
    local meta_file
    local -A metadata_files_map  # key: sw_version, value: metadata file
    local found_sw_version
    while IFS= read -r meta_file; do
        found_sw_version=$(get_simple_xml_attrib_from_metadata "${meta_file}" "sw_version")
        metadata_files_map[${found_sw_version}]=${meta_file}
    done < <(grep --recursive --files-with-matches --fixed-strings "<sw_version>${sw_version}" "${metadata_dir}")

    if [ ${#metadata_files_map[@]} -eq 0 ]; then
        return
    fi

    # 2) Sort by sw_version tag (regardless of path)
    local sorted_versions=()
    while IFS= read -rd '' found_sw_version; do
        sorted_versions+=("${found_sw_version}")
    done < <(printf '%s\0' "${!metadata_files_map[@]}" | sort --zero-terminated --version-sort)

    # 3) Return the list of files in sorted order
    local sorted_version
    for sorted_version in "${sorted_versions[@]}"; do
        echo "${metadata_files_map[${sorted_version}]}"
    done
}

find_metadata_file_for_attrib_val() {
    local attrib_name=$1
    local attrib_val=$2
    local metadata_dir=${3:-$METADATA_DIR}
    local meta_file
    local -a metadata_files=()
    while IFS= read -r meta_file; do
        metadata_files+=( "${meta_file}" )
    done < <(grep --recursive --files-with-matches --fixed-strings "<${attrib_name}>${attrib_val}</${attrib_name}>" "${metadata_dir}")
    if [ ${#metadata_files[*]} -eq 1 ]; then
        log_debug "find_metadata_file_for_attrib_val: attrib: ${attrib_name}, value: ${attrib_val}, file: ${metadata_files[0]}"
        echo "${metadata_files[0]}"
    elif [ ${#metadata_files[*]} -gt 1 ]; then
        die "find_metadata_file_for_attrib_val unexpected: found multiple metadata files for ${attrib_name} ${attrib_val} in ${metadata_dir}: ${metadata_files[*]}"
    fi
}

get_simple_xml_attrib_from_metadata() {
    # Retrieve the value of given attribute.
    # WARNING: This function performs very basic parsing:
    #          It only works if the opening and closing
    #          <attrib> </attrib> are on the same line.
    local meta_file=$1
    local attrib=$2
    local val
    val=$(sed -n 's|<'"${attrib}"'>\(.*\)</'"${attrib}"'>|\1|p' "${meta_file}")
    val=$(trim "${val}")
    log_debug "metadata GET ${attrib}: ${val}"
    echo "${val}"
}

get_commit_hashes_from_metadata() {
    # Using a nameref to update the passed-in array,
    # see https://mywiki.wooledge.org/BashProgramming?highlight=%28nameref%29#Functions
    local -n from_metadata_commit_hashes=$1
    local meta_file=$2
    local commit
    while IFS= read -r commit; do
        commit=$(trim "${commit}")
        from_metadata_commit_hashes+=( "${commit}" )
    done < <(sed --quiet 's|<commit[0-9]*>\(.*\)</commit[0-9]*>|\1|p' "${meta_file}")
}

get_usm_state_from_path() {
    local path=$1
    local state
    case "${path}" in
        */available/*)
            state=available
            ;;
        */committed/*)
            state=committed
            ;;
        */deployed/*)
            state=deployed
            ;;
        */deploying/*)
            state=deploying
            ;;
        */removing/*)
            state=removing
            ;;
        */unavailable/*)
            state=unavailable
            ;;
        *)
            log_error "get_usm_state_from_path: parse failure: path='${path}'"
            state=unavailable
            ;;
    esac
    log_debug "get_usm_state_from_path: path=${path}, state: ${state}"
    echo "${state}"
}

ostree_commit_exists() {
    # Does given commit exist in ostree?  i.e. has it been pulled into our repo yet?
    # Note: this only works for locally defined ostree repositories.
    # i.e. it can't get status from a remote server
    local commit_hash=$1
    local ref=${2:-${OSTREE_LOCAL_REF}}
    ostree --repo="${OSTREE_REPO}" log "${ref}" | grep '^commit ' | grep --quiet "${commit_hash}"
}

translate_central_metadata_path() {
    # translate the /opt/software/metadata/... path to /opt/software/tmp/metadata-sync/metadata...
    local metadata_file=$1
    echo "${metadata_file/#"${METADATA_DIR}"/"${METADATA_SYNC_METADATA_DIR}"}"
}

get_metadata_files_unique_to_central() {
    # TODO ISSUE:
    # This gets flagged for removal which it shouldn't - it's just a stage change:
    #
    # [sysadmin@controller-0 ~(keystone_admin)]$ diff -s /opt/software/tmp/metadata-sync/ostree-metadata-commits.*
    # 1d0
    # < /opt/software/metadata/deployed/starlingx-24.09.1-metadata.xml:db313865837f9512b024a2356bd76106140ebcea783f8183e5fcc8d5cd28783b
    # 2a2
    # > /opt/software/metadata/available/starlingx-24.09.1-metadata.xml:db313865837f9512b024a2356bd76106140ebcea783f8183e5fcc8d5cd28783b

    diff "${METADATA_SYNC_DIR}"/ostree-metadata-commits.{central,subcloud} | awk '/^</ {print $2;}' | awk -F ':' '{print $1;}'
}

get_metadata_files_unique_to_subcloud() {
    diff "${METADATA_SYNC_DIR}"/ostree-metadata-commits.{central,subcloud} | awk '/^>/ {print $2;}' | awk -F ':' '{print $1;}'
}

pull_ostree_commit_to_subcloud() {
    # Pulls given commit into subcloud feed repo
    #
    local commit_hash=$1
    if ostree_commit_exists "${commit_hash}"; then
        log_info "ostree commit ${commit_hash}: already exists in ${OSTREE_LOCAL_REF}"
    else
        log_info "Pulling ostree commit from system controller: ${commit_hash}"
        run_cmd ostree --repo="${OSTREE_REPO}" pull --mirror "${OSTREE_REMOTE_REF}" "${OSTREE_BRANCH}@${commit_hash}"
        check_rc_die $? "ostree pull failed"
    fi
}

configure_ostree_repo_for_central_pull() {
    # Ensures the $OSTREE_REPO is configured to pull from the system controller
    [ -n "${DRY_RUN}" ] && return

    # Get system controller management IP (run from system controller):
    local system_controller_ip
    system_controller_ip=$(system addrpool-list | awk '/system-controller-subnet/ { print $14; }')

    local is_https_enabled
    is_https_enabled=$(system show | awk '/https_enabled/ { print $4; }')

    log_info_l "Configuring ostree repo: "\
        "system_controller_ip: ${system_controller_ip}"\
        "is_https_enabled: ${is_https_enabled}"\
        "OSTREE_REPO: ${OSTREE_REPO}"

    if [ "${is_https_enabled}" = True ]; then
        sed -i.bak 's|^url=.*|url=https://'"${system_controller_ip}:${OSTREE_HTTPS_PORT}/iso/${MAJOR_SW_VERSION}/ostree_repo"'|' "${OSTREE_REPO}/config"
        if ! grep --quiet 'tls-permissive=true' "${OSTREE_REPO}/config"; then
            echo "tls-permissive=true" >> "${OSTREE_REPO}/config"
        fi
    else
        sed -i.bak 's|^url=.*|url=http://'"${system_controller_ip}:${OSTREE_HTTP_PORT}/iso/${MAJOR_SW_VERSION}/ostree_repo"'|' "${OSTREE_REPO}/config"
    fi
}

run_cmd() {
    if [ -n "${DRY_RUN}" ]; then
        log_info "DRY_RUN: $*"
    else
        log_info "Running: $*"
        "$@"
    fi
}


################################################################################
#
# Top-level command implementation
#
################################################################################

find_all_ostree_commits_for_release() {
    #
    # Find all ostree commits for the given sw version.
    #
    # Returns a list of: <metadata_file>:<ostree_commit_hash>
    # for the local metadata tree.
    #
    # If the metadata does not specify a commit-id then we use '-'
    # The list is sorted by version, from lowest to highest.
    # This ensures that versions can be processed in the correct numerical order.
    #
    local sw_version=${1:-$SW_VERSION}
    local metadata_dir=${2:-$METADATA_DIR}
    local number_of_commits metadata_file
    for metadata_file in $(find_metadata_files_for_release_sorted "${sw_version}" "${metadata_dir}"); do
        if [ ! -f "${metadata_file}" ]; then
            return
        fi
        number_of_commits=$(get_simple_xml_attrib_from_metadata "${metadata_file}" "number_of_commits")

        # TODO Testing with multiple commits in an update is incomplete
        # remove this when fully tested:
        if [ -n "${number_of_commits}" ] && [ "${number_of_commits}" -gt 1 ]; then
            log_warn "Update has ${number_of_commits} commits: not tested yet"
        fi

        local commit_hashes=()
        get_commit_hashes_from_metadata commit_hashes "${metadata_file}"
        if [ "${#commit_hashes[@]}" -eq 0 ]; then
            echo "${metadata_file}:-"
        else
            if [ "${number_of_commits}" -ne "${#commit_hashes[@]}" ]; then
                # Unexpected, and we should fail here
                die "Update has number_of_commits=${number_of_commits} but only found ${#commit_hashes[@]} commits"
            fi

            # We only need to supply the first commit here.
            # See how the sync_subcloud_metadata algorithm works - it only uses the first commit
            # TODO: do we actually need to supply the commit at all?
            echo "${metadata_file}:${commit_hashes[0]}"
        fi
    done
}

sync_metadata_on_subcloud() {
    #
    # This function peforms metadata / ostree commit synchronizaton on the subcloud
    #
    # The algorithm for syncing the /opt/software/metadata/<STATE>/<RELEASE>-metadata.xml
    # is as follows:
    #
    # For each RELEASE being synchronized from systemController:
    #
    #     COPY metadata.xml from systemController
    #         - this will include the 'ostree-commit-id' and 'committed' ATTRIBUTES from systemController
    #         * this has already been done by ansible
    #
    #     IF RELEASE does NOT EXIST on subcloud
    #         IF 'ostree-commit-id' == NULL
    #             Create it with STATE = unavailable
    #         ELSE
    #             Create it with STATE = available
    #     ELSE   // RELEASE exists on subcloud
    #         IF subcloud STATE == deployed
    #             Leave it as deployed
    #         ELSE IF subcloud STATE == available or unavailable
    #             IF ‘ostree-commit-id’ == NULL
    #                 Set STATE = unavailable
    #             ELSE
    #                 Set STATE = available
    #
    # For each RELEASE on SUBCLOUD but NOT synchronized from systemController
    #     REMOVE RELEASE FROM SUBCLOUD
    #
    local metadata_file=$1
    local central_metadata_file=$2

    # Using a namedref: use different name to avoid name collision
    # See https://mywiki.wooledge.org/BashProgramming?highlight=%28nameref%29#Functions
    local -n sync_subcloud_commit_hashes=$3

    # We already have the metadata file from the system controller
    if [ -z "${central_metadata_file}" ]; then
        # unexpected
        die "no metadata file found for ostree commit(s): ${sync_subcloud_commit_hashes[*]}"
    fi

    # Get current subcloud state from metadata; it may or may not exist
    local id sw_release central_usm_state subcloud_metadata_file
    id=$(get_simple_xml_attrib_from_metadata "${central_metadata_file}" "id")
    sw_release=$(get_simple_xml_attrib_from_metadata "${central_metadata_file}" "sw_release")
    central_usm_state=$(get_usm_state_from_path "$central_metadata_file")
    subcloud_metadata_file=$(find_metadata_file_for_attrib_val "id" "${id}" "${METADATA_DIR}")

    local log_hdr="sync_metadata_on_subcloud: id: ${id}"
    log_info_l "${log_hdr}" "sw_release: ${sw_release}"\
        "commit_hashes: ${sync_subcloud_commit_hashes[*]}"\
        "central_metadata_file: ${central_metadata_file}"\
        "central_usm_state: ${central_usm_state}"\
        "subcloud_metadata_file: ${subcloud_metadata_file}"

    local new_state
    # It is sufficient to check against only one commit hash here - they are all part of the same metadata file
    local commit_hash=${sync_subcloud_commit_hashes[0]}
    if [ -z "${subcloud_metadata_file}" ]; then
        # Not found: RELEASE does NOT EXIST on subcloud
        if ostree_commit_exists "${commit_hash}"; then
            # Create it with STATE = available
            log_debug_l "sync_metadata_on_subcloud: commit exists in local ${OSTREE_LOCAL_REF}"\
                "ref: ${commit_hash}"
            new_state="available"
        else
            # Create it with STATE = unavailable
            new_state="unavailable"
        fi
        log_info "${log_hdr} does not exist on subcloud, setting to ${new_state}"
        run_cmd cp "${central_metadata_file}" "${METADATA_DIR}/${new_state}"
    else
        # RELEASE exists on subcloud
        local subcloud_state
        subcloud_state=$(get_usm_state_from_path "${subcloud_metadata_file}")
        case "${subcloud_state}" in
            'deployed')
                # Leave it as deployed
                log_info "${log_hdr} is in sync (subcloud state: deployed)"
                ;;
            'available'|'unavailable')
                # Not found: RELEASE does NOT EXIST on subcloud
                if ostree_commit_exists "${commit_hash}"; then
                    # Set STATE = available
                    log_debug_l "sync_metadata_on_subcloud: commit exists in local ${OSTREE_LOCAL_REF}"\
                        "ref: ${commit_hash}"
                    new_state=available
                else
                    # Set STATE = unavailable
                    new_state=unavailable
                fi
                log_info "${log_hdr} exists on subcloud, setting subcloud state: ${new_state}"
                run_cmd rm "${subcloud_metadata_file}"
                run_cmd cp "${central_metadata_file}" "${METADATA_DIR}/${new_state}"
                ;;
            'committed')
                log_info "${log_hdr} subcloud state is ${subcloud_state} - ignoring"
                ;;
            'deploying'|'removing')
                log_info "${log_hdr} subcloud state is ${subcloud_state} - transitional, ignoring"
                ;;
            *)
                log_error "${log_hdr} subcloud state is unexpected: ${subcloud_state} - ignoring"
                ;;
        esac
    fi
}

# Context: INVOKED ON SUBCLOUD
sync_subcloud_metadata() {
    #
    # Top-level function to synchronize the subcloud software metadata.
    #
    # When this is invoked, we have the following in place (via ansible):
    #
    #   - "${METADATA_SYNC_DIR}"/ostree-metadata-commits.{central,subcloud}
    #       - these files summarizing the metadata files / ostree commits matching our given release
    #   - "${METADATA_SYNC_DIR}/metadata
    #       - is a direct copy of the system controller /opt/software/medatada directory
    #       - we use this to calculate the new subcloud state of the release
    #         and to pull the missing ostree commits to the subcloud
    #
    # Synchronization is done on a per-major-release basis.
    # For given major release:
    # 1) Get a list of all update metadata files needing to be synchronized
    #    (this is done by comparing (using diff) the central and subcloud file in
    #    "${METADATA_SYNC_DIR}"/ostree-metadata-commits.{central,subcloud}).
    # 2) Ensure any ostree commit(s) for the update are pulled from central
    #    controller if necessary.
    # 3) Synchronize the update metadata file into the proper state-based location
    #    on the subcloud
    #
    local metadata_file commit_hash central_metadata_file

    configure_ostree_repo_for_central_pull

    local commit_hashes=()
    local commit_hash
    # 1) Get list of metadata files requiring sync
    for metadata_file in $(get_metadata_files_unique_to_central); do
        log_info "sync_subcloud_metadata: processing ${metadata_file} from central (sync)"
        central_metadata_file=$(translate_central_metadata_path "${metadata_file}")

        get_commit_hashes_from_metadata commit_hashes "${central_metadata_file}"
        log_debug_l "sync_subcloud_metadata from central: "\
            "metadata_file: ${metadata_file}"\
            "central_metadata_file: ${central_metadata_file}"\
            "commit_hashes: ${commit_hashes[*]}"

        if [ "${#commit_hashes[@]}" -gt 0 ]; then
            for commit_hash in "${commit_hashes[@]}"; do
                # 2) Pull from central controller if necessary

                # TODO(kmacleod): check if previous_commit exists from metadata, fail

                pull_ostree_commit_to_subcloud "${commit_hash}"
            done
            # 3) Synchronize the metadata file
            sync_metadata_on_subcloud "${metadata_file}" "${central_metadata_file}" commit_hashes
        fi
    done
    for metadata_file in $(get_metadata_files_unique_to_subcloud); do
        log_info "sync_subcloud_metadata: processing ${metadata_file} from subcloud (check remove)"
        commit_hashes=()
        get_commit_hashes_from_metadata commit_hashes "${central_metadata_file}"
        log_debug_l "sync_subcloud_metadata from subcloud (check remove): "\
            "metadata_file: ${metadata_file}"\
            "commit_hashes: ${commit_hashes[*]}"
        local removed=
        if [ "${#commit_hashes[@]}" -gt 0 ]; then
            for commit_hash in "${commit_hashes[@]}"; do
                if ! ostree_commit_exists "${commit_hash}"; then
                    log_info "sync_subcloud_metadata from subcloud: commit '${commit_hash}' does not exist, removing '${metadata_file}'"
                    removed=1
                fi
            done
            if [ -n "${removed}" ]; then
                rm "${metadata_file}"
            fi
        fi
        if [ -n "${removed}" ]; then
            log_info_l "sync_subcloud_metadata from subcloud, removed file for non-existing commit(s): "\
                "metadata_file: ${metadata_file}"\
                "commit_hashes: ${commit_hashes[*]}"
        else
            log_info_l "sync_subcloud_metadata from subcloud, commit is in use, not removing: "\
                "metadata_file: ${metadata_file}"\
                "commit_hashes: ${commit_hashes[*]}"
        fi
    done
}

################################################################################
# Main
#
main() {
    local arg_outputfile=
    local -a cmd
    while [ $# -gt 0 ] ; do
        case "${1:-""}" in
            -h|--help)
                help
                ;;
            -D|--debug)
                DEBUG=1
                ;;
            --dry-run)
                DRY_RUN=1
                ;;
            -o|--output)
                shift
                arg_outputfile=$1
                ;;
            -v|--sw-version)
                shift
                SW_VERSION=$1
                export SW_VERSION
                ;;
            get-commits)
                shift
                cmd=('find_all_ostree_commits_for_release')
                break
                ;;
            sync-subcloud)
                if [ "$(id -u)" != 0 ]; then
                    die "you must be root to run sync-commits"
                fi
                shift
                cmd=('sync_subcloud_metadata')
                break
                ;;
            *)
                die "Invalid command '$1' [use -h/--help for help]"
                ;;
        esac
        shift
    done

    initialize_env

    # execute our command
    if [ -z "${arg_outputfile}" ]; then
        "${cmd[@]}"
    else
        [ -f "${arg_outputfile}" ] && rm -f "${arg_outputfile}"
        "${cmd[@]}" | tee "${arg_outputfile}"
    fi
}

if [[ "${BASH_SOURCE[0]}" = "$0" ]]; then
    main "$@"
fi
