#!/usr/bin/python
#
# Copyright (c) 2019 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import boto3
from botocore.config import Config
import re
import sys
import os


def set_advanced_config_for_botocore_client():
    """ This function is to set advanced configuration
        for botocore client

    supported configuration:
        proxies(optional): A dictionary of proxy servers
            to use by protocal or endpoint.
            e.g.:
            {'http': 'http://128.224.150.2:3128',
            'https': 'http://128.224.150.2:3129'}

    """
    config = None
    http_proxy = os.environ.get('AWS_HTTP_PROXY', 'undef')
    https_proxy = os.environ.get('AWS_HTTPS_PROXY', 'undef')

    proxies_dict = {}
    if http_proxy != 'undef':
        proxies_dict.update({'http': http_proxy})
    if https_proxy != 'undef':
        proxies_dict.update({'https': https_proxy})

    if proxies_dict:
        config = Config(proxies=proxies_dict)
    return config


def get_aws_ecr_registry_credentials(registry, username, password):
    try:
        region = re.compile("[0-9]*.dkr.ecr.(.*).amazonaws.com.*").match(registry)
        if region:
            ecr_region = region.groups()[0]
        else:
            ecr_region = 'us-west-2'

        config = set_advanced_config_for_botocore_client()
        client = boto3.client(
            'ecr',
            region_name=ecr_region,
            aws_access_key_id=username,
            aws_secret_access_key=password,
            config=config)

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
