#!/bin/bash
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# This script is used to generate container image bundles and md5 for
# the specified list of images and store them in the specified directory.
#
set -e
set -o pipefail

STAGING_DIR=$1
IMAGE_FILE=$2
OUTPUT_FILE=$STAGING_DIR"/container-image"

# Max bundle size in bytes (uncompressed)
IMAGE_BUNDLE_MAX_SIZE=$3

IMAGE_BUNDLES=""

# Registry Images are loaded into this array
declare -a IMAGE_ARRAY=()

LOG_FILE="/tmp/$(basename $0).log"

function log {
    echo $@ >> ${LOG_FILE}
}

#
# Generate an image bundle.  The bundles are limited to
# IMAGE_BUNDLE_MAX_SIZE.
#
function generate_image_bundle {
    local images=$1
    local bundle_num=$2
    local list_size
    list_size=$(echo ${images}|wc -w)
    local OUTPUT="${OUTPUT_FILE}${bundle_num}.tar.gz"
    log "Generating image bundle ${bundle_num}..."
    log "Image list: ${images}, list size: ${list_size}, \
    bundle: ${bundle_num}, output file: ${OUTPUT}"
    docker save $(echo "${images}") | gzip > ${OUTPUT}
    IMAGE_BUNDLES=${IMAGE_BUNDLES}" "$(basename ${OUTPUT})
}

#
# Build the image bundles; each bundle is limited to
# IMAGE_BUNDLE_MAX_SIZE.
#
#
function build_image_archive {
    mkdir -p ${STAGING_DIR}
    local total_size=0
    local image_list=""
    local bundle_count=1
    local image_bundles=""

    for image in "${IMAGE_ARRAY[@]}"; do
        image_size=$(docker inspect ${image} |grep -w Size|\
        awk '{print substr($2,1,length($2)-1)}')
        new_total_size=$(( $total_size + $image_size ))
        log "Image: ${image}, Size: ${image_size}, \
        Accumulated_size: ${new_total_size}"
        if (( new_total_size > ${IMAGE_BUNDLE_MAX_SIZE} )); then
            log "Cut off image: $image"
            generate_image_bundle "${image_list}" ${bundle_count}

            total_size=0
            new_total_size=0
            image_list=${image}
            bundle_count=$(( $bundle_count + 1 ))
        else
            total_size=${new_total_size}
            image_list=${image_list}" "${image}
        fi
    done
    generate_image_bundle "${image_list}" ${bundle_count}
    echo "Image bundles are stored under ${STAGING_DIR}."
    cd ${STAGING_DIR}; md5sum ${IMAGE_BUNDLES} > container-image.tar.gz.md5
}

#
# Clean the images from the docker cache
#
function remove_images {
    for image in "${IMAGE_ARRAY[@]}"; do
        log "docker image rm ${image}"
        # Don't fail if the image has been removed already
        docker image rm ${image} || true 1>>${LOG_FILE} 2>&1
    done
}

# Load image array
[ -e ${LOG_FILE} ] && rm ${LOG_FILE}
mapfile -t IMAGE_ARRAY < $2
echo "Building archive..."
build_image_archive
echo "Cleaning docker cache..."
remove_images
echo "Completed!"
