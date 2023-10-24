#!/usr/bin/python
#
# Copyright (c) 2019-2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import docker
import json
import keyring
import os
import subprocess
import sys
import time

from random import SystemRandom

MAX_DOWNLOAD_THREAD = 5

LOCAL_REGISTRY_URL = 'registry.local:9001/'
HARD_FAIL_ERRORS = [
    "no basic auth credentials",
    "Forbidden",
    "repository does not exist or may require 'docker login'",
    "no space left on device",
]

DEFAULT_REGISTRIES = {
    'docker.io': 'docker.io',
    'gcr.io': 'gcr.io',
    'k8s.gcr.io': 'k8s.gcr.io',
    'quay.io': 'quay.io',
    'docker.elastic.co': 'docker.elastic.co',
    'ghcr.io': 'ghcr.io',
    'registry.k8s.io': 'registry.k8s.io',
    'icr.io': 'icr.io'
}

REGISTRY_PATTERNS = ['.io', 'docker.elastic.co']

image_outfile = None
registries = json.loads(os.environ['REGISTRIES'])
add_docker_prefix = False


def get_local_registry_auth():
    """Obtain local registry credentials."""
    password = None

    # If, in the off-chance that keyring itself throws an excption, catch
    # and print out.
    try:
        password = keyring.get_password("sysinv", "services")
    except Exception as error:
        print("download_images.py: get_local_registry_auth - Unable to access keyring.")
        print(str(error))

    if not password:
        raise Exception("Local registry password not found.")

    return dict(username="sysinv", password=str(password))


def convert_img_for_local_lookup(img):
    """Convert Image for Local Lookup.

    This function converts the given image reference to the
    format that is suitable for lookup or push to the
    local registry.

    Examples of passed img reference:
      - k8s.gcr.io/kube-proxy:v.16.0
      - privateregistry.io:5000/kube-proxy:v1.16.0

    To push to local registry, local registry url
    'registry.local:9001' needs to be prepended to
    image reference. The registry url of passed img
    may contains a port, if it has a port, we strip
    it out as Docker does not allow the format of
    the image that has port in repositories/namespaces
    i.e.
    Invalid format:
      registry.local:9001/privateregistry.io:5000/kube-proxy:v1.16.0

    Args:
        img: (str) - String imagag format

    """
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

    return LOCAL_REGISTRY_URL + new_img


def handle_docker_exception(ex, err_msg, image):
    """Handle Docker Exception.

    Credentials or disk space related failures result in hard exit. Other
    types of error result in soft exit. The Ansible task that calls this
    script will issue a retry.

    Args:
        ex: (Exception) - This is the caught exception class.
        err_msg: (str) - String error message.
        image (str) - Associated Image string.

    """
    if (isinstance(ex, docker.errors.NotFound) or
            any(err in str(ex) for err in HARD_FAIL_ERRORS)):
        print(" HARD FAIL -" + err_msg + str(ex))
    else:
        # Registry might be temporarily busy/overloaded.  Throttle the retry
        time.sleep(round(SystemRandom().uniform(0.1, 1.0), 3))
        print(err_msg + str(ex))
    return image, False


def get_img_tag_with_registry(pub_img):
    """Obtain image tag.

    This function returns image tag suitable for downloading

    Args:
        pub_img: (str) - Input image string to be
        converted.
    """
    if registries == DEFAULT_REGISTRIES:
        # return as no private registires configured
        return pub_img

    for registry_default, registry_replaced in registries.items():
        if pub_img.startswith(registry_default):
            img_name = pub_img.split(registry_default)[1]
            return registry_replaced + img_name

    return pub_img


def get_image_list_with_auth_info(images):
    """Reformat image list into tuples.

    This function returns a list of image tuples. Each tuple contains
    3 elements:
       a) image tag suitable for prestaging
       b) image tag suitable for downloading
       c) image auth info

    Args:
        images: list - List of image strings.

    """
    images_with_auth = []
    for img in images:
        registry_auth = None
        for registry_default, registry_info in registries.items():
            if img.startswith(registry_default):
                # e.g. k8s.gcr.io/defaultbackend-amd64:1.5
                img_name = img.split(registry_default)[1]
                target_img = registry_info['url'] + img_name
                if 'username' in registry_info:
                    registry_auth = dict(
                        username=registry_info['username'],
                        password=str(registry_info['password']))
                images_with_auth.append(
                    (img, target_img, registry_auth))
                break
            elif img.startswith(registry_info['url']):
                # e.g. myprivate-registry:5000/k8s.gcr.io/defaultbackend-amd64:1.5
                img_name = img.split(registry_info['url'] + '/')[1]
                if registry_default not in img_name:
                    img_name = registry_default + '/' + img_name
                if 'username' in registry_info:
                    registry_auth = dict(
                        username=registry_info['username'],
                        password=str(registry_info['password']))
                images_with_auth.append(
                    (img_name, img, registry_auth))
                break
        else:
            images_with_auth.append((img, img, None))

    return images_with_auth


def download_and_push_an_image(img, auth):
    """Download and push the image.

    Args:
        img: (str) - Image string.
        auth: (dict) - Dictionary of local registry credentials.

    """
    local_img = convert_img_for_local_lookup(img)
    target_img = get_img_tag_with_registry(img)
    err_msg = " Image download failed: %s " % target_img
    client = docker.APIClient()

    try:
        client.inspect_distribution(local_img, auth_config=auth)
        print("Image {} found on local registry".format(target_img))
        try:
            auth_str = '{0}:{1}'.format(auth['username'], auth['password'])
            subprocess.check_call(["crictl", "pull", "--creds", auth_str,
                                   local_img])
        except Exception as e:
            print(err_msg + str(e))
            return target_img, False

        return target_img, True
    except docker.errors.APIError as e:
        print(str(e))
        print("Image {} not found on local registry, attempt to download...".format(target_img))
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
            return handle_docker_exception(e, err_msg, target_img)


# TODO(tngo): Remove this function post StarlingX 9.0
def download_a_local_image(img, auth):
    """Download a local image.

    This function is used to pull the specified image from the local
    registry for image prestage on CentOS.

    Args:
        img: (str) - Image string.
        auth: (dict) - Dictionary of local registry credentials.

    """
    err_msg = " Image retrieval failed: %s " % img
    local_img = LOCAL_REGISTRY_URL + img

    try:
        client = docker.APIClient()
        for line in client.pull(local_img, auth_config=auth, stream=True):
            j = json.loads(line)
            if 'errorDetail' in j:
                raise Exception("Error: " + str(j['errorDetail']))

        client.tag(local_img, img)
        client.remove_image(local_img)
        print("Image retrieval succeeded: %s" % img)
        return img, True
    except Exception as e:
        return handle_docker_exception(e, err_msg, img)


# TODO(tngo): Remove this function post StarlingX 9.0
def download_an_image(img_tuple, local_auth):
    """Download image.

    This function is used to download an image from the public/private
    registry for image prestage on CentOS. It first checks if the image
    is already available in the local registry and pulls it from there.
    Otherwise, it pulls the image from the specified source.

    Args:
        image_tuple: (tuple) - Tuple containing image details.
        local_auth: (dict) - Dictionary of local registry credentials.

    """
    prestage_img, target_img, registry_auth = img_tuple
    local_img = convert_img_for_local_lookup(prestage_img)
    client = docker.APIClient()

    # Leave this is for debugging
    # print("prestage_img: %s, target_img: %s, local_img: %s, auth_info: %s" %
    #       (prestage_img, target_img, local_img, registry_auth))
    try:
        err_msg = " Image download failed: %s " % target_img
        client.inspect_distribution(local_img, auth_config=local_auth)
        print("Image {} found on local registry".format(target_img))
        return download_a_local_image(local_img.split(LOCAL_REGISTRY_URL)[1])
    except docker.errors.APIError as e:
        print(str(e))
        print("Image {} not found on local registry, attempt to download...".format(target_img))
        try:
            client.pull(target_img, auth_config=registry_auth)
            print("Image download succeeded: %s" % target_img)
            if target_img != prestage_img:
                client.tag(target_img, prestage_img)
                client.remove_image(target_img)
            return target_img, True
        except Exception as e:
            return handle_docker_exception(e, err_msg, target_img)


def download_and_push_an_image_for_prestage(img_tuple, local_auth):
    """Download and push image or prestage.

    This function is used to download an image from the public/private
    registry and push it to the local registry for image prestage on
    Debian. It first checks if the image already exists in the local
    registry before pulling it from the specified source.

    Args:
        image_tuple: (tuple) - Tuple containing image details.
        local_auth: (dict) - Dictionary of local registry credentials.

    """
    prestage_img, target_img, registry_auth = img_tuple
    local_img = convert_img_for_local_lookup(prestage_img)
    client = docker.APIClient()

    try:
        err_msg = " Image download failed: %s " % target_img

        client.inspect_distribution(local_img, auth_config=local_auth)
        print("Image {} found on local registry".format(target_img))
        return target_img, True
    except docker.errors.APIError as e:
        print(str(e))
        print("Image {} not found on local registry, attempt to download...".format(target_img))
        try:
            client.pull(target_img, auth_config=registry_auth)
            print("Image download succeeded: %s" % target_img)
            client.tag(target_img, local_img)
            client.push(local_img, auth_config=local_auth)
            print("Image push succeeded: %s" % local_img)
            # Clean up docker cache
            if client.images(target_img):
                client.remove_image(target_img)
            if client.images(local_img):
                client.remove_image(local_img)
            return target_img, True
        except Exception as e:
            return handle_docker_exception(e, err_msg, target_img)


# TODO(tngo): Remove this function post StarlingX 9.0
def generate_image_outfile(images, image_outfile):
    """Generate image output file.

    This function writes the list of images in docker cache that can
    be used for prestaging to the given file.

    Args:
        images: (list) - List of image strings.
        image_outfile: (str) - Path to output file desired.

    """
    with open(image_outfile, 'a') as f:
        for image in images:
            f.write(image + "\n")


def map_function(images, function, local_download=False):
    """This function multi-threads the process of obtaining images.

    Args:
        images: list of image strings.
        function: One of:
            download_and_push_an_image
            download_and_push_an_image_for_prestage
            download_a_local_image
            download_an_image
        local_download: True if this funtion is going to source images
        from a local registry. False otherwise. Defaults to False.

    """
    failed_images = []
    threads = min(MAX_DOWNLOAD_THREAD, len(images))

    # Obtain local credentials once and pass to each job in the map.
    local_auth = get_local_registry_auth()

    # Each argument going into imap has to be a list of the same size, so if there
    # are N images in the list, then local_auth must be repeated N times.
    auth_list = []
    for _ in range(0, len(images)):
        auth_list.append(local_auth)

    if local_download:
        # monkey_patch is called on the eventlet to improve parallelism when
        # images are pulled from the local registry. Doing the same when
        # images are pulled from an external source can have an adverse
        # effect to large subcloud deployment due to too many concurrent image
        # pull requests.
        import eventlet
        eventlet.monkey_patch(os=False)
        from eventlet import greenpool  # noqa: E402
    else:
        # serial download
        from eventlet import greenpool

    pool = greenpool.GreenPool(size=threads)
    for image, success in pool.imap(function, images, auth_list):
        if not success:
            failed_images.append(image)

    return failed_images


if __name__ == '__main__':

    if len(sys.argv) < 2:
        raise Exception("Invalid Input!")

    image_list = sys.argv[1].split(',')
    success_msg = ""
    image_outfile = None
    local_download = False
    prestage_download = False

    start = time.time()

    if os.getenv('ADD_DOCKER_PREFIX') is not None:
        add_docker_prefix = (os.environ['ADD_DOCKER_PREFIX'] == 'True')

    if len(sys.argv) == 2:
        success_msg = "All images downloaded and pushed to the local registry"
        if os.getenv('PRESTAGE_DOWNLOAD') is not None:
            prestage_download = os.environ['PRESTAGE_DOWNLOAD']

        if not prestage_download:
            failed_downloads = map_function(image_list, download_and_push_an_image)
        else:
            # The specified images may also contain the url prefix.
            # Remove them before processing.
            images_with_auth = get_image_list_with_auth_info(image_list)
            image_list = [img_tuple[0] for img_tuple in images_with_auth]
            failed_downloads = map_function(images_with_auth, download_and_push_an_image_for_prestage)
    else:
        # TODO(tngo): Remove the following logic and related functions post StarlingX 9.0

        # Name of the output file to write the list of images to
        image_outfile = sys.argv[2]
        if not os.path.exists(image_outfile):
            raise Exception("Image output file does not exist %s" % image_outfile)

        if os.getenv('LOCAL_DOWNLOAD') is not None:
            local_download = os.environ['LOCAL_DOWNLOAD']

        if local_download == 'True':
            success_msg = "All images retrieved from the local registry"
            failed_downloads = map_function(image_list, download_a_local_image, True)
        else:
            # The specified images may also contain the url prefix.
            # Remove them before processing.
            images_with_auth = get_image_list_with_auth_info(image_list)
            image_list = [img_tuple[0] for img_tuple in images_with_auth]

            success_msg = "All images downloaded successfully"
            failed_downloads = map_function(images_with_auth, download_an_image)

        print("Local download flag: %s" % local_download)

    elapsed_time = time.time() - start
    if len(failed_downloads) > 0:
        raise Exception("Failed to download images %s" % failed_downloads)
    else:
        print("%s in %s seconds" % (success_msg, elapsed_time))
        if image_outfile is not None:
            generate_image_outfile(image_list, image_outfile)
