# WEKA CSI StorageClass

This directory contains the StorageClass definition for WEKA CSI driver integration.

## Prerequisites

- WEKA CSI driver installed in your cluster
- WEKA cluster configured and accessible
- CSI secret created (default name: `weka-csi-cluster` in namespace `weka`)

For WEKA CSI driver installation instructions, see the [WEKA CSI Plugin documentation](https://docs.weka.io/appendices/weka-csi-plugin).

## Configuration

Update the following parameters in [storage_class.yaml](./storage_class.yaml) to match your WEKA cluster configuration:

- `filesystemName`: Your WEKA filesystem name (default: `default`)
- `mountOptions`: Adjust performance parameters as needed for your workload

## Deployment

Set the storage class name:

```bash
export STORAGE_CLASS=weka-csi-sc
```

Deploy the StorageClass:

```bash
envsubst < ./storage_class.yaml | kubectl apply -f -
```

## Cleanup

To remove the StorageClass:

```bash
kubectl delete -f ./storage_class.yaml
```

**Note:** Ensure no PVCs are using this StorageClass before deletion.
