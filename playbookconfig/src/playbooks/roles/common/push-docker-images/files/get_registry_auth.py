#!/usr/bin/python
#
# Copyright (c) 2019 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import boto3
import re
import sys


def get_aws_ecr_registry_credentials(registry, username, password):
    region = re.compile("[0-9]*.dkr.ecr.(.*).amazonaws.com.*").match(registry)
    if region:
        ecr_region = region.groups()[0]
    else:
        ecr_region = 'us-west-2'

    try:
        client = boto3.client(
            'ecr',
            region_name=ecr_region,
            aws_access_key_id=username,
            aws_secret_access_key=password)

        response = client.get_authorization_token()
        token = response['authorizationData'][0]['authorizationToken']
        username, password = token.decode('base64').split(':')
    except Exception as e:
        raise Exception(
            "Failed to get AWS ECR credentials: %s" % e)

    return dict(username=username, password=password)


if __name__ == '__main__':

    if len(sys.argv) < 4:
        raise Exception("Invalid input!")

    registry_auth = get_aws_ecr_registry_credentials(
        sys.argv[1], sys.argv[2], sys.argv[3])
    print(registry_auth)
