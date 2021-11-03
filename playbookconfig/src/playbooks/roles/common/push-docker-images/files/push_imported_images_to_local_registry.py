#!/usr/bin/python
#
# Copyright (c) 2021 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# This script is used to push images that were previously
# imported from local image archive(s) to the local registry.

import eventlet
eventlet.monkey_patch(os=False)
from eventlet import greenpool  # noqa: E402

import docker  # noqa: E402
import time  # noqa: E402
import keyring  # noqa: E402

MAX_PUSH_THREAD = 5


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
            img_name = img[img.find('/'):]
            new_img = registry_url.split(':')[0] + img_name
        else:
            if ".io" not in registry_url:
                # Default to docker.io
                new_img = "docker.io/" + img
            else:
                new_img = img
    else:
        # e.g. rabbitmq:3.8.11-management, default to docker.io
        new_img = "docker.io/" + img

    target_img = img
    local_img = 'registry.local:9001/' + new_img
    err_msg = " Image push failed: %s" % target_img

    client = docker.APIClient()
    auth = get_local_registry_auth()
    try:
        client.inspect_distribution(local_img, auth_config=auth)
        print("Image {} found on local registry".format(target_img))
        # When it gets here, it's a playbook replay
        return target_img, True
    except docker.errors.APIError:
        print("Imported image {} not found in local registry, attempting to push...".format(target_img))
        try:
            client.tag(target_img, local_img)
            client.push(local_img, auth_config=auth)
            print("Image push succeeded: %s" % local_img)
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
    image_list = get_list_of_imported_images()
    print("List of imported images: {}".format(image_list))
    start = time.time()
    failed_pushes = push_images(image_list)
    elapsed_time = time.time() - start
    if len(failed_pushes) > 0:
        raise Exception("Failed to push images %s" % failed_pushes)
    else:
        print("All imported images pushed to the local "
              "registry in %s seconds" % elapsed_time)
