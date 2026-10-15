# Problem: Service Account Token Automount Compliance Check

## Objective

Create an automated compliance checking system to detect Kubernetes resources that violate the Service Account token automount security policy. You need to implement both a data collection script and an OPA (Open Policy Agent) policy to identify compliance violations.

## Requirements

### Security Policy
Service Account token automatic mounting should be disabled to reduce attack surface. Resources that explicitly enable token automounting are considered security violations:

- ServiceAccount resources with `automountServiceAccountToken: true`
- Pod resources with `automountServiceAccountToken: true`  
- Deployment resources with `automountServiceAccountToken: true` in their pod template

Resources with `automountServiceAccountToken: false` or explicit disabling are compliant.

### Implementation Requirements

You must create two files:

1. **fetch.sh** - A script that collects and processes Kubernetes resource data
2. **policy.rego** - An OPA policy that analyzes the data and detects violations

### Technical Specifications

**Fetcher Script (fetch.sh)**:
- Process Kubernetes resources from the provided static resource directory
- Output structured data suitable for OPA analysis
- Save results to `collected_data.json`

**OPA Policy (policy.rego)**:
- Use package name: `package check`
- Provide a boolean result field: `result`
- Return `false` when violations are detected
- Return `true` when no violations are found (default compliant state)
- Compatible with OPA version 1.0.0

## Environment Information

- **Static Resources**: ./static-resources
- **Test Namespace**: k8s-opa-static-cis-516

## Resource Structure

The static resources directory contains Kubernetes resources organized by type:
- `serviceaccounts/` - ServiceAccount YAML files
- `pods/` - Pod YAML files  
- `deployments/` - Deployment YAML files
- `replicasets/` - ReplicaSet YAML files
- `services/` - Service YAML files
- `roles/` - Role YAML files
- `rolebindings/` - RoleBinding YAML files

## Expected Execution Flow

The evaluation system will test your implementation using:

```bash
./fetch.sh
cat collected_data.json | opa eval -d policy.rego -I 'data.check.result'
```

## Success Criteria

Your implementation should:
- Correctly identify resources with `automountServiceAccountToken: true` as violations
- Recognize resources with `automountServiceAccountToken: false` as compliant
- Handle different resource types (ServiceAccounts, Pods, Deployments)
- Produce consistent boolean results through the OPA evaluation

Focus on creating robust, accurate compliance checking that can distinguish between secure and insecure Service Account token configurations.