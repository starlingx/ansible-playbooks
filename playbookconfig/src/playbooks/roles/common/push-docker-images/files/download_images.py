#!/usr/bin/python
#
# Copyright (c) 2019-2021 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from eventlet import greenpool
import docker
import sys
import time
import os
import json
import keyring
import subprocess

MAX_DOWNLOAD_THREAD = 5
MAX_FAILED_DOWNLOADS = 5

num_failed_downloads = 0

DEFAULT_REGISTRIES = {
    'docker.io': 'docker.io',
    'gcr.io': 'gcr.io',
    'k8s.gcr.io': 'k8s.gcr.io',
    'quay.io': 'quay.io',
    'docker.elastic.co': 'docker.elastic.co',
    'ghcr.io': 'ghcr.io'
}

registries = json.loads(os.environ['REGISTRIES'])


def get_local_registry_auth():
    password = keyring.get_password("sysinv", "services")
    if not password:
        raise Exception("Local registry password not found.")
    return dict(username="sysinv", password=str(password))


def download_an_image(img):
    # This function is to pull image from public/private
    # registry and push to local registry.
    #
    # Examples of passed img reference:
    #  - k8s.gcr.io/kube-proxy:v.16.0
    #  - privateregistry.io:5000/kube-proxy:v1.16.0
    #
    # To push to local registry, local registry url
    # 'registry.local:9001' needs to be prepended to
    # image reference. The registry url of passed img
    # may contains a port, if it has a port, we strip
    # it out as Docker does not allow the format of
    # the image that has port in repositories/namespaces
    # i.e.
    # Invalid format:
    #   registry.local:9001/privateregistry.io:5000/kube-proxy:v1.16.0
    registry_url = img[:img.find('/')]
    if ':' in registry_url:
        img_name = img[img.find('/'):]
        new_img = registry_url.split(':')[0] + img_name
    else:
        new_img = img

    target_img = get_img_tag_with_registry(img)
    local_img = 'registry.local:9001/' + new_img
    err_msg = " Image download failed: %s" % target_img

    client = docker.APIClient()
    auth = get_local_registry_auth()
    try:
        client.inspect_distribution(local_img, auth_config=auth)
        print("Image {} found on local registry".format(target_img))

        return target_img, True
    except docker.errors.APIError as e:
        print(str(e))
        print("Image {} not found on local registry, attempt to download...".format(target_img))
        # pull if not already too many failed downloads
        if num_failed_downloads > MAX_FAILED_DOWNLOADS:
            print("Too many failed downloads {}, skipping {}".format(
                  num_failed_downloads, target_img))
            return target_img, False
        try:
            client.pull(target_img)
            print("Image download succeeded: %s" % target_img)
            client.tag(target_img, local_img)
            client.push(local_img, auth_config=auth)
            print("Image push succeeded: %s" % local_img)

            auth_str = '{0}:{1}'.format(auth['username'], auth['password'])
            subprocess.check_call(["crictl", "pull", "--creds", auth_str,
                                   local_img])
            print("Image %s download succeeded by containerd" % target_img)
            # Clean up docker images except for n3000-opae
            # as opae container runs via docker.
            # TODO: run opae with containerd.
            if not ('n3000-opae' in target_img):
                delete_warn = "WARNING: Image %s was not deleted because" \
                              " it was not present into the local docker" \
                              " filesystem"
                if client.images(target_img):
                    client.remove_image(target_img)
                else:
                    print(delete_warn % target_img)
                if client.images(local_img):
                    client.remove_image(local_img)
                else:
                    print(delete_warn % local_img)

            return target_img, True
        except Exception as e:
            print(err_msg + str(e))
            return target_img, False


def get_img_tag_with_registry(pub_img):
    if registries == DEFAULT_REGISTRIES:
        # return as no private registires configured
        return pub_img

    for registry_default, registry_replaced in registries.items():
        if pub_img.startswith(registry_default):
            img_name = pub_img.split(registry_default)[1]
            return registry_replaced + img_name

    return pub_img


def download_images(images):
    global num_failed_downloads
    failed_images = []
    threads = min(MAX_DOWNLOAD_THREAD, len(images))

    pool = greenpool.GreenPool(size=threads)
    for img, success in pool.imap(download_an_image, images):
        if not success:
            failed_images.append(img)
            num_failed_downloads += 1
    return failed_images


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise Exception("Invalid Input!")

    image_list = sys.argv[1].split(',')

    start = time.time()
    failed_downloads = download_images(image_list)
    elapsed_time = time.time() - start

    if len(failed_downloads) > 0:
        raise Exception("Failed to download images %s" % failed_downloads)
    else:
        print("All images downloaded and pushed to the local "
              "registry in %s seconds" % elapsed_time)
