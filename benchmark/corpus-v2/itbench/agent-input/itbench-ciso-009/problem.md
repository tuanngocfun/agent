# Problem: Kubernetes Host Network Namespace Compliance Check

## Objective
Implement a compliance checking system to detect violations of CIS Kubernetes Benchmark 5.2.5: "Minimize the admission of containers sharing the host network namespace."

## Background
Host network namespace sharing (`hostNetwork: true`) allows containers to use the host's network stack directly, which poses security risks by bypassing network isolation mechanisms. This configuration should be prohibited in production environments.

## Requirements
Create two files to implement a static compliance checker:

1. **Resource Fetcher (`fetch.sh`)**: A script that analyzes Kubernetes resources and extracts relevant data
2. **Compliance Policy (`policy.rego`)**: An OPA (Open Policy Agent) policy that detects violations

## Compliance Rule
**Violation Condition**: Any pod or pod template that has `spec.hostNetwork: true`

This applies to:
- Standalone Pod resources
- Pod templates within Deployment, ReplicaSet, DaemonSet, StatefulSet, and other workload resources

## Available Resources
You have access to a directory of static Kubernetes resources at: `./static-resources`

The resources are organized by type in subdirectories and represent a snapshot of a Kubernetes namespace.

## Expected Deliverables
1. **`fetch.sh`**: 
   - Must be executable
   - Should analyze the static resources
   - Must output findings to a file named `collected_data.json`

2. **`policy.rego`**:
   - Must use `package check`
   - Must define a `result` boolean field
   - Should return `false` when violations are found, `true` when compliant

## Evaluation Process
Your implementation will be tested by:
1. Running the fetcher: `./fetch.sh`
2. Evaluating with OPA: `cat collected_data.json | opa eval -d policy.rego -I 'data.check.result'`
3. Verifying detection of both violation and compliant states

## Success Criteria
- Correctly identify resources with `hostNetwork: true` as violations
- Correctly identify resources without `hostNetwork` or with `hostNetwork: false` as compliant
- Handle various Kubernetes resource types that may contain pod specifications