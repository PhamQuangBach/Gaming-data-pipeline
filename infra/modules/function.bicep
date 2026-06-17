param location string
param functionAppName string
param storageAccountName string
param keyVaultName string  

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: 'plan-${functionAppName}'
  location: location
  sku: { name: 'Y1', tier: 'Dynamic' }
  kind: 'functionapp'
  properties: { reserved: true }  // required for Linux
}

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: appServicePlan.id
    siteConfig: {
      pythonVersion: '3.11'
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${storageAccount.listKeys().keys[0].value}' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'RAWG_API_KEY', value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/rawg-api-key/)' }
        { name: 'SNOWFLAKE_ACCOUNT', value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/snowflake-account/)' }
        { name: 'SNOWFLAKE_USER', value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/snowflake-user/)' }
        { name: 'SNOWFLAKE_PASSWORD', value: '@Microsoft.KeyVault(SecretUri=${keyVault.properties.vaultUri}secrets/snowflake-password/)' }
        { name: 'ADLS_ACCOUNT_NAME', value: storageAccountName }
      ]
    }
    httpsOnly: true
  }
}

output functionAppName string = functionApp.name
output principalId string = functionApp.identity.principalId
