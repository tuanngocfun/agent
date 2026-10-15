package check

# Check if any resource has hostIPC enabled - return false if violations found
result := false if {
    some i
    resource := input.resources[i]
    has_host_ipc_violation(resource)
}

# Default to compliant (true) if no violations found
result := true if {
    not any_violations
}

any_violations if {
    some i
    resource := input.resources[i]
    has_host_ipc_violation(resource)
}

# Helper function to detect hostIPC violations
has_host_ipc_violation(resource) if {
    # Check standalone pods
    resource.kind == "Pod"
    resource.spec.hostIPC == true
}

has_host_ipc_violation(resource) if {
    # Check deployment pod templates
    resource.kind == "Deployment"
    resource.spec.template.spec.hostIPC == true
}