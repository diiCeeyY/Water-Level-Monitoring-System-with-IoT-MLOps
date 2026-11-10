param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9]+(?:-[a-z0-9]+)*$')]
    [string]$Group
)

$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
[byte[]]$bytes = @(0, 0, 0)
try {
    $random.GetBytes($bytes)
}
finally {
    $random.Dispose()
}
$suffix = [BitConverter]::ToString($bytes).Replace("-", "").ToLowerInvariant()
Write-Output "wlm/tdia2-$Group-$suffix"
