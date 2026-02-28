#!/usr/bin/env bash
# register-adapters.sh — Manage LoRA adapters on a runtime-loaded vLLM server.
#
# Usage:
#   ./register-adapters.sh [OPTIONS]
#
# Options:
#   --load        Load adapters onto all pods (default)
#   --unload      Unload adapters from all pods
#   --list        List loaded models on all pods
#   -n, --namespace NAMESPACE
#                 Kubernetes namespace (default: current kubectl context namespace)
#   -h, --help    Show this help message
#
# Adapters are defined in the ADAPTERS array below — edit it to suit your needs.

set -euo pipefail

# ── Adapters ────────────────────────────────────────────────────────────
# Each entry is "adapter_name=huggingface_repo_id".
ADAPTERS=(
  "topic-control=nvidia/llama-3.1-nemoguard-8b-topic-control"
  "fact-generation=algoprog/fact-generation-llama-3.1-8b-instruct-lora"
  "finance=k0xff/llama-3-8b-sujet-finance-lora"
)

# ── Defaults ────────────────────────────────────────────────────────────
ACTION="load"
NAMESPACE=""
BASE_PORT=8199

# ── Parse flags ─────────────────────────────────────────────────────────
usage() {
  sed -n '2,/^$/s/^# \?//p' "$0"
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --load)     ACTION="load";   shift ;;
    --unload)   ACTION="unload"; shift ;;
    --list)     ACTION="list";   shift ;;
    -n|--namespace)
      NAMESPACE="$2"; shift 2 ;;
    -h|--help)  usage ;;
    -*)
      echo "Unknown option: $1" >&2; exit 1 ;;
    *)
      echo "Unexpected argument: $1" >&2; exit 1 ;;
  esac
done

# Resolve namespace: flag > current context > default
if [[ -z "${NAMESPACE}" ]]; then
  NAMESPACE=$(kubectl config view --minify -o jsonpath='{.contexts[0].context.namespace}' 2>/dev/null)
  NAMESPACE="${NAMESPACE:-default}"
fi

# ── Helpers ─────────────────────────────────────────────────────────────
format_response() {
  local body="$1"
  if echo "${body}" | jq . 2>/dev/null; then
    return
  fi
  # vLLM returns plain text for success — wrap it as JSON for consistency
  jq -n --arg msg "${body}" '{"status": "success", "message": $msg}'
}

wait_for_port_forward() {
  for i in $(seq 1 30); do
    if curl -s -o /dev/null "http://localhost:${LOCAL_PORT}/health" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "  Error: port-forward to ${POD} did not become ready" >&2
  return 1
}

load_adapter() {
  local name="$1" path="$2"
  echo "  Loading adapter: ${name} (${path})"
  local body
  body=$(curl -s -X POST \
    "http://localhost:${LOCAL_PORT}/v1/load_lora_adapter" \
    -H "Content-Type: application/json" \
    -d "{\"lora_name\": \"${name}\", \"lora_path\": \"${path}\"}")
  format_response "${body}"
}

unload_adapter() {
  local name="$1"
  echo "  Unloading adapter: ${name}"
  local body
  body=$(curl -s -X POST \
    "http://localhost:${LOCAL_PORT}/v1/unload_lora_adapter" \
    -H "Content-Type: application/json" \
    -d "{\"lora_name\": \"${name}\"}")
  format_response "${body}"
}

list_models() {
  curl -s "http://localhost:${LOCAL_PORT}/v1/models" \
    | jq '{data: [.data[] | {id, object}]}'
}

# ── Main ────────────────────────────────────────────────────────────────
PODS=$(kubectl get pods -n "${NAMESPACE}" \
  -l llm-d.ai/inference-serving=true \
  -o jsonpath='{.items[*].metadata.name}')

if [[ -z "${PODS}" ]]; then
  echo "Error: no model-server pods found in namespace '${NAMESPACE}'." >&2
  exit 1
fi

case "${ACTION}" in
  load)   VERB="Loading" ;;
  unload) VERB="Unloading" ;;
  list)   VERB="Listing models on" ;;
esac

POD_INDEX=0
for POD in ${PODS}; do
  LOCAL_PORT=$((BASE_PORT + POD_INDEX))
  POD_INDEX=$((POD_INDEX + 1))
  POD_IP=$(kubectl get pod -n "${NAMESPACE}" "${POD}" -o jsonpath='{.status.podIP}')
  echo "═══════════════════════════════════════════════════════════════"
  echo "${VERB} ${POD} (${POD_IP})"
  echo "═══════════════════════════════════════════════════════════════"
  kubectl port-forward -n "${NAMESPACE}" "${POD}" "${LOCAL_PORT}:8000" > /dev/null 2>&1 &
  PF_PID=$!

  if ! wait_for_port_forward; then
    kill "${PF_PID}" 2>/dev/null || true
    wait "${PF_PID}" 2>/dev/null || true
    continue
  fi

  case "${ACTION}" in
    load)
      for entry in "${ADAPTERS[@]}"; do
        load_adapter "${entry%%=*}" "${entry#*=}"
      done
      ;;
    unload)
      for entry in "${ADAPTERS[@]}"; do
        unload_adapter "${entry%%=*}"
      done
      ;;
    list)
      list_models
      ;;
  esac

  kill "${PF_PID}" 2>/dev/null || true
  wait "${PF_PID}" 2>/dev/null || true
  echo ""
done
