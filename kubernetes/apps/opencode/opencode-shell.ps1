#!/usr/bin/env pwsh

# OpenCode Shell Entry Script
# Works on Windows (PowerShell), Linux, and Mac.
# Requires: kubectl, pwsh (PowerShell Core) if on Linux/Mac.

$NAMESPACE = "opencode"
$LABEL = "app=opencode-shell"

Write-Host "Finding OpenCode pod in namespace '$NAMESPACE'..." -ForegroundColor Cyan

$POD = kubectl get pod -n $NAMESPACE -l $LABEL -o name | Select-Object -First 1

if (-not $POD) {
    Write-Error "No pod found with label '$LABEL' in namespace '$NAMESPACE'."
    exit 1
}

Write-Host "Entering shell on $POD..." -ForegroundColor Green
Write-Host "Starting OpenCode in /workspace/Homelab-ops..." -ForegroundColor Gray

# Exec into the pod and chain the commands
kubectl exec -it -n $NAMESPACE $POD -- bash -c "cd /workspace/Homelab-ops && opencode"
