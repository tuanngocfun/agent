# Problem: Detect cluster-admin Role Usage in Kubernetes Resources

## Objective

Create a fetcher script and OPA policy to detect compliance violations related to cluster-admin role usage in Kubernetes namespace-scoped resources.

## Compliance Requirement

**CIS Benchmark 5.1.1**: The cluster-admin role should not be used by any service account.

In this scenario, we define "cluster-admin-like" permissions as:
- Roles with wildcard permissions: `apiGroups: ["*"]`, `resources: ["*"]`, `verbs: ["*"]`
- ServiceAccounts bound to such roles via RoleBindings

## Exception

One service account is used by the benchmark system itself and has wildcard permissions for operational purposes. This account should be **excluded** from violation detection:
- ServiceAccount name: `benchmark-admin-sa`

## Task

You need to create two files:

1. **fetch.sh** - A script that collects and processes Kubernetes resource data from the static resources directory
2. **policy.rego** - An OPA (Open Policy Agent) policy that evaluates the collected data for compliance violations

## Static Resources

Pre-collected Kubernetes resources are available in the directory:
- Path: `./static-resources`
- Namespace: `k8s-opa-static-cis-511`

The directory contains YAML files organized by resource type:
- serviceaccounts/
- roles/
- rolebindings/
- pods/
- deployments/
- replicasets/
- services/
- configmaps/

## Requirements

### fetch.sh Requirements
- Read and process resources from the static resources directory
- Output collected data to a file named `collected_data.json`
- The output should be in JSON format suitable for OPA evaluation

### policy.rego Requirements
- Package name: `package check`
- Define a boolean field named `result`
- Return `false` when violations are detected
- Return `true` when the system is compliant
- Exclude the benchmark system service account (`benchmark-admin-sa`) from violation checks

### Evaluation Method
Your solution will be evaluated using:
```bash
./fetch.sh
cat collected_data.json | opa eval -d policy.rego -I 'data.check.result'
```

## Expected Behavior

- **Initial state** (with violations): The evaluation should return `false`
- **After removing violations**: The evaluation should return `true`
- **Benchmark system account**: Should never be flagged as a violation

## Notes

- OPA version: 1.0.0
- All resources are namespace-scoped (no cluster-level resources)
- Focus on detecting RoleBindings that grant wildcard permissions to ServiceAccounts
- Remember to exclude the benchmark system account from your violation detection logic