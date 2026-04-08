# Unlock Vaultwarden and load age key
$env:BW_SESSION = $(bw unlock --raw)
$env:SOPS_AGE_KEY = $(bw get notes "HOMELAB_SOPS_KEY")

# Encrypt Talos machine configs
$TalosDir = "$PSScriptRoot\talos-config"

function Protect-YamlFile {
    param([string]$Path, [string]$OutDir)
    $FileName = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $OutFile = "$OutDir\$FileName.enc.yaml"
    sops --encrypt $Path | Set-Content $OutFile
    Write-Host "Encrypted: $OutFile"
}

# Encrypt control plane and worker configs (output to talos/ dir)
$OutDir = "$PSScriptRoot\talos"
Protect-YamlFile -Path "$TalosDir\controlplane.yaml" -OutDir $OutDir
Protect-YamlFile -Path "$TalosDir\worker.yaml" -OutDir $OutDir

# Reminder
Write-Host "`nDone. Commit the .enc.yaml files, NOT the plaintext yaml or talosconfig/kubeconfig files."
