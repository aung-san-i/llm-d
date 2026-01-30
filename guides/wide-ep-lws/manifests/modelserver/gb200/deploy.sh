#!/bin/bash
set -e

# Simplified GB200 deployment script
#
# Required environment variables:
# - NAMESPACE: Kubernetes namespace (default: vllm)

NAMESPACE="${NAMESPACE:-vllm}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Deploying GB200 model server to namespace: $NAMESPACE"

# Deploy model server
kubectl apply -k "$SCRIPT_DIR" -n "$NAMESPACE"

echo ""
echo "Deployment submitted. Monitor with:"
echo "  kubectl get pods -n $NAMESPACE -l llm-d.ai/model=DeepSeek-V3 -w"
echo ""
echo "View logs with:"
echo "  kubectl logs -n $NAMESPACE -l llm-d.ai/model=DeepSeek-V3 -f"
