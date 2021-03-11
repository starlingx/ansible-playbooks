#!/bin/bash
#
# Copyright (c) 2021 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# As the  'openstack user set' command may fail to
# update the passwords, this script validates the password
# from db, to ensure the password is updated in database.
#

USER_NAME=$1
START_TIME=$2

# Search the password creation timestamp in microsecond
create_time_in_db=$(sudo -u postgres psql -c "select password.created_at_int \
                        from local_user inner join password \
                        on local_user.id=password.local_user_id \
                        where local_user.name='"${USER_NAME}"' \
                        and password.expires_at is null" keystone \
                        |sed -n 3p)

if [[ $((create_time_in_db/1000000)) -lt $START_TIME ]]; then
    echo "Failed to update keystone password."
    exit 1
fi

echo "Updated keystone password."
exit 0
