# Well-lit Path: WEKA GPU Direct Storage

This guide demonstrates how to deploy llm-d with WEKA storage using GPU
Direct Storage (GDS) for high-performance data transfer between GPUs and
storage. It supports both prefill/decode disaggregation and tiered prefix caching.

## Overview

WEKA provides high-performance shared storage with GPU Direct Storage (GDS) support, enabling direct data transfer between GPUs and storage, bypassing CPU and system memory for reduced latency.

This deployment uses a MultiConnector configuration that combines:

1. **NIXL** - For prefill/decode disaggregation (KV transfer between pods over the network)
2. **LMCache** - For tiered prefix caching (KV cache offloading to WEKA storage via GDS)

The WEKA GDS integration includes:

1. **cufile Configuration** - WEKA Operator provisions cufile.json (users can adjust the path via `subPath` if needed)
2. **Volume Mounts** - Mounts cufile.json from WEKA storage to `/etc/cufile.json` into container
3. **Storage Options** - Supports both PersistentVolumeClaim (PVC) and host-path storage configurations
4. **GDS Requirements** - InitContainer loads kernel modules (`nvidia_fs` and `nvidia_peermem`) on host nodes

## Architecture

The manifests use a layered kustomize structure with MultiConnector support:

**Key features:**

- **MultiConnector KV transfer**: Combines NIXL (network-based) and LMCache (storage-based) connectors
- **Prefill/Decode disaggregation**: Separate deployments optimized for each phase via NIXL
- **Tiered prefix caching**: KV cache offloading to WEKA storage via LMCache with GDS
- **Storage organized by type**: Choose `pvc/` or `host/` based on your storage setup

## Prerequisites

- Have the [proper client tools installed on your local system](../../prereq/client-setup/README.md) to use this guide
- **WEKA Operator**:
  - Deploy the WEKA Operator to provision WEKA clients in your cluster
  - Enable CSI in the operator (`csi.installationEnabled: true`) for PVC support
  - WEKA Operator provisions cufile.json configuration for GPU Direct Storage
  - See WEKA documentation for operator deployment instructions
- **GPU Direct Storage (GDS)** requirements:
  - NVIDIA GPUs with GPUDirect Storage capability
  - NVIDIA driver version 450.80.02 or later
  - Kernel modules: `nvidia-fs` and `nvidia_peermem` available on host nodes
  - **RHEL nodes only**: Install `nvidia-gds` package on the host (`dnf install nvidia-gds-12-9`)
- **Pod Configuration** for llm-d workloads (configured via manifests in this guide):
  - **GDS kernel modules**: InitContainer (`enable-nvidia-gds`) loads required kernel modules
  - **cufile mount**: cufile.json from WEKA storage mounted to `/etc/cufile.json`
  - **Storage mount**: WEKA storage mounted for models, cache, and cufile.json (via PVC or hostPath)
- Create Installation Namespace:

  ```bash
  export NAMESPACE=weka
  kubectl create namespace ${NAMESPACE}
  ```

  **Note:** This guide uses `weka` as the namespace, which is hardcoded in the kustomization files. If you want to use a different namespace, update the `namespace:` field in:
  - `./manifests/vllm/overlays/host/kustomization.yaml`
  - `./manifests/vllm/overlays/pvc/kustomization.yaml`
  - `./manifests/gateway/overlays/istio/kustomization.yaml`

- Gateway API implementation deployed (Istio) - see [Gateway control plane setup](../../prereq/gateway-provider/README.md) if needed

## Installation

**Note:** The example deployment manifests use the `RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic` model.

### Deploy vLLM Model Servers

Choose either PVC or host-path storage based on your WEKA setup.

#### Option 1: PVC Storage (Recommended)

##### 1. Configure WEKA StorageClass

Configure and deploy the WEKA CSI StorageClass following the [WEKA backend guide](../storage/manifests/backends/weka/README.md).

##### 2. Create the PVC

Create a PersistentVolumeClaim named `wekafs` with 100Gi storage:

**Note:** Set `STORAGE_CLASS` to match the StorageClass name created in step 1.

```bash
export STORAGE_CLASS=weka-csi-sc
envsubst < ./manifests/vllm/overlays/pvc/pvc.yaml | kubectl apply -f - -n ${NAMESPACE}
```

##### 3. Deploy both decode and prefill with PVC storage

   ```bash
   kubectl apply -k ./manifests/vllm/overlays/pvc
   ```

   This creates:

- ServiceAccount: `weka-vllm`
- Deployment `weka-decode`:
  - 1 replica with 4 GPUs (tensor-parallel), 16 CPUs, 64Gi memory, port 8200
  - InitContainers: `routing-proxy`, `enable-nvidia-gds`
- Deployment `weka-prefill`:
  - 4 replicas (each replica: 1 GPU, 8 CPUs, 64Gi memory), port 8000
  - InitContainers: `enable-nvidia-gds`

#### Option 2: Host-Path Storage

1. If WEKA is mounted at a different location than `/mnt/weka`, update the `path` in `./manifests/vllm/overlays/host/kustomization.yaml`:

   ```yaml
   patches:
     - target:
         kind: Deployment
       patch: |-
         - op: replace
           path: /spec/template/spec/volumes/1
           value:
             name: weka-storage
             hostPath:
               path: /mnt/weka  # Replace with your WEKA mount path
               type: Directory
   ```

2. Deploy both decode and prefill with host-path storage

   ```bash
   kubectl apply -k ./manifests/vllm/overlays/host
   ```

   This creates:
   - ServiceAccount: `weka-vllm`
   - Deployment `weka-decode`: 1 replica with 4 GPUs (tensor-parallel), 16 CPUs, 64Gi memory, port 8200
     - InitContainers: `routing-proxy`, `enable-nvidia-gds`
   - Deployment `weka-prefill`: 4 replicas (each replica: 1 GPU, 8 CPUs, 64Gi memory), port 8000
     - InitContainers: `enable-nvidia-gds`

### Deploy InferencePool

Deploy the inference-scheduler and create the InferencePool CR:

**Note:** You can customize the InferencePool or EndpointPickerConfig by editing `./manifests/inferencepool.values.yaml`.

```bash
helm install weka-vllm \
    -n ${NAMESPACE} \
    -f ./manifests/inferencepool.values.yaml \
    oci://registry.k8s.io/gateway-api-inference-extension/charts/inferencepool --version v1.4.0
```

This creates:

- InferencePool: `weka-vllm`
- ServiceAccount: `weka-vllm-epp`
- Deployment: `weka-vllm-epp` (runs `llm-d-inference-scheduler` image)
- Service: `weka-vllm-epp`
- ConfigMap: `weka-vllm-epp` (contains EndpointPickerConfig)
- DestinationRule: `weka-vllm-epp` (controller traffic for connection limits and TLS for service `weka-vllm-epp`)
- Role: `weka-vllm-epp`
- RoleBinding: `weka-vllm-epp`

### Deploy Gateway

Deploy the Gateway, HTTPRoute, and ConfigMap. The HTTPRoute references the InferencePool backend (`weka-vllm`).

**Note:** By default, the Gateway service type is `LoadBalancer`. If you want to use `ClusterIP` instead, add the following patch to `./manifests/gateway/overlays/istio/kustomization.yaml` in the `patches:` section before deploying:

```yaml
  - target:
      kind: Gateway
      name: llm-d-inference-gateway
    patch: |-
      - op: add
        path: /metadata/annotations
        value:
          networking.istio.io/service-type: ClusterIP
```

Deploy the resources:

```bash
kubectl apply -k ./manifests/gateway/overlays/istio
```

This creates:

- Gateway: `llm-d-inference-gateway`
- HTTPRoute: `llm-d-route`
- ConfigMap: `llm-d-inference-gateway`

Alternatively, you can manually add the annotation after deployment to change to `ClusterIP`:

```bash
kubectl annotate gateway llm-d-inference-gateway \
  -n ${NAMESPACE} \
  networking.istio.io/service-type=ClusterIP
```
