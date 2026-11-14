$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$mosquittoPath = Join-Path $repoRoot "infra\mosquitto"
$passwordFile = Join-Path $mosquittoPath "passwd"

docker version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker is unavailable. Start Docker Desktop and try again."
}

$mountPath = (Resolve-Path -LiteralPath $mosquittoPath).Path
$mount = "type=bind,source=$mountPath,target=/work"
$image = "eclipse-mosquitto:2.0.22"

$existingUsers = @()
if (Test-Path $passwordFile) {
    $existingUsers = @(
        Get-Content -LiteralPath $passwordFile | ForEach-Object {
            $separator = $_.IndexOf(":")
            if ($separator -gt 0) {
                $_.Substring(0, $separator)
            }
        }
    )
}

$users = @("nodered", "replay", "healthcheck")
foreach ($user in $users) {
    if ($existingUsers -contains $user) {
        Write-Output "Keeping existing Mosquitto user: $user"
        continue
    }

    $arguments = @("run", "--rm", "-it", "--user", "0:0", "--mount", $mount, $image)
    if (-not (Test-Path $passwordFile)) {
        $arguments += @("mosquitto_passwd", "-c", "/work/passwd", $user)
    }
    else {
        $arguments += @("mosquitto_passwd", "/work/passwd", $user)
    }
    & docker @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create or update the Mosquitto user '$user'. Existing entries were preserved."
    }

    $existingUsers += $user
}

$permissionCommand = "if chown 1883:1883 /work/passwd 2>/dev/null; then chmod 600 /work/passwd; else chmod 644 /work/passwd; echo 'Warning: Docker could not set the Mosquitto owner on this bind mount; the password hashes are readable by local users.'; fi"
docker run --rm --user 0:0 --mount $mount --entrypoint sh $image -c $permissionCommand
if ($LASTEXITCODE -ne 0) {
    throw "Password entries were created, but the password file permissions could not be prepared."
}

Write-Output "Mosquitto password file is ready with users: $($existingUsers -join ', ')."
Write-Output "Use the same passwords in .env for MQTT_PASS_NODERED, MQTT_PASS_REPLAY, and MQTT_PASS_HEALTHCHECK."
