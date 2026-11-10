package main

import (
	"crypto/x509/pkix"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v4"
	"github.com/stretchr/testify/require"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/log"
)

func newTestMapper(t *testing.T) (*AzureClaimMapper, func(jwt.MapClaims) string) {
	provider, key := newTestKeyProvider(t)
	m := &AzureClaimMapper{
		keyProvider:          provider,
		permissionsClaimName: "roles",
		logger:               log.NewNoopLogger(),
	}
	sign := func(c jwt.MapClaims) string {
		if _, ok := c["exp"]; !ok {
			c["exp"] = time.Now().Add(time.Hour).Unix()
		}
		return "Bearer " + signTestToken(t, key, c)
	}
	return m, sign
}

func TestAzureClaimMapper(t *testing.T) {
	m, sign := newTestMapper(t)
	adminCert := &pkix.Name{CommonName: "temporal-admin"}
	userCert := &pkix.Name{CommonName: "someone"}

	t.Run("admin cert no token", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{TLSSubject: adminCert})
		require.NoError(t, err)
		require.Equal(t, &authorization.Claims{System: authorization.RoleAdmin, AuthType: "mtls", Subject: "temporal-admin"}, c)
	})
	t.Run("admin cert wins over token, token not parsed", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{TLSSubject: adminCert, AuthToken: "garbage"})
		require.NoError(t, err)
		require.Equal(t, authorization.RoleAdmin, c.System)
	})
	t.Run("namespace roles", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{TLSSubject: userCert,
			AuthToken: sign(jwt.MapClaims{"sub": "s1", "preferred_username": "alice", "roles": []any{"uat:reader", "dev:writer"}})})
		require.NoError(t, err)
		require.Equal(t, map[string]authorization.Role{"uat": authorization.RoleReader, "dev": authorization.RoleWriter}, c.Namespaces)
		require.Equal(t, authorization.RoleUndefined, c.System)
		require.Equal(t, "jwt", c.AuthType)
		require.Equal(t, "alice", c.Subject)
	})
	t.Run("subject falls back to sub", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{"sub": "s1"})})
		require.NoError(t, err)
		require.Equal(t, "s1", c.Subject)
	})
	t.Run("system admin", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{"roles": []any{"system:admin"}})})
		require.NoError(t, err)
		require.Equal(t, authorization.RoleAdmin, c.System)
		require.Empty(t, c.Namespaces)
	})
	t.Run("roles are OR-ed", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{"roles": []any{"dev:read", "dev:write"}})})
		require.NoError(t, err)
		require.Equal(t, map[string]authorization.Role{"dev": authorization.RoleReader | authorization.RoleWriter}, c.Namespaces)
	})
	t.Run("bad entries skipped, no zero role stored", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{
			"roles": []any{"uat:reader", "uat:bogus", float64(7), nil, "nocolon", "bogus:bogus"}})})
		require.NoError(t, err)
		require.Equal(t, map[string]authorization.Role{"uat": authorization.RoleReader}, c.Namespaces)
	})
	t.Run("only bad entries leaves no map entries", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{"roles": []any{"x:bogus", 1}})})
		require.NoError(t, err)
		require.Empty(t, c.Namespaces)
	})
	t.Run("client cert no token", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{TLSSubject: userCert})
		require.NoError(t, err)
		require.Equal(t, &authorization.Claims{}, c)
	})
	t.Run("nil authInfo", func(t *testing.T) {
		c, err := m.GetClaims(nil)
		require.NoError(t, err)
		require.Equal(t, &authorization.Claims{}, c)
	})
	t.Run("nil TLSSubject no token", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{})
		require.NoError(t, err)
		require.Equal(t, &authorization.Claims{}, c)
	})
	t.Run("roles claim not an array", func(t *testing.T) {
		for _, v := range []any{"uat:reader", float64(5), map[string]any{"a": "b"}} {
			c, err := m.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{"roles": v})})
			require.NoError(t, err)
			require.Empty(t, c.Namespaces)
			require.Equal(t, authorization.RoleUndefined, c.System)
		}
	})
	t.Run("roles claim absent", func(t *testing.T) {
		c, err := m.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{"sub": "x"})})
		require.NoError(t, err)
		require.Empty(t, c.Namespaces)
	})
	t.Run("custom permissions claim name", func(t *testing.T) {
		m2 := *m
		m2.permissionsClaimName = "perms"
		c, err := m2.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{"perms": []any{"a:read"}, "roles": []any{"b:read"}})})
		require.NoError(t, err)
		require.Equal(t, map[string]authorization.Role{"a": authorization.RoleReader}, c.Namespaces)
	})
	t.Run("malformed bearer prefix", func(t *testing.T) {
		_, err := m.GetClaims(&authorization.AuthInfo{AuthToken: "Basic abc"})
		require.Error(t, err)
		var pd *serviceerror.PermissionDenied
		require.ErrorAs(t, err, &pd)
	})
	t.Run("empty stripped token is rejected, not anonymous", func(t *testing.T) {
		_, err := m.GetClaims(&authorization.AuthInfo{AuthToken: "Bearer "})
		require.Error(t, err)
	})
	t.Run("expired token", func(t *testing.T) {
		_, err := m.GetClaims(&authorization.AuthInfo{AuthToken: sign(jwt.MapClaims{"exp": time.Now().Add(-time.Hour).Unix()})})
		require.Error(t, err)
		var pd *serviceerror.PermissionDenied
		require.ErrorAs(t, err, &pd)
	})
	t.Run("wrong key", func(t *testing.T) {
		_, otherKey := newTestKeyProvider(t)
		tok := "Bearer " + signTestToken(t, otherKey, jwt.MapClaims{"exp": time.Now().Add(time.Hour).Unix()})
		_, err := m.GetClaims(&authorization.AuthInfo{AuthToken: tok})
		require.Error(t, err)
	})
}

func TestAzureClaimMapperAuthInfoRequired(t *testing.T) {
	require.False(t, (&AzureClaimMapper{}).AuthInfoRequired())
}
