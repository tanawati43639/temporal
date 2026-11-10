package main

import (
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/config"
	"go.temporal.io/server/common/log"
	"go.temporal.io/server/common/log/tag"
	"go.temporal.io/server/common/primitives"
)

const adminCertCommonName = "temporal-admin"

// AzureClaimMapper turns a client certificate or an Entra ID bearer token
// into Temporal claims.
type AzureClaimMapper struct {
	keyProvider          authorization.TokenKeyProvider
	permissionsClaimName string
	logger               log.Logger
}

var (
	_ authorization.ClaimMapper                     = (*AzureClaimMapper)(nil)
	_ authorization.ClaimMapperWithAuthInfoRequired = (*AzureClaimMapper)(nil)
)

// NewAzureClaimMapper builds a mapper whose keys come from the JWKS endpoints
// configured under global.authorization.
func NewAzureClaimMapper(cfg *config.Config, logger log.Logger) *AzureClaimMapper {
	claimName := cfg.Global.Authorization.PermissionsClaimName
	if claimName == "" {
		claimName = "roles"
	}
	return &AzureClaimMapper{
		keyProvider:          authorization.NewDefaultTokenKeyProvider(&cfg.Global.Authorization, logger),
		permissionsClaimName: claimName,
		logger:               logger,
	}
}

// AuthInfoRequired returns false so the mapper is always consulted.
func (m *AzureClaimMapper) AuthInfoRequired() bool { return false }

// GetClaims maps authInfo to claims. A certificate with the admin common name
// wins over any token; otherwise a bearer token is validated and its roles
// mapped; anything else yields empty claims.
func (m *AzureClaimMapper) GetClaims(authInfo *authorization.AuthInfo) (*authorization.Claims, error) {
	if authInfo == nil {
		return &authorization.Claims{}, nil
	}
	if authInfo.TLSSubject != nil && authInfo.TLSSubject.CommonName == adminCertCommonName {
		return &authorization.Claims{System: authorization.RoleAdmin, AuthType: "mtls", Subject: adminCertCommonName}, nil
	}
	if authInfo.AuthToken == "" {
		return &authorization.Claims{}, nil
	}

	tokenString, err := StripBearer(authInfo.AuthToken)
	if err != nil {
		return nil, err
	}
	jwtClaims, err := ParseAndValidateWithAudience(tokenString, m.keyProvider, authInfo.Audience)
	if err != nil {
		if _, ok := err.(serviceerror.ServiceError); ok {
			return nil, err
		}
		return nil, serviceerror.NewPermissionDenied("token validation failed: "+err.Error(), "")
	}

	claims := &authorization.Claims{AuthType: "jwt"}
	if s, ok := jwtClaims["preferred_username"].(string); ok && s != "" {
		claims.Subject = s
	} else if s, ok := jwtClaims["sub"].(string); ok {
		claims.Subject = s
	}

	entries, ok := jwtClaims[m.permissionsClaimName].([]any)
	if !ok {
		return claims, nil
	}
	for _, entry := range entries {
		s, ok := entry.(string)
		if !ok {
			m.logger.Warn("skipping non-string permission entry", tag.NewStringTag("subject", claims.Subject))
			continue
		}
		namespace, role, ok := ParsePermission(s)
		if !ok {
			m.logger.Warn("skipping unparseable permission entry",
				tag.NewStringTag("subject", claims.Subject), tag.NewStringTag("permission", s))
			continue
		}
		if namespace == primitives.SystemLocalNamespace {
			claims.System |= role
			continue
		}
		if claims.Namespaces == nil {
			claims.Namespaces = make(map[string]authorization.Role)
		}
		claims.Namespaces[namespace] |= role
	}
	return claims, nil
}
