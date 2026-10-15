# Problem: CIS 5.1.3 - Role Wildcard Usage Detection

## Objective

Implement a compliance checking system to detect inappropriate wildcard usage in Kubernetes Roles according to CIS Benchmark 5.1.3. You need to create both a data fetcher and an OPA policy to identify violations.

## Requirements

### CIS 5.1.3 Compliance Rule
Minimize the use of wildcards in Roles. Specifically:
- Roles should not use wildcard (`"*"`) in `resources` field
- Roles should not use wildcard (`"*"`) in `verbs` field  
- Roles should not use wildcard (`"*"`) in `apiGroups` field

### Exception Handling
- Benchmark-related service accounts may legitimately use wildcard permissions
- These should be excluded from violation detection
- Look for roles associated with benchmark operations (may have labels like `app: benchmark`)

### Implementation Requirements

You must create two files in the current directory:

1. **fetch.sh** - Data collection script
   - Extract Role definitions from the provided static resources
   - Output collected data to `collected_data.json` file
   - Process YAML files in the static resources directory

2. **policy.rego** - OPA policy for violation detection
   - Package name must be: `package check`
   - Must define a `result` boolean field
   - Return `false` when violations are detected
   - Return `true` when all Roles are compliant
   - Exclude benchmark-related Roles from violation detection

## Environment Information

- **Static Resources Path**: `./static-resources`
- **Test Namespace**: `k8s-opa-static-cis-513-1772801858`

## Expected Behavior

Your implementation should:
1. Parse Kubernetes Role resources from static YAML files
2. Identify Roles that use wildcard patterns inappropriately
3. Exclude legitimate benchmark Roles from violation detection
4. Return appropriate compliance status via OPA evaluation

## Execution Context

The evaluation system will run your implementation as follows:
```bash
./fetch.sh
cat collected_data.json | opa eval -d policy.rego -I 'data.check.result'
```

The result should be a boolean value indicating compliance status.