#!/usr/bin/env bash

# OpenCode Shell Entry Script (Linux/Mac)
# If you have pwsh installed, it calls the .ps1 for consistency.
# Otherwise, it runs the native bash equivalent.

if command -v pwsh >/dev/null 2>&1; then
    exec pwsh "$(dirname "$0")/opencode-shell.ps1" "$@"
fi

NAMESPACE="opencode"
LABEL="app=opencode-shell"

echo "Finding OpenCode pod in namespace '$NAMESPACE'..."
POD=$(kubectl get pod -n "$NAMESPACE" -l "$LABEL" -o name | head -n 1)

if [ -z "$POD" ]; then
    echo "Error: No pod found with label '$LABEL' in namespace '$NAMESPACE'."
    exit 1
fi

echo "Entering shell on $POD..."
kubectl exec -it -n "$NAMESPACE" "$POD" -- bash -c "cd /workspace/Homelab-ops && opencode"
