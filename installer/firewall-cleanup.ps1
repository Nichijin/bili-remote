param([Parameter(Mandatory=$true)][string]$Program, [switch]$Query)
$ErrorActionPreference = 'Stop'
try {
    $taskProgramPath = [IO.Path]::GetFullPath($Program)
    if ([IO.Path]::GetFileName($taskProgramPath) -ne 'BiliRemote-Desktop.exe') { exit 2 }
    $taskPolicy = New-Object -ComObject HNetCfg.FwPolicy2
    $taskRules = @($taskPolicy.Rules | Where-Object {
        $taskCandidate = [Environment]::ExpandEnvironmentVariables($_.ApplicationName)
        $taskCandidate -and [string]::Equals($taskCandidate, $taskProgramPath, [StringComparison]::OrdinalIgnoreCase)
    })
    if ($Query) { if ($taskRules.Count) { exit 10 } else { exit 0 } }
    foreach ($taskRule in $taskRules) { $taskPolicy.Rules.Remove($taskRule.Name) }
    exit 0
} catch { exit 2 }
