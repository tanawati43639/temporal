package main

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
	"go.temporal.io/server/common/authorization"
)

const (
	testWorkflowService   = "/temporal.api.workflowservice.v1.WorkflowService/"
	testStartWorkflowAPI  = testWorkflowService + "StartWorkflowExecution"
	testDescribeNamespace = testWorkflowService + "DescribeNamespace"
	testUpdateNamespace   = testWorkflowService + "UpdateNamespace"
	testGetSystemInfo     = testWorkflowService + "GetSystemInfo"
	testListNamespaces    = testWorkflowService + "ListNamespaces"
	testGetClusterInfo    = testWorkflowService + "GetClusterInfo"
	testGetSearchAttrs    = testWorkflowService + "GetSearchAttributes"
	testListClusters      = "/temporal.api.operatorservice.v1.OperatorService/ListClusters"
	testAddRemoteCluster  = "/temporal.api.operatorservice.v1.OperatorService/AddOrUpdateRemoteCluster"
)

func TestAzureAuthorizer(t *testing.T) {
	require.True(t, authorization.IsHealthCheckAPI(testGetSystemInfo))

	tests := []struct {
		name      string
		claims    *authorization.Claims
		api       string
		namespace string
		want      authorization.Decision
	}{
		{"nil claims denied", nil, testStartWorkflowAPI, "dev", authorization.DecisionDeny},
		{"nil claims denied on ListNamespaces", nil, testListNamespaces, "", authorization.DecisionDeny},
		{"health check allowed with nil claims", nil, testGetSystemInfo, "", authorization.DecisionAllow},
		{"system admin updates namespace", &authorization.Claims{Subject: "root", System: authorization.RoleAdmin}, testUpdateNamespace, "dev", authorization.DecisionAllow},

		{"ListNamespaces with a namespace role", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"uat": authorization.RoleReader}}, testListNamespaces, "", authorization.DecisionAllow},
		{"ListNamespaces with no roles", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{}}, testListNamespaces, "", authorization.DecisionDeny},
		{"ListNamespaces with undefined role", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"uat": authorization.RoleUndefined}}, testListNamespaces, "", authorization.DecisionDeny},
		{"GetClusterInfo with a namespace role", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"uat": authorization.RoleReader}}, testGetClusterInfo, "", authorization.DecisionAllow},
		{"GetSearchAttributes with a namespace role", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"uat": authorization.RoleReader}}, testGetSearchAttrs, "", authorization.DecisionAllow},
		{"GetClusterInfo with no roles", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{}}, testGetClusterInfo, "", authorization.DecisionDeny},
		{"ListClusters not read-only, denied", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"uat": authorization.RoleReader}}, testListClusters, "", authorization.DecisionDeny},
		{"AddOrUpdateRemoteCluster denied", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"uat": authorization.RoleWriter}}, testAddRemoteCluster, "", authorization.DecisionDeny},

		{"writer starts workflow in own namespace", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"dev": authorization.RoleWriter}}, testStartWorkflowAPI, "dev", authorization.DecisionAllow},
		{"reader cannot start workflow", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"dev": authorization.RoleReader}}, testStartWorkflowAPI, "dev", authorization.DecisionDeny},
		{"writer in other namespace denied", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"uat": authorization.RoleWriter}}, testStartWorkflowAPI, "dev", authorization.DecisionDeny},
		{"reader describes own namespace", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"uat": authorization.RoleReader}}, testDescribeNamespace, "uat", authorization.DecisionAllow},
		{"writer cannot update namespace", &authorization.Claims{Subject: "u", Namespaces: map[string]authorization.Role{"dev": authorization.RoleWriter}}, testUpdateNamespace, "dev", authorization.DecisionDeny},
	}

	authorizer := NewAzureAuthorizer()
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			res, err := authorizer.Authorize(context.Background(), tc.claims, &authorization.CallTarget{
				APIName:   tc.api,
				Namespace: tc.namespace,
			})
			require.NoError(t, err)
			require.Equal(t, tc.want, res.Decision)
			if tc.want == authorization.DecisionAllow && tc.claims != nil && tc.api != testGetSystemInfo {
				require.NotNil(t, res.Principal)
				require.Equal(t, tc.claims.Subject, res.Principal.Name)
			}
		})
	}
}

func TestHasAnyNamespaceRole(t *testing.T) {
	tests := []struct {
		name   string
		claims *authorization.Claims
		want   bool
	}{
		{"nil claims", nil, false},
		{"nil map", &authorization.Claims{}, false},
		{"empty map", &authorization.Claims{Namespaces: map[string]authorization.Role{}}, false},
		{"only zero-valued entries", &authorization.Claims{Namespaces: map[string]authorization.Role{"a": authorization.RoleUndefined}}, false},
		{"one real role", &authorization.Claims{Namespaces: map[string]authorization.Role{"a": authorization.RoleUndefined, "b": authorization.RoleWorker}}, true},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			require.Equal(t, tc.want, hasAnyNamespaceRole(tc.claims))
		})
	}
}
