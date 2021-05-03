#!/usr/bin/python
#
# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from eventlet import greenpool
import docker
import json
import sys
import time
import keyring
import subprocess

MAX_DOWNLOAD_ATTEMPTS = 3
MAX_DOWNLOAD_THREAD = 5


def get_local_registry_auth():
    password = keyring.get_password("sysinv", "services")
    if not password:
        raise Exception("Local registry password not found.")
    return dict(username="sysinv", password=str(password))


def push_from_filesystem(image):
    # The main purpose of the function is to push the image references
    # starting with 'registry.local:9001' to the local registry as the
    # name suggests.
    # There is no external download step.
    #
    # Valid format:
    #   registry.local:9001/privateregistry.io/kube-proxy:v1.16.0
    #
    # Invalid format:
    #   registry.local:9001/privateregistry.io:5000/kube-proxy:v1.16.0

    err_msg = " Processing failed: %s " % image

    for i in range(MAX_DOWNLOAD_ATTEMPTS):
        try:
            client = docker.APIClient()
            auth = get_local_registry_auth()
            client.push(image, auth_config=auth)
            print("Image push succeeded: %s" % image)
            # due to crictl doesn't support push function, docker client is
            # used to pull and push image to local registry, then crictl
            # download image from local registry.
            # admin password may be changed by openstack client in parallel.
            # So we cannot cache auth info, need refresh it each time.
            auth = get_local_registry_auth()
            auth_str = '{0}:{1}'.format(auth['username'], auth['password'])
            subprocess.check_call(["crictl", "pull", "--creds",
                                   auth_str, image])
            print("Image %s download succeeded by containerd" % image)
            # Clean up docker images except for n3000-opae
            # as opae container runs via docker.
            # TODO: run opae with containerd.
            if not ('n3000-opae' in image):
                client.remove_image(image)
            return image, True
        except docker.errors.APIError as e:
            print(err_msg + str(e))
            if "no basic auth credentials" in str(e):
                return image, False
        except Exception as e:
            print(err_msg + str(e))

        print("Sleep 10s before retry uploading image %s ..." % image)
        time.sleep(10)

    return image, False


def pull_image_from_local_registry(image):
    # This function pulls an image from local registry to local filesystem.
    # Example of passed img reference:
    #  - registry.local:9001:k8s.gcr.io/pause:3.2

    err_msg = " Image download failed: %s " % image

    for i in range(MAX_DOWNLOAD_ATTEMPTS):
        try:
            client = docker.APIClient()
            auth = get_local_registry_auth()
            for line in client.pull(image, auth_config=auth, stream=True):
                j = json.loads(line)
                if 'errorDetail' in j:
                    raise Exception("Error: " + str(j['errorDetail']))

            print("Image download succeeded: %s" % image)
            return image, True
        except docker.errors.NotFound as e:
            print(err_msg + str(e))
            return image, False
        except docker.errors.APIError as e:
            print(err_msg + str(e))
            if "no basic auth credentials" in str(e):
                return image, False
        except Exception as e:
            print(err_msg + str(e))
            if "no space left on device" in str(e):
                return image, False

        print("Sleep 10s before retry downloading image %s ..." % image)
        time.sleep(10)

    return image, False


def map_function(images, function):
    failed_images = []
    threads = min(MAX_DOWNLOAD_THREAD, len(images))

    pool = greenpool.GreenPool(size=threads)
    for image, success in pool.imap(function, images):
        if not success:
            failed_images.append(image)
    return failed_images


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise Exception("Invalid Input!")

    image_list = sys.argv[2].split(',')

    if sys.argv[1] == "push":
        start = time.time()
        failed_uploads = map_function(image_list,
                                      push_from_filesystem)
        elapsed_time = time.time() - start

        if len(failed_uploads) > 0:
            raise Exception("Failed to upload images %s" % failed_uploads)
        else:
            print("All images pushed to the local "
                  "registry in %s seconds" % elapsed_time)
    elif sys.argv[1] == "pull":
        start = time.time()
        failed_downloads = map_function(image_list,
                                        pull_image_from_local_registry)
        elapsed_time = time.time() - start

        if len(failed_downloads) > 0:
            raise Exception("Failed to download images %s" % failed_downloads)
        else:
            print("All images downloaded from the local "
                  "registry in %s seconds" % elapsed_time)
