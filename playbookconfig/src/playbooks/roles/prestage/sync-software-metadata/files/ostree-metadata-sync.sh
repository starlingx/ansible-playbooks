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
        # Removes the positional parameters, which are not required in this
        # case by the openrc script. This is to ensure backward compatibility
        # of the source command.
        set -- ""
        source /etc/platform/openrc
    else
        # unit testing
        log_warn "not found: /etc/platform/openrc"
    fi

    export SOFTWARE_DIR=/opt/software
    export METADATA_DIR=${METADATA_DIR:-${SOFTWARE_DIR}/metadata}
    export METADATA_SYNC_DIR=${METADATA_SYNC_DIR:-${SOFTWARE_DIR}/tmp/metadata-sync}
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
    export OSTREE_SYSROOT_REPO="/sysroot/ostree/repo"
    export OSTREE_REMOTE=starlingx
    export OSTREE_BRANCH=starlingx
    export OSTREE_LOCAL_REF="${OSTREE_REMOTE}"
    export OSTREE_REMOTE_REF="${OSTREE_REMOTE}:${OSTREE_BRANCH}"
    export OSTREE_HTTP_PORT=8080
    export OSTREE_HTTPS_PORT=8443

    log_debug_l "SW_VERSION: ${SW_VERSION}"\
        "MAJOR_SW_VERSION: ${MAJOR_SW_VERSION}"\
        "OSTREE_REPO: ${OSTREE_REPO}"\
        "OSTREE_SYSROOT_REPO: ${OSTREE_SYSROOT_REPO}"\
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
    local -A metadata_files_map=()  # key: sw_version, value: metadata file
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
    # Get the value of given XML attribute.
    # We embed Python to parse the XML within script.
    # Params:
    #      $1 = the metadata file path
    #      $2 = the xml attribute to find. can be a path that
    #           specifies the element. For example:
    #               /root/item/subitem1
    # Returns the value of the element if it exists.
    local meta_file=$1
    local attrib=$2
    local val

val=$(python - <<END
import defusedxml.ElementTree as et
import sys

try:
    tree = et.parse('$meta_file')
    root = tree.getroot()
    tag = root.find(".//$attrib")

    print(tag.text)
except:
    sys.exit()
END
)
    log_debug "metadata GET ${attrib}: ${val}"
    echo "${val}"
}

get_commit_hashes_from_metadata() {
    # Retrieves the commit hash of given metadata file
    # Currently the metadata file supports only a single commit.
    # We use the commit1 path to find the hash.
    local -n from_metadata_commit_hashes=$1
    local meta_file=$2
    local commit
    local commit_path="contents/ostree/commit1/commit"

    from_metadata_commit_hashes=$(get_simple_xml_attrib_from_metadata "${meta_file}" "${commit_path}")
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
    # To ensure that the patch is entirely deployed, it must be verified in both repositories.
    # This ensures that when checking whether the commit of a given patch exists on the system,
    # it considers both repos (ostree repo and sysroot)
    local commit_hash=$1
    local ref=${2:-${OSTREE_LOCAL_REF}}
    ostree --repo="${OSTREE_REPO}" log "${ref}" | grep '^commit ' | grep --quiet "${commit_hash}" && \
    ostree --repo="${OSTREE_SYSROOT_REPO}" log "${ref}" | grep '^commit ' | grep --quiet "${commit_hash}"
    return $?
}

translate_central_metadata_path() {
    # translate the /opt/software/metadata/... path to /opt/software/tmp/metadata-sync/metadata...
    local metadata_file=$1
    echo "${metadata_file/#"${METADATA_DIR}"/"${METADATA_SYNC_METADATA_DIR}"}"
}

get_metadata_files_unique_to_central() {
    cat "${METADATA_SYNC_DIR}"/ostree-metadata-commits.central | awk -F ':' '{print $1;}'
}

sync_ostree_repo() {
    # Synchronizes the remote ostree repository (system controller) to the local subcloud.
    local tmp_ostree_sync_file="/tmp/sync-ostree-commits.log"
    run_cmd ostree --repo="${OSTREE_REPO}" pull --mirror --depth=-1 "${OSTREE_REMOTE_REF}" > "${tmp_ostree_sync_file}" 2>&1
    rc=$?
    # To avoid showing all ostree pull progress, which generates a very large output
    # in Ansible, we show only the report line in case of success.
    # In case of error only the last 10 lines.
    if [ "$rc" != "0" ]; then
        tail -10 "${tmp_ostree_sync_file}"
        rm -f "${tmp_ostree_sync_file}"
        check_rc_die $rc "Unable to synchronize ostree repository."
    fi
    tail -1 "${tmp_ostree_sync_file}"
    rm -f "${tmp_ostree_sync_file}"
}

configure_ostree_repo_for_central_pull() {
    # Ensures the $OSTREE_REPO is configured to pull from the system controller
    [ -n "${DRY_RUN}" ] && return

    local remote_ostree_resource="iso/${MAJOR_SW_VERSION}/ostree_repo"
    local system_controller_ip
    local url

    # Get system controller management IP (run from system controller):
    system_controller_ip=$(system addrpool-list --nowrap | awk '/system-controller-subnet/ { print $14; }')

    # Adapts to IPv6 format if necessary
    if [[ $system_controller_ip =~ : && ! $system_controller_ip =~ \[ ]]; then
        system_controller_ip="["$system_controller_ip"]"
    fi

    # We need to know if the system controller has https enabled. We cannot query locally since
    # ostree needs a remote URL to sync.
    # For the N-1 subcloud scenario, it may happen that the subcloud did not have https enabled
    # on the source system controller, then it is necessary to check if the new system controller
    # has https support.
    # The script queries the URL using https initially to check if the system controller has https
    # enabled. If the query fails, assume it is http.
    url="https://${system_controller_ip}:${OSTREE_HTTPS_PORT}/${remote_ostree_resource}"
    response_code=$(curl -k --max-time 20 --connect-timeout 5 -s -o /dev/null -w "%{http_code}" "${url}")
    if [ "$?" != "0" ]; then
        url="http://${system_controller_ip}:${OSTREE_HTTP_PORT}/${remote_ostree_resource}"
    fi

    # Configure remote ostree repo via the CLI.
    ostree remote add --force --no-gpg-verify --set=tls-permissive=true --set=branches="${OSTREE_BRANCH};" "${OSTREE_REMOTE}" "${url}"

    log_info_l "Configuring ostree repo: "\
        "Remote ostree url: ${url}"\
        "Remote ostree response code: ${response_code}" \
        "Local ostree repo: ${OSTREE_REPO}"

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

        release_state=$(get_usm_state_from_path "${metadata_file}")
        if [ "$release_state" = "deployed" ]; then
            number_of_commits=$(get_simple_xml_attrib_from_metadata "${metadata_file}" "number_of_commits")

            local commit_hashes=()
            get_commit_hashes_from_metadata commit_hashes "${metadata_file}"
            if [ "${#commit_hashes[@]}" -gt 0 ]; then
                # We only need to supply the first commit here.
                echo "${metadata_file}:${commit_hashes[0]}"
            fi
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
    #   1 - The extracted commit hash is used to check if the commit exists in the
    #       local feed and sysroot ostree repo. If it exists, the state is set to
    #       "deployed" and the metadata file is copied to the deployed state directory.
    #
    #   2 - If the commit does not exist in the local feed and sysroot ostree repo,
    #       the metadata file is checked in the metadata tmp directory. If it exists and
    #       the state is "deployed", keep it in the same state. Otherwise, set the state
    #       to "available" and copy the metadata file to the available state directory.
    #
    # This mechanism is used to ensure that the metadata files are in the correct
    # state directory, based on the state of the commit hash and the metadata file.
    #
    local metadata_file=$1
    local central_metadata_file=$2

    # Using a namedref: use different name to avoid name collision
    # See https://mywiki.wooledge.org/BashProgramming?highlight=%28nameref%29#Functions
    local -n sync_subcloud_commit_hashes=$3

    # The metadata_tmp_dir is used to store the metadata files temporarily
    # before they are copied to the correct state directory.
    local metadata_tmp_dir=$4

    # We already have the metadata file from the system controller
    if [ -z "${central_metadata_file}" ]; then
        # unexpected
        die "no metadata file found for ostree commit(s): ${sync_subcloud_commit_hashes[*]}"
    fi

    # Get current subcloud state from metadata; it may or may not exist
    local id sw_version central_usm_state subcloud_metadata_file
    id=$(get_simple_xml_attrib_from_metadata "${central_metadata_file}" "id")
    sw_version=$(get_simple_xml_attrib_from_metadata "${central_metadata_file}" "sw_version")
    central_usm_state=$(get_usm_state_from_path "$central_metadata_file")

    local log_hdr="sync_metadata_on_subcloud: id: ${id}"
    log_info_l "${log_hdr}" "sw_version: ${sw_version}"\
        "commit_hashes: ${sync_subcloud_commit_hashes[*]}"\
        "central_metadata_file: ${central_metadata_file}"\
        "central_usm_state: ${central_usm_state}"

    # It is sufficient to check against only one commit hash here - they are all part of the same metadata file
    local commit_hash=${sync_subcloud_commit_hashes[0]}
    # Default to the central metadata file
    local new_metadata_file=${central_metadata_file}
    # Default to deployed state
    local new_state="deployed"
    local reason

    # Check if the commit hash exists in both the local feed and sysroot ostree repo
    if ostree_commit_exists "${commit_hash}"; then
        reason="already exists and is deployed. Keeping it in the same state."
    else
        subcloud_metadata_file=$(find_metadata_file_for_attrib_val "id" "${id}" "${metadata_tmp_dir}")
        # If subcloud_metadata_file is empty, it means that the metadata file
        # does not exist in the metadata tmp directory. In this case, we
        # set the state to available the metadata file from central.
        if [ -z "${subcloud_metadata_file}" ]; then
            new_state="available"
            reason="does not exist. Setting state to available."
        else
            # If the metadata file exists in the metadata tmp directory,
            # we need to check the state. If it is not deployed, we set the state
            # to available. Otherwise, we set the state to deployed.
            subcloud_usm_state=$(get_usm_state_from_path "$subcloud_metadata_file")
            new_metadata_file=$subcloud_metadata_file
            [ "${subcloud_usm_state}" != "${new_state}" ] && new_state="available"
            reason="exists but keeping it in ${new_state} state."
        fi
    fi

    # Ensures that the new state directory exists
    if [ ! -d "${METADATA_DIR}/${new_state}" ]; then
        log_info "Creating ${METADATA_DIR}/${new_state} state directory"
        run_cmd mkdir -p "${METADATA_DIR}/${new_state}"
    fi
    log_info "${log_hdr} ${reason}"
    run_cmd cp "${new_metadata_file}" "${METADATA_DIR}/${new_state}"
}

# Context: INVOKED ON SUBCLOUD
sync_subcloud_metadata() {
    #
    # Top-level function to synchronize the subcloud software metadata.
    #
    # When this is invoked, we have the following in place (via ansible):
    #
    #   - "${METADATA_SYNC_DIR}"/ostree-metadata-commits.central
    #   - "${METADATA_SYNC_DIR}/metadata
    #       - is a direct copy of the system controller /opt/software/medatada directory
    #       - we use this to ensure that the metadata files exist in the subcloud
    #
    # Synchronization is done on a per-major-release basis.
    # For given major release:
    # 1) Synchronize ostree repo
    # 2) Make a copy of the metadata directory to a temporary location
    # 3) Remove the metadata from the specified release to ensure that when synchronized,
    #    it is in the right directory, based on the state.
    # 4) Get a list of all update metadata files needing to be synchronized
    # 5) Synchronize the update metadata file into the proper state-based location
    #    on the subcloud
    # 6) Remove the temporary metadata directory
    #
    local metadata_file commit_hash central_metadata_file metadata_tmp_dir
    local sw_version=${1:-$SW_VERSION}

    # Configure and sync ostree feed repo
    # This will be able to ostree at the same level between System Controller and subcloud.
    configure_ostree_repo_for_central_pull
    sync_ostree_repo

    local commit_hashes=()
    local commit_hash

    # Create a temporary directory to backup the metadata files
    metadata_tmp_dir=$(mktemp --directory ostree-metadata-sync.XXXXX)

    # Copy the metadata directory to a temporary location
    cp -Rf "${METADATA_DIR}" "${metadata_tmp_dir}"

    # Remove current files for specified release
    log_info "Removing directories for release ${sw_version}"
    rm -Rf ${SOFTWARE_DIR}/rel-${sw_version}.*
    find ${METADATA_DIR} -type f -name "*${sw_version}*" | xargs rm -f

    # Get list of metadata files requiring sync
    for metadata_file in $(get_metadata_files_unique_to_central); do
        log_info "sync_subcloud_metadata: processing ${metadata_file} from central (sync)"
        central_metadata_file=$(translate_central_metadata_path "${metadata_file}")

        get_commit_hashes_from_metadata commit_hashes "${central_metadata_file}"
        log_debug_l "sync_subcloud_metadata from central: "\
            "metadata_file: ${metadata_file}"\
            "central_metadata_file: ${central_metadata_file}"\
            "commit_hashes: ${commit_hashes[*]}"

        if [ "${#commit_hashes[@]}" -gt 0 ]; then
            # Synchronize the metadata file
            sync_metadata_on_subcloud "${metadata_file}" "${central_metadata_file}" commit_hashes "${metadata_tmp_dir}"
            commit_hashes=()
        fi
    done
    rm -Rf "${metadata_tmp_dir}"
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
