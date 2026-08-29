# =====================================================================
# Proposal Evaluator — deploy script (Windows / PowerShell)
# ต้องมี: Azure CLI (az), Azure Functions Core Tools (func), Node.js/npm,
#         Static Web Apps CLI (swa) — ติดตั้ง: npm i -g @azure/static-web-apps-cli
#
# ลำดับ: (1) infra Bicep -> (2) grant MI to SQL -> (3) apply schema
#        -> (4) deploy function code -> (5) deploy frontend
#
# หมายเหตุ: script นี้ provision resource ที่มีค่าใช้จ่าย — มี confirmation gate
# =====================================================================
param(
  [string]$ResourceGroup = "rg-proposal-evaluator",
  [string]$Location      = "southeastasia",
  [string]$ParamFile     = "$PSScriptRoot\main.parameters.json"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Proposal Evaluator deployment ===" -ForegroundColor Cyan
Write-Host "Resource group : $ResourceGroup"
Write-Host "Location       : $Location"
Write-Host ""
Write-Host "⚠️  จะสร้าง Azure resource ที่มีค่าใช้จ่ายจริง (OpenAI, SQL, Storage, ฯลฯ)" -ForegroundColor Yellow
$confirm = Read-Host "พิมพ์ 'yes' เพื่อดำเนินการต่อ"
if ($confirm -ne "yes") { Write-Host "ยกเลิก."; exit 1 }

# ---- ตรวจ login ----
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) { Write-Host "ยังไม่ได้ login — รัน 'az login' ก่อน" -ForegroundColor Red; exit 1 }
Write-Host "Subscription: $($account.name)" -ForegroundColor Green

# ---- (1) infra ----
Write-Host "`n[1/5] Provisioning infrastructure (Bicep)..." -ForegroundColor Cyan
az group create --name $ResourceGroup --location $Location | Out-Null
$deploy = az deployment group create `
  --resource-group $ResourceGroup `
  --template-file "$PSScriptRoot\main.bicep" `
  --parameters "@$ParamFile" `
  | ConvertFrom-Json

$funcName   = $deploy.properties.outputs.functionAppName.value
$swaNameOut = $deploy.properties.outputs.staticWebAppName.value
$funcMI     = $deploy.properties.outputs.functionPrincipalId.value
$sqlFqdn    = $deploy.properties.outputs.sqlServerFqdn.value
Write-Host "Function App   : $funcName"
Write-Host "Static Web App : $swaNameOut"
Write-Host "Function MI    : $funcMI"

# ---- (2) grant Function App Managed Identity access to SQL ----
Write-Host "`n[2/5] Grant Function MI -> SQL (ต้องรัน T-SQL ด้วย Entra admin)" -ForegroundColor Cyan
Write-Host "รัน SQL นี้บน DB 'proposal_evaluator' ด้วย Entra admin (Azure Data Studio / sqlcmd -G):" -ForegroundColor Yellow
Write-Host @"
    CREATE USER [$funcName] FROM EXTERNAL PROVIDER;
    ALTER ROLE db_datareader ADD MEMBER [$funcName];
    ALTER ROLE db_datawriter ADD MEMBER [$funcName];
"@ -ForegroundColor Gray
Read-Host "รัน T-SQL ข้างบนเสร็จแล้ว กด Enter เพื่อไปต่อ"

# ---- (3) apply schema ----
Write-Host "`n[3/5] Apply SQL schema" -ForegroundColor Cyan
Write-Host "รัน: sqlcmd -G -S $sqlFqdn -d proposal_evaluator -i `"$PSScriptRoot\..\sql\schema.sql`"" -ForegroundColor Gray
Read-Host "apply schema เสร็จแล้ว กด Enter เพื่อไปต่อ"

# ---- (4) deploy function code ----
Write-Host "`n[4/5] Deploy Function code..." -ForegroundColor Cyan
Push-Location "$PSScriptRoot\..\api"
func azure functionapp publish $funcName --python
Pop-Location

# ---- (5) deploy frontend ----
Write-Host "`n[5/5] Build + deploy frontend..." -ForegroundColor Cyan
Push-Location "$PSScriptRoot\..\frontend"
npm install
npm run build
$swaToken = az staticwebapp secrets list --name $swaNameOut --query "properties.apiKey" -o tsv
swa deploy .\dist --deployment-token $swaToken --env production
Pop-Location

Write-Host "`n=== เสร็จสิ้น ===" -ForegroundColor Green
Write-Host "Function API: https://$funcName.azurewebsites.net/api/health"
