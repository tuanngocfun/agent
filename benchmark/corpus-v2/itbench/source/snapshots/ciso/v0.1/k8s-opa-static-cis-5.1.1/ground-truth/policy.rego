package check

import rego.v1

# Default result is true (compliant)
default result := true

# Check for violations: Direct cluster-admin ClusterRole usage
result := false if {
    some rb in input.rolebindings
    
    # Check if binding references cluster-admin ClusterRole
    rb.roleRef.kind == "ClusterRole"
    rb.roleRef.name == "cluster-admin"
    
    # Check if bound to a ServiceAccount
    some subject in rb.subjects
    subject.kind == "ServiceAccount"
    
    # Exclude benchmark system accounts
    not startswith(subject.name, "benchmark-")
}

# Check for violations: ServiceAccounts with wildcard role permissions
result := false if {
    some rb in input.rolebindings
    some role in input.roles
    
    # Match RoleBinding to Role
    rb.roleRef.kind == "Role"
    rb.roleRef.name == role.metadata.name
    
    # Check if Role has wildcard permissions
    has_wildcard_permissions(role)
    
    # Check if bound to a ServiceAccount
    some subject in rb.subjects
    subject.kind == "ServiceAccount"
    
    # Exclude benchmark system accounts
    not startswith(subject.name, "benchmark-")
}

# Helper function to check for wildcard permissions
has_wildcard_permissions(role) if {
    some rule in role.rules
    "*" in rule.apiGroups
    "*" in rule.resources
    "*" in rule.verbs
}
