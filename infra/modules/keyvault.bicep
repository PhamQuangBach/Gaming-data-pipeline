param location string
param keyVaultName string
param functionAppPrincipalId string = ''

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true 
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

// Grant the Function App's managed identity permission to read secrets
// Only created if a principalId is provided
resource secretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (functionAppPrincipalId != '') {
  name: guid(keyVault.id, functionAppPrincipalId, 'secrets-user')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets User
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output keyVaultName string = keyVault.name
