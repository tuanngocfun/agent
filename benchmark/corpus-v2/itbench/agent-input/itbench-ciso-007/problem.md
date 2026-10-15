# CIS 5.2.3 - Minimize sharing host process ID namespace

## Objective

Create compliance checking tools to detect violations of CIS 5.2.3, which prohibits sharing the host process ID namespace in Kubernetes pods.

## Requirements

- **Compliance Rule**: Kubernetes pods must NOT use `spec.hostPID: true`
- **Detection Method**: Create tools to identify pods that violate this requirement
- **Output Format**: Provide clear indication of compliance violations

## Environment Information

- **Static Resources Path**: `./static-resources`
- **OPA Version**: 1.0.0

## Task

You need to create two files in your working directory:

### 1. fetch.sh
A shell script that:
- Processes the provided Kubernetes resource files
- Collects relevant data about pod configurations
- Outputs the collected data to `collected_data.json`

### 2. policy.rego
An OPA Rego policy that:
- Uses package name `check`
- Defines a `result` boolean field
- Evaluates whether pods have host PID namespace sharing enabled
- Returns `false` when violations are detected, `true` when compliant

## Expected Workflow

The compliance checking will follow this process:
1. Execute `./fetch.sh` to collect data
2. Pipe data to OPA: `cat collected_data.json | opa eval -d policy.rego -I 'data.check.result'`
3. Evaluate the boolean result

## Available Resources

The static resources directory contains various Kubernetes resources from a test namespace, including:
- Pod configurations (some may have compliance violations)
- Deployments and ReplicaSets
- Services and ServiceAccounts  
- RBAC resources (Roles and RoleBindings)

Examine the pod specifications to identify any instances where `hostPID: true` is configured, as this violates CIS 5.2.3.

## Success Criteria

Your solution should:
- Accurately detect pods with `hostPID: true` as violations
- Correctly identify compliant pods (without hostPID sharing)
- Work reliably with the provided static resource files
- Follow the specified OPA policy structure and naming conventions