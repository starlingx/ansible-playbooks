#!/usr/bin/python3
"""Place a controller's per-controller platform network addresses on its NICs.

These are platform NETWORK addresses (OAM, management, cluster-host, pxeboot)
-- not systemd, maintenance or HA "units". On a simplex system each network
has only a floating address shared by the active controller. Converting the
system to duplex adds a per-controller "unit" address on each network, and
this script puts each unit address onto the same interface that already
carries the matching floating address.

For every unit address passed on the command line it:
  - adds the address as a live IP alias on that interface, and
  - clones the floating address's alias file in /etc/network/interfaces.d
    (reusing the floating address's network id and the next free address id,
    which are database keys) so the address is restored on reboot.

The migrate-sx-to-dx role runs this BEFORE the controller unlock, while
controller-0 is still the active, running controller.

Why a standalone script and not a puppet manifest? Placing these addresses
with puppet means running platform::network::runtime, which calls
apply_network_config.py. Outside of an upgrade that takes the "reconcile"
path: it compares the current and desired interface config and, for any
interface whose config changed, brings that interface DOWN (ip link set
down + ip addr flush) and back UP. During this conversion the controller-0
unit address has just been bound to the management/OAM interface and the
floating address released from it, so that interface counts as changed.
Running the reconcile here -- on the live controller-0, while this very
playbook is still talking to it over management/OAM -- would flush the
floating address the playbook's own connection depends on, in the middle
of the conversion.

So this script does the minimum instead, and only ever ADDS: it runs
"ip addr add" for each unit address and clones the floating address's alias
file in /etc/network/interfaces.d. It never brings an interface down, so it
cannot cut off the running conversion. After the unlock, puppet regenerates
all of these files the normal way; this script only has to carry the
addresses across that single reboot.
"""
import ipaddress
import os
import re
import subprocess
import sys

IFDIR = '/etc/network/interfaces.d'


def held_addresses():
    # Both families, since the unit addresses are IPv6 on an IPv6 system.
    shown = subprocess.check_output(['ip', '-o', 'addr', 'show'],
                                    universal_newlines=True)
    for line in shown.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            try:
                yield fields[1], ipaddress.ip_interface(u'%s' % fields[3])
            except ValueError:
                continue


# The generated alias file carrying this address, if any.
def alias_holding(address):
    for name in sorted(os.listdir(IFDIR)):
        path = os.path.join(IFDIR, name)
        if not os.path.isfile(path):
            continue
        with open(path) as handle:
            body = handle.read()
        if re.search(r'^\s*address\s+%s\s*$' % re.escape(str(address)),
                     body, re.M):
            return path, body
    return None, None


def next_address_id(iface):
    """Return the next address id free among this interface's alias files.

    The address id is a database key, so it is read from the files present.
    """
    highest = 0
    pattern = re.compile(r'^ifcfg-%s:\d+-(\d+)$' % re.escape(iface))
    for name in os.listdir(IFDIR):
        found = pattern.match(name)
        if found:
            highest = max(highest, int(found.group(1)))
    return highest + 1


# Clone the floating address's alias file for the unit address.
def persist(unit, floating, body, path):
    label = os.path.basename(path)[len('ifcfg-'):]
    # Alias files are named "<interface>:<network id>-<address id>". The unit
    # address is on the floating address's network, so its network id is reused.
    iface, _, generated = label.partition(':')
    network_id = generated.partition('-')[0]
    if not network_id.isdigit():
        print('  cannot derive an alias label from %s, not persisting %s'
              % (label, unit))
        return
    new_label = '%s:%s-%d' % (iface, network_id, next_address_id(iface))
    new_path = os.path.join(IFDIR, 'ifcfg-%s' % new_label)
    cloned = re.sub(r'^(\s*iface\s+)\S+', r'\g<1>%s' % new_label,
                    body, count=1, flags=re.M)
    cloned = re.sub(r'^(\s*address\s+)\S+', r'\g<1>%s' % unit,
                    cloned, count=1, flags=re.M)
    with open(new_path, 'w') as handle:
        handle.write(cloned)

    # ifup brings up only what the generated "auto" file lists.
    auto = os.path.join(IFDIR, 'auto')
    with open(auto) as handle:
        listed = handle.read()
    if not re.search(r'(?<![\w:.-])%s(?![\w:.-])' % re.escape(new_label),
                     listed):
        listed = re.sub(r'^(auto .*)$', r'\g<1> %s' % new_label,
                        listed, count=1, flags=re.M)
        with open(auto, 'w') as handle:
            handle.write(listed)
    print('  persisted %s as %s (from %s)' % (unit, new_label, floating))


for raw in sys.argv[1:]:
    if not raw or raw in ('None', ''):
        continue
    unit = ipaddress.ip_address(raw)
    held = None

    # Skip an address already in place, so a retried conversion is a no-op.
    for iface, candidate in held_addresses():
        if candidate.ip == unit:
            print('  %s already on %s' % (unit, iface))
            held = candidate
            break
    if held is not None:
        floating = None
        for _, candidate in held_addresses():
            if candidate.ip != unit and unit in candidate.network:
                floating = candidate.ip
                break
        if floating is None:
            continue
        path, body = alias_holding(floating)
        if path and not alias_holding(unit)[0]:
            persist(unit, floating, body, path)
        continue

    for iface, candidate in held_addresses():
        if unit in candidate.network:
            held = candidate
            try:
                subprocess.check_call(
                    ['ip', 'addr', 'add',
                     '%s/%d' % (unit, candidate.network.prefixlen),
                     'dev', iface])
                print('  placed %s on %s' % (unit, iface))
            except subprocess.CalledProcessError as failure:
                # Still persisted, so the boot brings it up.
                print('  could not place %s on %s: %s'
                      % (unit, iface, failure))
            break
    if held is None:
        print('  no interface holds the subnet of %s' % unit)
        continue

    # and make it survive the unlock reboot
    floating = held.ip
    path, body = alias_holding(floating)
    if not path:
        print('  no alias file holds %s, cannot persist %s'
              % (floating, unit))
    elif alias_holding(unit)[0]:
        print('  %s already persisted' % unit)
    else:
        persist(unit, floating, body, path)
