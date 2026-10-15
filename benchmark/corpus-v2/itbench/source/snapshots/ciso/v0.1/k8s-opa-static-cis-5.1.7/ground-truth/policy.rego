package check

import rego.v1

# Default result is true (compliant) unless violations are found
default result := true

# Result is false if any role grants excessive permissions to secrets
result := false if {
    some role in input.roles
    has_secret_violation(role)
}

# Check if a role has violations related to secret access
has_secret_violation(role) if {
    some rule in role.rules
    # Check if the rule applies to secrets resource
    secrets_in_resources(rule.resources)
    # Check if the rule grants write permissions
    has_write_permissions(rule.verbs)
}

# Helper function: check if "secrets" is in resources list
secrets_in_resources(resources) if {
    some resource in resources
    resource == "secrets"
}

# Helper function: check if "secrets" is covered by wildcard
secrets_in_resources(resources) if {
    some resource in resources
    resource == "*"
}

# Helper function: check if rule contains write permissions (beyond get, list, watch)
has_write_permissions(verbs) if {
    some verb in verbs
    verb in ["create", "update", "patch", "delete"]
}

# Helper function: check if wildcard permissions are granted
has_write_permissions(verbs) if {
    some verb in verbs
    verb == "*"
}