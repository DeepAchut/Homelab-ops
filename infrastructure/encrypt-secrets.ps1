# Unlock Vaultwarden and load age key
$env:BW_SESSION = $(bw unlock --raw)
$env:SOPS_AGE_KEY = $(bw get notes "HOMELAB_SOPS_KEY")

# Helper: strip comments/blank lines and encrypt as dotenv
function Protect-EnvFile {
    param([string]$Path)
    $OutFile = "$Path.enc.yaml"
    $TmpFile = ($Path -replace '\.env$', '.cleaned.env')
    Get-Content $Path |
        Where-Object { $_ -notmatch '^\s*#' -and $_ -notmatch '^\s*$' } |
        Set-Content -Path $TmpFile -NoNewline:$false
    sops --encrypt --input-type dotenv --output-type yaml $TmpFile | Set-Content $OutFile
    Remove-Item $TmpFile
    Write-Host "Encrypted: $OutFile"
}

# Encrypt .env files for each LXC
#Protect-EnvFile -Path "media-ops-lxc/.env"
Protect-EnvFile -Path "home-ops-lxc/.env"

# Reminder: add .env to .gitignore, commit only .env.enc files
Write-Host "`nDone. Commit the .env.enc files, NOT the plaintext .env files."
