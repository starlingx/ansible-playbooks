#!/usr/bin/python
#
# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# This script is used to push images that were previously
# imported from local image archive(s) to the local registry.

import docker
import eventlet
import keyring
import os
import subprocess
import sys
import time

eventlet.monkey_patch(os=False)
from eventlet import greenpool  # noqa: E402


MAX_PUSH_THREAD = 5
REGISTRY_PATTERNS = ['.io', 'docker.elastic.co']
add_docker_prefix = False


def get_local_registry_auth():
    password = keyring.get_password("sysinv", "services")
    if not password:
        raise Exception("Local registry password not found.")
    return dict(username="sysinv", password=str(password))


def get_list_of_imported_images():
    client = docker.DockerClient()
    try:
        image_list = client.images.list()
        return [i.tags[0] for i in image_list]
    except Exception as e:
        print(str(e))
        raise


def push_an_image(img):
    # This function is to push an image from docker cache
    # to local registry.
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
    if img.find('/') > 0:
        registry_url = img[:img.find('/')]
        if ':' in registry_url:
            # e.g. registry.central:9001/myimage:latest
            new_img = img.split('/', 1)[1]
        else:
            if not any(pattern in registry_url for pattern in REGISTRY_PATTERNS):
                # e.g. fluxcd/helm-controller
                new_img = "docker.io/" + img if add_docker_prefix else img
            else:
                # e.g. k8s.gcr.io/kube-apiserver:v1.24.4
                new_img = img
    else:
        # e.g. rabbitmq:3.8.11-management
        new_img = "docker.io/" + img if add_docker_prefix else img

    print("Image name used for local lookup is {}".format(new_img))
    target_img = img
    local_img = 'registry.local:9001/' + new_img
    err_msg = " Image push failed: %s" % target_img

    client = docker.APIClient()
    auth = get_local_registry_auth()
    try:
        client.inspect_distribution(local_img, auth_config=auth)
        print("Imported image {} found on local registry".format(target_img))
        # When it gets here, it's a playbook replay
        return target_img, True
    except docker.errors.APIError:
        print("Imported image {} not found in local registry, attempting to push...".format(target_img))
        try:
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
        except docker.errors.APIError as e:
            print(err_msg + str(e))
            return target_img, False


def push_images(images):
    failed_images = []
    threads = min(MAX_PUSH_THREAD, len(images))

    pool = greenpool.GreenPool(size=threads)
    for img, success in pool.imap(push_an_image, images):
        if not success:
            failed_images.append(img)
    return failed_images


if __name__ == '__main__':
    if len(sys.argv) == 2:
        if sys.argv[1] != 'physical':
            MAX_PUSH_THREAD = 1
            print("Subcloud is virtual. MAX_PUSH_THREAD is set to %d" % MAX_PUSH_THREAD)

    if os.getenv('ADD_DOCKER_PREFIX') is not None:
        add_docker_prefix = (os.environ['ADD_DOCKER_PREFIX'] == 'True')

    image_list = get_list_of_imported_images()
    if not image_list:
        raise Exception("No images have been imported. Docker cache is empty.")
    print("List of imported images: {}".format(image_list))
    start = time.time()
    failed_pushes = push_images(image_list)
    elapsed_time = time.time() - start
    if len(failed_pushes) > 0:
        raise Exception("Failed to push images %s" % failed_pushes)
    else:
        print("All imported images pushed to the local "
              "registry in %s seconds" % elapsed_time)
