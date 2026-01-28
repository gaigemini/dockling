#!/bin/bash

# Build and Push Script for Docling API
set -e

# Configuration
REGISTRY="registry.gai.co.id"
IMAGE_NAME="gai/docling_api"
VERSION=${1:-latest}
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${VERSION}"

echo "=========================================="
echo "Building Docling API Docker Image"
echo "=========================================="
echo "Registry: ${REGISTRY}"
echo "Image: ${IMAGE_NAME}"
echo "Version: ${VERSION}"
echo "Full Image: ${FULL_IMAGE}"
echo "=========================================="

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    exit 1
fi

# Check if nvidia-docker is available (for GPU support)
if ! docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi > /dev/null 2>&1; then
    echo "⚠️  Warning: NVIDIA Docker runtime not available or GPU not detected"
    echo "   The image will still be built, but GPU features may not work"
fi

# Build the Docker image
echo ""
echo "🔨 Building Docker image..."
docker build -t ${FULL_IMAGE} .

# Tag as latest if version is not latest
if [ "${VERSION}" != "latest" ]; then
    echo ""
    echo "🏷️  Tagging as latest..."
    docker tag ${FULL_IMAGE} ${REGISTRY}/${IMAGE_NAME}:latest
fi

# Login to registry
echo ""
echo "🔐 Logging in to registry..."
echo "Please enter your registry credentials:"
docker login ${REGISTRY}

# Push the image
echo ""
echo "📤 Pushing image to registry..."
docker push ${FULL_IMAGE}

if [ "${VERSION}" != "latest" ]; then
    docker push ${REGISTRY}/${IMAGE_NAME}:latest
fi

echo ""
echo "✅ Successfully built and pushed:"
echo "   - ${FULL_IMAGE}"
if [ "${VERSION}" != "latest" ]; then
    echo "   - ${REGISTRY}/${IMAGE_NAME}:latest"
fi
echo ""
echo "To pull this image:"
echo "   docker pull ${FULL_IMAGE}"
echo ""
echo "To run with GPU support:"
echo "   docker-compose up -d"
echo ""
