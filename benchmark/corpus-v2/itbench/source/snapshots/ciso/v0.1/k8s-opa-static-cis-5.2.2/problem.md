# Problem: CIS-5.2.2 Privileged Container Detection

## Objective

Create static analysis tools to detect Kubernetes containers that violate CIS-5.2.2 security requirements by running with privileged access.

## Requirements

### Compliance Rule
- **CIS-5.2.2**: Minimize the admission of privileged containers
- **Violation**: Any container with `securityContext.privileged: true`
- **Compliance**: Containers with `privileged: false` or no `privileged` field (defaults to false)

### Task Details
You need to create two files to analyze pre-collected Kubernetes resources:

1. **fetch.sh** - Resource collection script
   - Process static Kubernetes resources from the provided directory
   - Output collected data in JSON format to `collected_data.json`
   - Focus on resources that can contain container specifications

2. **policy.rego** - OPA Rego policy for compliance evaluation
   - Use package name: `package check`
   - Define `result` field that returns boolean value
   - Return `false` when privileged containers are detected (violation)
   - Return `true` when no privileged containers are found (compliant)

## Available Resources

Static Kubernetes resources are provided in: `./static-resources`

The directory contains various Kubernetes resource types including:
- Pods (direct and generated from deployments)
- Deployments with container specifications  
- Services, ServiceAccounts
- RBAC resources (Roles, RoleBindings)
- ReplicaSets

## Expected Workflow

1. Analyze the provided static resources
2. Create `fetch.sh` to collect relevant data for analysis
3. Create `policy.rego` to evaluate privileged container usage
4. The evaluation will run: `./fetch.sh && cat collected_data.json | opa eval -d policy.rego -I 'data.check.result'`

## Success Criteria

- Both files are created in the current working directory
- Scripts execute without errors
- Policy correctly identifies privileged containers as violations
- Policy correctly identifies compliant configurations
- OPA integration works with your policy structure

## Environment Information

- OPA version 1.0.0 is available
- Static resources path: `./static-resources`
- Working directory: Current directory where you create the files

Focus on creating effective analysis tools that can reliably detect privileged container violations in the provided Kubernetes resources.