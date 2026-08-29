// =====================================================================
// Proposal Evaluator — Azure infrastructure (Bicep)
// Provisions: Storage, App Insights, Function App (Consumption/Python),
//             Azure OpenAI + gpt-4o deployment, Document Intelligence,
//             Azure SQL (Entra-only auth), Static Web App.
//
// Auth model (ตรงกับโค้ด api/):
//   - OpenAI / DocIntel / Blob  -> key-based ผ่าน Function App appSettings
//   - Azure SQL                 -> Function App Managed Identity (ActiveDirectoryMsi)
// Hardening (ทำภายหลัง): ย้าย key ทั้งหมดไป Key Vault + reference
// =====================================================================

@description('Base name (lowercase, no spaces) — prefix ของทุก resource')
@minLength(3)
@maxLength(11)
param baseName string = 'proposalapp'

@description('Location ของ resource ส่วนใหญ่')
param location string = resourceGroup().location

@description('Location ของ Azure OpenAI (บาง region เท่านั้นที่มี gpt-4o)')
param openaiLocation string = 'eastus'

@description('Location ของ Static Web App — รองรับเฉพาะ centralus/eastus2/westus2/westeurope/eastasia')
param swaLocation string = 'eastasia'

@description('Entra admin object id (Azure AD) สำหรับ SQL Server admin')
param sqlAdminObjectId string

@description('Entra admin login name (เช่น user@tenant.onmicrosoft.com)')
param sqlAdminLogin string

@description('OpenAI model name — gpt-4o เลิก deploy ใหม่แล้ว (ก.ค.2026); default gpt-5.5 (GA)')
param modelName string = 'gpt-5.5'

@description('OpenAI model version')
param modelVersion string = '2026-04-24'

@description('Deployment SKU — gpt-5.x ใช้ GlobalStandard')
param modelSku string = 'GlobalStandard'

@description('capacity (K TPM) — 50 กัน 429 (1 call ~8K + retry)')
param modelCapacity int = 50

// suffix กันชื่อชนกันทั่วโลก (storage/openai/sql/func/swa ต้อง globally unique)
var suffix = substring(uniqueString(resourceGroup().id), 0, 5)
var storageName = toLower('${baseName}${suffix}stg')
var funcName = '${baseName}-${suffix}-func'
var planName = '${baseName}-${suffix}-plan'
var aiName = '${baseName}-${suffix}-ai'
var openaiName = '${baseName}-${suffix}-openai'
var docintelName = '${baseName}-${suffix}-docintel'
var sqlServerName = '${baseName}-${suffix}-sql'
var sqlDbName = 'proposal_evaluator'
var swaName = '${baseName}-${suffix}-web'
var contentShare = toLower('${funcName}-content')

// ---------- Storage (Functions runtime + proposals container) ----------
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storage
  name: 'default'
}

resource proposalsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'proposals'
  properties: { publicAccess: 'None' }
}

// ---------- Application Insights ----------
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  kind: 'web'
  properties: { Application_Type: 'web' }
}

// ---------- Azure OpenAI + gpt-4o deployment ----------
resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: openaiName
  location: openaiLocation
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: openaiName
    publicNetworkAccess: 'Enabled'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: modelName
  sku: { name: modelSku, capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
}

// ---------- Document Intelligence ----------
resource docintel 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: docintelName
  location: location
  kind: 'FormRecognizer'
  sku: { name: 'S0' }
  properties: { customSubDomainName: docintelName }
}

// ---------- Azure SQL (Entra-only auth) ----------
resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: location
  properties: {
    minimalTlsVersion: '1.2'
    administrators: {
      administratorType: 'ActiveDirectory'
      principalType: 'User'
      login: sqlAdminLogin
      sid: sqlAdminObjectId
      tenantId: subscription().tenantId
      azureADOnlyAuthentication: true
    }
  }
}

resource sqlDb 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: sqlDbName
  location: location
  sku: { name: 'Basic', tier: 'Basic' }
}

// allow Azure services (Function App) เข้าถึง SQL
resource sqlFirewallAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

// ---------- Consumption plan (Linux) ----------
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  sku: { name: 'Y1', tier: 'Dynamic' }
  properties: { reserved: true }
}

// ---------- Function App (Python) ----------
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: funcName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'WEBSITE_CONTENTSHARE', value: contentShare }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }

        // ----- app-specific (ตรงกับ local.settings.json.example) -----
        { name: 'BLOB_CONNECTION_STRING', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}' }
        { name: 'BLOB_CONTAINER', value: 'proposals' }
        { name: 'DOCINTEL_ENDPOINT', value: docintel.properties.endpoint }
        { name: 'DOCINTEL_KEY', value: docintel.listKeys().key1 }
        { name: 'AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
        { name: 'AZURE_OPENAI_KEY', value: openai.listKeys().key1 }
        { name: 'AZURE_OPENAI_DEPLOYMENT', value: modelDeployment.name }
        { name: 'AZURE_OPENAI_API_VERSION', value: '2025-04-01-preview' }
        { name: 'SQL_CONNECTION_STRING', value: 'Driver={ODBC Driver 18 for SQL Server};Server=tcp:${sqlServer.properties.fullyQualifiedDomainName},1433;Database=${sqlDbName};Encrypt=yes;TrustServerCertificate=no;Authentication=ActiveDirectoryMsi' }
      ]
    }
  }
}

// ---------- Static Web App (frontend) ----------
resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: swaName
  location: swaLocation
  // Standard tier จำเป็นสำหรับ linked backend (bring-your-own Function App)
  sku: { name: 'Standard', tier: 'Standard' }
  properties: {}
}

output functionAppName string = functionApp.name
output functionAppHostname string = functionApp.properties.defaultHostName
output functionPrincipalId string = functionApp.identity.principalId
output staticWebAppName string = swa.name
output openaiEndpoint string = openai.properties.endpoint
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
