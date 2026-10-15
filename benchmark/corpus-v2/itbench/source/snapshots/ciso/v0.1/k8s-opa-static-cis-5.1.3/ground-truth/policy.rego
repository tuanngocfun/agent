package check

import rego.v1

# Default result is true (compliant)
default result := true

# Result is false if any violations are found
result := false if {
    count(violations) > 0
}

# Find all violations (roles with wildcards that are not benchmark-related)
violations contains role if {
    some role in input.roles
    has_wildcard_violation(role)
    not is_benchmark_role(role)
}

# Check if role has wildcard violations
has_wildcard_violation(role) if {
    some rule in role.rules
    "*" in rule.resources
}

has_wildcard_violation(role) if {
    some rule in role.rules
    "*" in rule.verbs
}

has_wildcard_violation(role) if {
    some rule in role.rules
    "*" in rule.apiGroups
}

# Check if role is benchmark-related (should be excluded)
is_benchmark_role(role) if {
    role.metadata.labels.app == "benchmark"
}

is_benchmark_role(role) if {
    role.metadata.labels.component == "benchmark-service"
}

is_benchmark_role(role) if {
    contains(role.metadata.name, "benchmark")
}