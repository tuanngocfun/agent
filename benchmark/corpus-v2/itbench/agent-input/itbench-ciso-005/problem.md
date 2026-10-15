# Problem: Kubernetes Secret Access Compliance Check (CIS 5.1.7)

## Objective

Analyze Kubernetes RBAC configurations to detect improper Secret access permissions and implement an automated compliance checking solution using OPA (Open Policy Agent).

## Requirements

You need to create a compliance checking system that can:

1. **Collect RBAC Resources**: Extract and analyze Kubernetes RBAC configurations from provided static resources
2. **Detect Secret Access Violations**: Identify roles that grant excessive permissions to Secret resources  
3. **Report Compliance Status**: Use OPA to evaluate and report whether the configuration violates CIS 5.1.7

### Compliance Rule (CIS 5.1.7)
Roles should not grant excessive permissions to Secret resources:
- **Acceptable**: Read-only access to Secrets (get, list, watch)
- **Violation**: Write access to Secrets (create, update, patch, delete)

## Environment Information

- **Static Resources Path**: `/root/itbench/workdir/outputs/static-resources`
- **OPA Version**: 1.0.0

## Available Resources

You have access to a directory containing Kubernetes resource files organized by resource kind:
- `role/` - Role definitions with various permission configurations
- `rolebinding/` - RoleBinding definitions connecting ServiceAccounts to Roles
- `serviceaccount/` - ServiceAccount definitions
- Additional context resources (pods, deployments, secrets, configmaps)

## Expected Deliverables

Create two files in your working directory:

### 1. fetch.sh
A script that:
- Reads the provided static resources
- Extracts relevant RBAC information 
- Outputs collected data to `collected_data.json`

### 2. policy.rego  
An OPA policy that:
- Uses package name: `package check`
- Defines a `result` boolean field
- Implements logic to detect Secret access violations
- Returns `false` when violations are found, `true` when compliant

## Expected Behavior

Your solution should:
1. **Analyze Roles**: Examine role permissions for Secret resource access
2. **Detect Violations**: Identify roles with write permissions on Secrets
3. **Report Results**: Provide clear compliance status through OPA evaluation

The evaluation will test your solution against both:
- Current configuration (containing violations)
- Modified configuration (with violations removed)

Your implementation should correctly identify violations in the first case and report compliance in the second case.