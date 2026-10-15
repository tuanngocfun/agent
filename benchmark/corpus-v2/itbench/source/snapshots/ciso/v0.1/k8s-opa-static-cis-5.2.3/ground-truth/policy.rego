package check
import rego.v1

# Check for hostPID violations in pods
result := false if {
    some pod in input.pods
    pod.kind == "Pod"
    pod.spec.hostPID == true
}

# Default to compliant (true) when no violations found
default result := true