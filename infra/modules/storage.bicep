param location string
param storageAccountName string
param containerNames array = ['bronze']

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    isHnsEnabled: true           // ADLS Gen2 — hierarchical namespace
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = [for name in containerNames: {
  parent: blobService
  name: name
  properties: { publicAccess: 'None' }
}]

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
output primaryEndpoint string = storageAccount.properties.primaryEndpoints.dfs
