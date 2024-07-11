#!/usr/bin/python

#
# Copyright (c) 2021-2022,2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Migrate keystone IDs during rehoming a subcloud
#

import psycopg2
import sys

from psycopg2.extras import RealDictCursor


def get_keystone_local_user_id(user_name, cur):
    """ Get a keystone local user id by name"""

    cur.execute("SELECT user_id FROM local_user WHERE name='%s'" %
                user_name)
    user_id = cur.fetchone()
    if user_id is not None:
        return user_id['user_id']
    else:
        return user_id


def get_keystone_local_user_record(user_name, cur):
    """ Get a keystone local user record by name"""

    cur.execute("SELECT public.user.* FROM public.user INNER JOIN public.local_user \
                    ON public.user.id=public.local_user.user_id \
                    WHERE public.local_user.name='%s'" % user_name)
    user_record = cur.fetchone()
    return user_record


def get_keystone_project_id(project_name, cur):
    """ Get a keystone project id by name"""

    cur.execute("SELECT id FROM public.project WHERE name='%s'" %
                project_name)
    project_id = cur.fetchone()
    if project_id is not None:
        return project_id['id']
    else:
        return project_id


def clean_keystone_non_local_user(user_id, cur):
    """ Clean an existing keystone non local user by user id"""

    try:
        cur.execute("DELETE FROM nonlocal_user WHERE user_id='%s'" % user_id)
        cur.execute("DELETE FROM federated_user WHERE user_id='%s'" % user_id)
        cur.execute("DELETE FROM public.user WHERE id='%s'" % user_id)
    except Exception as ex:
        print("Failed to clean the user id: %s" % user_id)
        raise ex


def update_keystone_user_id(user_name, user_id):
    """ Update the keystone user id"""

    conn = psycopg2.connect("dbname='keystone' user='postgres'")
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            current_user_id = get_keystone_local_user_id(user_name, cur)
            if current_user_id != user_id:
                try:
                    clean_keystone_non_local_user(user_id, cur)
                    local_user_record = get_keystone_local_user_record(user_name, cur)
                    cur.execute("INSERT INTO public.user (id, extra, enabled, created_at, domain_id) \
                                 VALUES ('%s', '%s', '%s', '%s', '%s')" %
                                (user_id, local_user_record['extra'], local_user_record['enabled'],
                                 local_user_record['created_at'], local_user_record['domain_id']))
                    cur.execute("UPDATE public.user_option SET user_id='%s' WHERE user_id='%s'"
                                % (user_id, local_user_record['id']))
                    cur.execute("UPDATE public.assignment SET actor_id='%s' from public.local_user \
                                 WHERE public.assignment.actor_id=public.local_user.user_id AND \
                                 public.local_user.name='%s'" % (user_id, user_name))
                    cur.execute("UPDATE public.system_assignment SET actor_id='%s' from public.local_user \
                                 WHERE public.system_assignment.actor_id=public.local_user.user_id AND \
                                 public.local_user.name='%s'" % (user_id, user_name))
                    cur.execute("UPDATE public.local_user SET user_id='%s' \
                                 WHERE public.local_user.name='%s'" % (user_id, user_name))
                    cur.execute("DELETE FROM public.user WHERE id='%s'" % local_user_record['id'])
                except Exception as ex:
                    print("Failed to update keystone id for user: %s" % user_name)
                    raise ex


def update_barbican_project_external_id(old_id, new_id):
    """ update the project external id in barbican db """

    conn = psycopg2.connect("dbname='barbican' user='postgres'")
    with conn:
        with conn.cursor() as cur:
            try:
                cur.execute("UPDATE public.projects SET external_id='%s' WHERE \
                             external_id='%s'" % (new_id, old_id))
            except Exception as ex:
                raise ex


def update_keystone_project_id(project_name, project_id):
    """ Update a keystone project id by name"""

    conn = psycopg2.connect("dbname='keystone' user='postgres'")
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            current_project_id = get_keystone_project_id(project_name, cur)
            if current_project_id != project_id:
                try:
                    cur.execute("UPDATE public.assignment SET target_id='%s' FROM public.project \
                                 WHERE public.assignment.target_id=public.project.id AND \
                                 public.project.name='%s'" % (project_id, project_name))
                    cur.execute("UPDATE public.project SET id='%s' WHERE \
                                 name='%s'" % (project_id, project_name))
                except Exception as ex:
                    print("Failed to update keystone id for project: %s" % project_name)
                    raise ex

                try:
                    update_barbican_project_external_id(current_project_id, project_id)
                except Exception as ex:
                    print("Failed to update external_id in barbican db for project: %s" % project_name)
                    raise ex


if __name__ == "__main__":

    keystone_name = sys.argv[1]
    keystone_id = sys.argv[2]
    keystone_type = sys.argv[3]

    if keystone_type == 'user':
        update_keystone_user_id(keystone_name, keystone_id)
    elif keystone_type == 'project':
        update_keystone_project_id(keystone_name, keystone_id)
