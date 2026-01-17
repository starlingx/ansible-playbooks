This is a unit test suite for the ostree-metadata-sync.sh bash script.

Bats is the Bash Automated Testing System. See https://bats-core.readthedocs.io/

Usage:

The tests are executed via the bats docker container. Use the run-bats.sh wrapper script to run the tests via bats inside the docker
container:

    cd $MY_REPO/stx/ansible-playbooks/playbookconfig/src/playbooks/roles/prestage/sync-software-metadata/files/test

    # Run all tests
    ./run-bats.sh

    # Run tests in interactive mode:
    ./run-bats.sh --interactive

See ./run-bats.sh --help for information.


TODO (as suggested by Yuxing):

> I would suggest to try to run the bat test with tox/zuul rather than in another container:
> Something like:

> [testenv:bats]
> basepython = python3
> allowlist_externals =
> bats
> git
> commands = bats <>

> [tox]
> envlist = linters,pep8,bats

Note: this would require ensuring that bats in installed in the tox/zuul environment, which
is probably not trivial, and is likely the bulk of the effort required. 

Once this is dont, then other bash scripts could be tested using bats, which would be a valuable
addition to the test suite.