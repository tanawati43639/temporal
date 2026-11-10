package main

import (
	"context"

	commonpb "go.temporal.io/api/common/v1"
	"go.temporal.io/server/common/api"
	"go.temporal.io/server/common/authorization"
)

// AzureAuthorizer behaves exactly like Temporal's default authorizer, except
// that read-only cluster-scoped APIs (ListNamespaces, GetClusterInfo,
// GetSearchAttributes, ...) are allowed for any caller holding a namespace
// role. The default authorizer requires a system role for them, which would
// stop a namespace-only user from loading the Temporal UI.
type AzureAuthorizer struct {
	delegate authorization.Authorizer
}

// NewAzureAuthorizer returns an authorizer that delegates to the default one.
func NewAzureAuthorizer() authorization.Authorizer {
	return &AzureAuthorizer{delegate: authorization.NewDefaultAuthorizer()}
}

func (a *AzureAuthorizer) Authorize(ctx context.Context, claims *authorization.Claims, target *authorization.CallTarget) (authorization.Result, error) {
	m := api.GetMethodMetadata(target.APIName)
	if m.Scope == api.ScopeCluster && m.Access == api.AccessReadOnly && hasAnyNamespaceRole(claims) {
		return authorization.Result{
			Decision:  authorization.DecisionAllow,
			Principal: &commonpb.Principal{Type: claims.AuthType, Name: claims.Subject},
		}, nil
	}
	return a.delegate.Authorize(ctx, claims, target)
}

func hasAnyNamespaceRole(claims *authorization.Claims) bool {
	if claims == nil {
		return false
	}
	for _, role := range claims.Namespaces {
		if role != authorization.RoleUndefined {
			return true
		}
	}
	return false
}
