package check

import rego.v1

# Default to compliant (no violations found)
default result := true

# Check for violations - if any found, result becomes false
result := false if {
    some container in input.containers
    container.securityContext.allowPrivilegeEscalation == true
}

# Helper to identify violating containers (for detailed reporting)
violating_containers contains container if {
    some container in input.containers
    container.securityContext.allowPrivilegeEscalation == true
}