targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environment string = 'dev'
param allowedOrigin string = '*'   // your GitHub Pages URL, e.g. https://yourusername.github.io

// Resource names — all globally unique, so we suffix with a short hash
var suffix = uniqueString(resourceGroup().id)
var storageAccountName = 'rawgadls${take(suffix, 8)}'
var keyVaultName = 'kv-gaming-${take(suffix, 8)}'
var functionAppName = 'func-rawg-ingest-${environment}-${take(suffix, 6)}'

// Reference the Key Vault as an existing resource so we can call
// getSecret() when passing secrets into module @secure() params.
// getSecret() is only valid at module call sites, not inside resource bodies.
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

module storage './modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    storageAccountName: storageAccountName
    containerNames: ['bronze']
  }
}

module keyvault './modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    keyVaultName: keyVaultName
  }
}

module function './modules/function.bicep' = {
  name: 'function'
  params: {
    location: location
    functionAppName: functionAppName
    storageAccountName: storageAccountName
    keyVaultName: keyvault.outputs.keyVaultName
    allowedOrigin: allowedOrigin
  }
  dependsOn: [storage]
}

module pgvector './modules/pgvector.bicep' = {
  name: 'pgvector'
  params: {
    location: location
    keyVaultName: keyvault.outputs.keyVaultName
    administratorPassword: kv.getSecret('pgvector-postgres-password')
  }
}

// Outputs — printed after deploy so you can copy them
output storageAccountName string = storage.outputs.storageAccountName
output adlsEndpoint string = storage.outputs.primaryEndpoint
output keyVaultName string = keyvault.outputs.keyVaultName
output functionAppName string = function.outputs.functionAppName
output functionPrincipalId string = function.outputs.principalId
output pgvectorServerFqdn string = pgvector.outputs.serverFqdn
output pgvectorDatabase string = pgvector.outputs.databaseName
