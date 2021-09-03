Name: playbookconfig
Version: 1.0.0
Release: %{tis_patch_ver}%{?_tis_dist}
Summary: Ansible Playbooks for StarlingX Configurations

Group: Development/Tools/Other
License: Apache-2.0
URL: https://opendev.org/starlingx/config
Source0: %{name}-%{version}.tar.gz

Requires: ansible
Requires: python
Requires: python-netaddr
Requires: python-parted
Requires: python2-ptyprocess
Requires: python2-pexpect
Requires: sshpass
Requires: sysinv
Requires: cgts-client

BuildArch: noarch

%description
This package contains playbooks used for configuring StarlingX.

%define local_stx_ansible_dir %{_datadir}/ansible/stx-ansible
%define local_etc_ansible %{_sysconfdir}/ansible
%define debug_package %{nil}

%prep
%setup -q -n %{name}-%{version}/src

%build

%install
make install DESTDIR=%{buildroot}%{local_stx_ansible_dir}
chmod 755 %{buildroot}%{local_stx_ansible_dir}/playbooks/roles/bootstrap/persist-config/files/populate_initial_config.py
chmod 755 %{buildroot}%{local_stx_ansible_dir}/playbooks/roles/bootstrap/prepare-env/files/check_root_disk_size.py
chmod 755 %{buildroot}%{local_stx_ansible_dir}/playbooks/roles/backup/backup-system/files/fm_alarm.py
chmod 755 %{buildroot}%{local_stx_ansible_dir}/playbooks/roles/rehome-subcloud/update-keystone-data/files/migrate_keystone_ids.py


%post
mkdir -p %{local_etc_ansible}
cp %{local_stx_ansible_dir}/playbooks/ansible.cfg %{local_etc_ansible}
cp %{local_stx_ansible_dir}/playbooks/hosts %{local_etc_ansible}
chmod 644 %{local_etc_ansible}/ansible.cfg
chmod 644 %{local_etc_ansible}/hosts

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%doc LICENSE
%dir %{_datadir}/ansible
%dir %{local_stx_ansible_dir}
%{local_stx_ansible_dir}/*
