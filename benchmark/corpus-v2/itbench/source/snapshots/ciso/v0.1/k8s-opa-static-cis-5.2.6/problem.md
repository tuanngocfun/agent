# Problem: Kubernetes Container Security Compliance Check

## Objective

Create a compliance checking solution to detect containers that violate security best practices by allowing privilege escalation. Specifically, identify containers where `allowPrivilegeEscalation` is set to `true` in their security context.

## Background

Container privilege escalation can pose significant security risks in Kubernetes environments. When `allowPrivilegeEscalation` is set to `true`, containers can gain more privileges than their parent process, potentially leading to security vulnerabilities and unauthorized access.

## Requirements

You need to implement a two-part solution:

1. **Data Collection Tool**: Create a script named `fetch.sh` that extracts relevant container security configuration data from Kubernetes resources
2. **Policy Checker**: Create an OPA (Open Policy Agent) policy file named `policy.rego` that evaluates the collected data for compliance violations

## Environment Information

- **Static Resources Path**: `./static-resources`
- **Output Requirements**: 
  - Fetch script must save data to `collected_data.json`
  - Policy must be compatible with OPA evaluation

## Resource Structure

The static resources directory contains Kubernetes manifests organized by resource type:
- `pods/` - Pod resources
- `deployments/` - Deployment resources  
- `replicasets/` - ReplicaSet resources
- `services/` - Service resources
- `serviceaccounts/` - ServiceAccount resources

## Expected Deliverables

1. **fetch.sh**: A script that processes the static Kubernetes resources and outputs relevant security context data
2. **policy.rego**: An OPA Rego policy that identifies containers with privilege escalation enabled

## Evaluation Flow

Your solution will be evaluated using this process:
1. Execute your fetch script to collect data
2. Use OPA to evaluate your policy against the collected data
3. Verify correct detection of both violations and compliant configurations

## Success Criteria

Your solution should:
- Correctly identify containers with `allowPrivilegeEscalation: true`
- Avoid false positives with compliant configurations
- Follow standard OPA policy patterns
- Process static resource files effectively

Focus on creating a robust solution that can accurately detect the specified security violations while maintaining precision in compliant scenarios.