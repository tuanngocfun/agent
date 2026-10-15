# CIS 5.1.5: Default Service Account Prohibition Detection

## Objective

Implement an automated compliance checking system to detect violations of CIS Kubernetes Benchmark 5.1.5, which prohibits the use of default service accounts in Pod and Deployment specifications.

## Requirements

Create two components to analyze Kubernetes resources and detect compliance violations:

1. **Resource Fetcher (fetch.sh):** A script that collects and processes Kubernetes resource data
2. **Compliance Checker (policy.rego):** An OPA (Open Policy Agent) policy that detects violations

## Compliance Rule: Default Service Account Prohibition

**Violation conditions:**
- Any Pod with `spec.serviceAccountName` set to "default"
- Any Pod with missing or unspecified `spec.serviceAccountName` field (defaults to "default")
- Any Deployment template with `spec.template.spec.serviceAccountName` set to "default"
- Any Deployment template with missing `spec.template.spec.serviceAccountName` field

**Compliant configurations:**
- Pods/Deployments that explicitly specify a custom service account name (not "default")

## Environment Information

- **Static Resources Directory:** `./static-resources`
- **Test Namespace:** `cis-515-opa-test-1772803717`

## Implementation Requirements

### 1. Resource Fetcher (fetch.sh)
- Read Kubernetes resource files from the static resources directory
- Process relevant resource types (Pods, Deployments, etc.)
- Output data in JSON format suitable for OPA policy evaluation
- Save output to `collected_data.json` file

### 2. Compliance Policy (policy.rego)
- Use OPA Rego language for policy definition
- Package name must be `check`
- Define a `result` field that returns:
  - `false` when violations are detected
  - `true` when all resources are compliant
- Analyze the collected resource data to identify default service account usage

## Expected Workflow

```bash
# 1. Execute the fetcher to collect resource data
./fetch.sh

# 2. Evaluate compliance using OPA with the policy
opa eval -d policy.rego -I 'data.check.result' < collected_data.json
```

## Deliverables

Create the following files in your working directory:
1. `fetch.sh` - Resource collection script
2. `policy.rego` - OPA compliance policy

Both files should work together to accurately detect default service account violations according to CIS 5.1.5 requirements.