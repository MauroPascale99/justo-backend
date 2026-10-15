$ErrorActionPreference = 'Stop'
$root = 'C:\KlavePricing'
$reports = Join-Path $env:USERPROFILE 'Dropbox\GESTION COMERCIAL\REPORTES SPM'
$exports = Join-Path $root 'spm-exportaciones'
$tool = Join-Path $root 'tools\pbi-tools-desktop\pbi-tools.exe'
$python = 'C:\Program Files\Python312\python.exe'
$backend = Join-Path $root 'justo-backend'
$runtime = Join-Path $root 'tools\pbi-runtime'
$logDirectory = Join-Path $root 'logs'
$logFile = Join-Path $logDirectory 'actualizar-cobertura-spm.log'

New-Item -ItemType Directory -Force -Path $exports, "$runtime\tmp", $logDirectory | Out-Null
Start-Transcript -Path $logFile -Append | Out-Null
$env:PBITOOLS_AppDataDir = $runtime; $env:TEMP = "$runtime\tmp"; $env:TMP = "$runtime\tmp"
$names = @('REPORTE CENCO.pbix','REPORTE CARRE.pbix','REPORTE CHANGOMAS.pbix','REPORTE DIA.pbix','REPORTE LA ANONIMA.pbix')
foreach ($name in $names) {
  $out = Join-Path $exports ([IO.Path]::GetFileNameWithoutExtension($name))
  if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $out | Out-Null
  & $tool export-data -pbixPath (Join-Path $reports $name) -outPath $out
  if ($LASTEXITCODE -ne 0) { throw "Falló la exportación de $name" }
}
Push-Location $backend
try { & $python backend\scripts\importar_reportes_spm.py --exportaciones $exports; if ($LASTEXITCODE -ne 0) { throw 'Falló la importación SPM.' } }
finally { Pop-Location }
Stop-Transcript | Out-Null
