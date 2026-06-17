targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environment string = 'dev'

// Resource names suffix with a hash
var suffix = uniqueString(resourceGroup().id)
var storageAccountName = 'rawgadls${take(suffix, 8)}'   // max 24 chars, lowercase only
var keyVaultName = 'kv-gaming-${take(suffix, 8)}'
var functionAppName = 'func-rawg-ingest-${environment}-${take(suffix, 6)}'

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
  }
  dependsOn: [storage]
}

// Outputs
output storageAccountName string = storage.outputs.storageAccountName
output adlsEndpoint string = storage.outputs.primaryEndpoint
output keyVaultName string = keyvault.outputs.keyVaultName
output functionAppName string = function.outputs.functionAppName
output functionPrincipalId string = function.outputs.principalId
