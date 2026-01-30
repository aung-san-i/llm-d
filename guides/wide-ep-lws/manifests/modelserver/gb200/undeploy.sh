#!/bin/bash
set -e

# GB200 cleanup script
#
# Required environment variables:
# - NAMESPACE: Kubernetes namespace (default: vllm)

NAMESPACE="${NAMESPACE:-vllm}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Removing GB200 model server from namespace: $NAMESPACE"

kubectl delete -k "$SCRIPT_DIR" -n "$NAMESPACE" --ignore-not-found

echo "Cleanup complete."
