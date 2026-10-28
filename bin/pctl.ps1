<#
.SYNOPSIS
  pctl - the short command for polyctl on Windows, with nothing installed.

.DESCRIPTION
  Runs polyctl.ps1 beside this script with every argument it was given and exits
  with its exit code (POLYCTL-AFTER-RENAME-2).

.EXAMPLE
  .\pctl.ps1 status
  .\pctl.ps1 board -Root C:\work\project
#>
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE = 0
& (Join-Path $PSScriptRoot 'polyctl.ps1') @args
exit $LASTEXITCODE
