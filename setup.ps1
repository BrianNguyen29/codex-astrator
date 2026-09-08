[CmdletBinding()]
param(
    [ValidateSet('global', 'project')]
    [string]$Scope = 'project',
    [Parameter(Mandatory = $true)]
    [string]$Target,
    [string]$Source,
    [switch]$Apply,
    [switch]$ReplaceExisting,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'scripts\install.py'
$argsList = @($script, '--scope', $Scope, '--target', $Target)
if ($Source) { $argsList += @('--source', $Source) }
if ($Apply) { $argsList += '--apply' }
if ($ReplaceExisting) { $argsList += '--replace-existing' }
if ($Uninstall) { $argsList += '--uninstall' }
& python @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
