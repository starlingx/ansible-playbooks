=====================
stx-ansible-playbooks
=====================

StarlingX Bootstrap and Deployment Playbooks

Execution environment
=====================

- Unix like OS (recent Linux based distributions, MacOS, Cygwin)
- Python 2.7

Additional Required Packages
============================
The playbooks in this repo have been verified with the following versions of Ansible
and StarlingX playbooks dependencies:

- sshpass 1.06
- python2-ptyprocess 0.5
- python2-pexpect 4.6
- python2-netaddr 0.7
- ``ansible`` 2.7.5

Supported StarlingX Releases
============================
The playbooks in this repo are compatible with the following StarlingX releases:

- 19.12

Executing StarlingX Playbooks
=============================

Executing Bootstrap Playbook
----------------------------
Please refer to ``StarlingX Deployment Guides``, section **Configuration controller-0**
of the respective system configuration for instructions on how to set up and execute
the bootstrap playbook from another host.

References
==========
.. [1] https://docs.ansible.com/ansible/2.7/installation_guide/index.html
.. [2] https://docs.starlingx.io/deployment_guides/index.html

