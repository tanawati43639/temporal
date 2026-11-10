package main

import (
	"context"

	commonpb "go.temporal.io/api/common/v1"
	"go.temporal.io/server/common/authorization"
)

// listNamespacesAPI is declared cluster-scoped by Temporal, so the default
// authorizer would require a system role for it. The Temporal UI calls it
// first, so a namespace-only user must be allowed through.
const listNamespacesAPI = "/temporal.api.workflowservice.v1.WorkflowService/ListNamespaces"

// AzureAuthorizer behaves exactly like Temporal's default authorizer, except
// that ListNamespaces is allowed for any caller holding a namespace role.
type AzureAuthorizer struct {
	delegate authorization.Authorizer
}

// NewAzureAuthorizer returns an authorizer that delegates to the default one.
func NewAzureAuthorizer() authorization.Authorizer {
	return &AzureAuthorizer{delegate: authorization.NewDefaultAuthorizer()}
}

func (a *AzureAuthorizer) Authorize(ctx context.Context, claims *authorization.Claims, target *authorization.CallTarget) (authorization.Result, error) {
	if target.APIName == listNamespacesAPI && hasAnyNamespaceRole(claims) {
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
