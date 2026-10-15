package check

# CIS 5.2.5: Minimize the admission of containers which share the host network namespace
# This policy checks for pods that have hostNetwork: true, which violates the security requirement

# Main evaluation rule
# Returns false if violations are found, true if compliant
result := true if {
    not has_host_network_violations
}

result := false if {
    has_host_network_violations
}

# Check if any resources have hostNetwork violations
has_host_network_violations if {
    some i
    input[i].spec.hostNetwork == true
}

# Additional rule to provide detailed violation information
violations contains violation if {
    some i
    resource := input[i]
    resource.spec.hostNetwork == true
    
    violation := {
        "resource_name": resource.metadata.name,
        "resource_kind": resource.kind,
        "namespace": resource.metadata.namespace,
        "violation_type": "hostNetwork_enabled",
        "description": sprintf("Resource %s/%s has hostNetwork: true which violates CIS 5.2.5", [resource.kind, resource.metadata.name])
    }
}

# Provide a summary of the evaluation
summary := {
    "total_resources_checked": count(input),
    "violations_found": count(violations),
    "compliant": result,
    "policy_version": "1.0.0",
    "cis_control": "5.2.5"
}