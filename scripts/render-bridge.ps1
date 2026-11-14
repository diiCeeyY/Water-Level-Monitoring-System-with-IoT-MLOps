$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot ".env"
$templatePath = Join-Path $repoRoot "infra\mosquitto\conf.d\bridge.conf.template"
$outputPath = Join-Path $repoRoot "infra\mosquitto\conf.d\bridge.conf"

if (-not (Test-Path $envPath)) {
    throw "Missing .env. Copy .env.example to .env and configure MQTT values first."
}

$values = @{}
foreach ($line in Get-Content -LiteralPath $envPath) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#")) {
        continue
    }

    $separator = $trimmed.IndexOf("=")
    if ($separator -gt 0) {
        $key = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim().Trim('"').Trim("'")
        $values[$key] = $value
    }
}

foreach ($name in @("MQTT_TOPIC_PREFIX", "MQTT_PUBLIC_HOST", "MQTT_PUBLIC_PORT", "MQTT_BRIDGE_CLIENT_ID")) {
    if (-not $values.ContainsKey($name) -or -not $values[$name]) {
        throw "Missing $name in .env."
    }
}

if ($values["MQTT_TOPIC_PREFIX"] -notmatch '^wlm/tdia2-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{6}$') {
    throw "MQTT_TOPIC_PREFIX must be a unique wlm/tdia2-<group>-<6 lowercase hex> prefix."
}
if ($values["MQTT_BRIDGE_CLIENT_ID"] -match "CHANGEME") {
    throw "Replace the MQTT_BRIDGE_CLIENT_ID placeholder in .env with a unique client ID."
}
if ($values["MQTT_PUBLIC_PORT"] -notmatch '^\d{1,5}$' -or [int]$values["MQTT_PUBLIC_PORT"] -gt 65535) {
    throw "MQTT_PUBLIC_PORT must be a valid TCP port."
}

$rendered = Get-Content -LiteralPath $templatePath -Raw
foreach ($name in @("MQTT_PUBLIC_HOST", "MQTT_PUBLIC_PORT", "MQTT_BRIDGE_CLIENT_ID", "MQTT_TOPIC_PREFIX")) {
    $rendered = $rendered.Replace("@$name@", $values[$name])
}

$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($outputPath, $rendered, $utf8WithoutBom)
Write-Output "Rendered infra\mosquitto\conf.d\bridge.conf from .env."
