#!/bin/bash
#
# Runs bats (Bash Automated Testing System) https://bats-core.readthedocs.io/ via docker
#

# shellcheck disable=SC2155
readonly SCRIPTNAME=$(basename "$0")
# shellcheck disable=SC2155,SC2034
readonly SCRIPTDIR=$(readlink -m "$(dirname "$0")")

cd "${SCRIPTDIR}" || { echo "cd failed"; exit 1; }

# build if necessary
docker images | grep -q 'starlingx/bats' || docker build -t starlingx/bats:latest .

#echo "Running bats: $(docker run -it bats/bats:latest --help)"
case "$1" in
    --help)
        "Usage: ${SCRIPTNAME} ?-i|--interactive?"
        echo ""
        echo "bats --help:"
        docker run -it bats/bats:latest --help
        ;;
    -i|--interactive|--bash|bash|shell)
        echo "Running in interactive mode. Run tests in 'test' via: bats test"
        docker run -it --rm -v "${PWD}/..:/code" --entrypoint bash starlingx/bats:latest
        ;;
    *)
        docker run -it --rm -v "${PWD}/..:/code" starlingx/bats:latest --verbose-run test/ostree-metadata-sync.bats
        ;;
esac
