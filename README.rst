=====================
stx-ansible-playbooks
=====================
StarlingX Bootstrap and Deployment Ansible [1]_ Playbooks

Execution environment
=====================
- Unix like OS (recent Linux based distributions, MacOS, Cygwin)
- Python 3.8 and later

Additional Required Packages
============================
In addition to the pakages listed in `requirements.txt` and `test-requirements.txt`,
the following packages are required to run the playbooks remotely:

- python3-pexpect
- python3-ptyprocess
- sshpass

Supported StarlingX Releases
============================
The playbooks are compatible with StarlingX R8.0 and later.

Executing StarlingX Playbooks
=============================

Bootstrap Playbook
------------------
For instructions on how to set up and execute the bootstrap playbook from
another host, please refer to the StarlingX Documentation [2]_, at
``Installation Guides``, section **Configure controller-0** of the respective
system deployment type.

Developer Notes
===============
This repository is not intended to be developed standalone, but rather as part
of the StarlingX Source System, which is defined by the StarlingX manifest [3]_.

References
==========
.. [1] https://docs.ansible.com/ansible/latest/installation_guide
.. [2] https://docs.starlingx.io
.. [3] https://opendev.org/starlingx/manifest.git
