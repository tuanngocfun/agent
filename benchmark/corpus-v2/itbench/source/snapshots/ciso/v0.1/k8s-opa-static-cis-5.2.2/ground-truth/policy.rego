package check
import rego.v1

# Main result - returns false if violations found, true if compliant
default result := true

# Check for privileged containers in any resource
result := false if {
    some resource in input.items
    has_privileged_container(resource)
}

# Function to check if a resource has privileged containers
has_privileged_container(resource) if {
    # Direct pod check
    resource.kind == "Pod"
    some container in resource.spec.containers
    container.securityContext.privileged == true
}

has_privileged_container(resource) if {
    # Deployment template check
    resource.kind == "Deployment"
    some container in resource.spec.template.spec.containers
    container.securityContext.privileged == true
}

has_privileged_container(resource) if {
    # ReplicaSet template check
    resource.kind == "ReplicaSet"
    some container in resource.spec.template.spec.containers
    container.securityContext.privileged == true
}

has_privileged_container(resource) if {
    # DaemonSet template check
    resource.kind == "DaemonSet"
    some container in resource.spec.template.spec.containers
    container.securityContext.privileged == true
}

has_privileged_container(resource) if {
    # StatefulSet template check
    resource.kind == "StatefulSet"
    some container in resource.spec.template.spec.containers
    container.securityContext.privileged == true
}

# Optional: Include init containers as well
has_privileged_container(resource) if {
    resource.kind == "Pod"
    some container in resource.spec.initContainers
    container.securityContext.privileged == true
}

has_privileged_container(resource) if {
    resource.kind == "Deployment"
    some container in resource.spec.template.spec.initContainers
    container.securityContext.privileged == true
}