# Problem: CIS 5.2.4 Compliance Check - Host IPC Sharing Prohibition

## Objective

You need to create tools to analyze Kubernetes resources and detect violations of CIS 5.2.4 security requirement. This requirement states that pods should not share the host's IPC namespace, which means `spec.hostIPC` should not be set to `true`.

## Requirements

Your task is to implement two components:

1. **Resource Fetcher** (`fetch.sh`): A script that collects and processes Kubernetes resource data
2. **Compliance Checker** (`policy.rego`): An OPA policy that analyzes the collected data for violations

## Environment

- **Static Resources Path**: `./static-resources`
- **OPA Version**: 1.0.0
- **Output Format**: Your fetcher should output data to `collected_data.json`

## Compliance Rule

A pod violates CIS 5.2.4 if:
- The pod specification contains `hostIPC: true`

This applies to:
- Standalone pods
- Pods created by deployments (check deployment template specifications)
- Any other workload resources that define pod templates

## Expected Deliverables

1. **`fetch.sh`**: Executable script that:
   - Processes the provided static Kubernetes resources
   - Extracts relevant information for compliance checking
   - Outputs structured data to `collected_data.json`

2. **`policy.rego`**: OPA policy that:
   - Uses package name `check`
   - Defines a `result` boolean field
   - Returns `false` when violations are detected
   - Returns `true` when resources are compliant

## Evaluation Method

Your implementation will be tested using:
```bash
./fetch.sh
cat collected_data.json | opa eval -d policy.rego -I 'data.check.result'
```

The expected result:
- `false` when hostIPC violations exist
- `true` when all resources are compliant

## Success Criteria

- Both files are created and executable/readable
- The implementation correctly identifies pods with `hostIPC: true` as violations
- The implementation correctly identifies clean resources as compliant
- The OPA policy integration works as expected