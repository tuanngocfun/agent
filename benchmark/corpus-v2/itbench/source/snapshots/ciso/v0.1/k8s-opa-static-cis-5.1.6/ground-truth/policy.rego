package check

import rego.v1

# Default result is true (compliant)
default result := true

# Result is false if any violations are found
result := false if {
    count(violations) > 0
}

# Violations collection
violations contains violation if {
    # Check ServiceAccount violations
    serviceaccount := input.serviceaccounts[_]
    serviceaccount.automountServiceAccountToken == true
    violation := {
        "type": "ServiceAccount",
        "name": serviceaccount.name,
        "namespace": serviceaccount.namespace,
        "reason": "automountServiceAccountToken is explicitly set to true"
    }
}

violations contains violation if {
    # Check Pod violations  
    pod := input.pods[_]
    pod.automountServiceAccountToken == true
    violation := {
        "type": "Pod", 
        "name": pod.name,
        "namespace": pod.namespace,
        "reason": "automountServiceAccountToken is explicitly set to true"
    }
}

violations contains violation if {
    # Check Deployment violations
    deployment := input.deployments[_]
    deployment.automountServiceAccountToken == true
    violation := {
        "type": "Deployment",
        "name": deployment.name, 
        "namespace": deployment.namespace,
        "reason": "Pod template has automountServiceAccountToken set to true"
    }
}