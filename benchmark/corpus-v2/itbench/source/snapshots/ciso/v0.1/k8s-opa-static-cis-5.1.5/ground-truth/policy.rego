package check

import rego.v1

# Default to compliant (no violations found)
default result := true

# Check for violations - if any found, result becomes false
result := false if {
    some item in input.items
    is_violation(item)
}

# Helper function to identify violations
is_violation(resource) if {
    # Check Pod resources using default service account
    resource.kind == "Pod"
    is_default_service_account(resource.spec)
}

is_violation(resource) if {
    # Check Deployment resources using default service account
    resource.kind == "Deployment"
    is_default_service_account(resource.spec.template.spec)
}

# Check if spec uses default service account
is_default_service_account(spec) if {
    # Explicit default service account assignment
    spec.serviceAccountName == "default"
}

is_default_service_account(spec) if {
    # Missing serviceAccountName field (defaults to "default")
    not spec.serviceAccountName
}