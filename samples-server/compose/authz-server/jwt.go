package main

import (
	"context"
	"fmt"
	"strings"

	"github.com/golang-jwt/jwt/v4"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/server/common/authorization"
)

const authorizationBearer = "bearer"

// StripBearer extracts the token from an "Authorization: Bearer <jwt>" header
// value. The scheme is matched case-insensitively, as Temporal's own mapper does.
func StripBearer(authToken string) (string, error) {
	parts := strings.SplitN(authToken, " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], authorizationBearer) {
		return "", serviceerror.NewPermissionDenied("unexpected authorization token format", "")
	}
	return parts[1], nil
}

// ParseAndValidate verifies the signature and standard time-based claims of
// tokenString using keys from provider. It mirrors the unexported parseJWT in
// go.temporal.io/server/common/authorization.
func ParseAndValidate(tokenString string, provider authorization.TokenKeyProvider) (jwt.MapClaims, error) {
	return ParseAndValidateWithAudience(tokenString, provider, "")
}

// ParseAndValidateWithAudience is ParseAndValidate plus an audience check that
// is enforced only when audience is non-blank, as in upstream's
// parseJWTWithAudience.
func ParseAndValidateWithAudience(tokenString string, provider authorization.TokenKeyProvider, audience string) (jwt.MapClaims, error) {
	parser := jwt.NewParser(jwt.WithValidMethods(provider.SupportedMethods()))

	var keyFunc jwt.Keyfunc
	if raw, _ := provider.(authorization.RawTokenKeyProvider); raw != nil {
		keyFunc = func(token *jwt.Token) (any, error) {
			return raw.GetKey(context.Background(), token)
		}
	} else {
		keyFunc = func(token *jwt.Token) (any, error) {
			kid, ok := token.Header["kid"].(string)
			if !ok {
				return nil, serviceerror.NewPermissionDenied(`malformed token - no "kid" header`, "")
			}
			alg, _ := token.Header["alg"].(string)
			switch token.Method.(type) {
			case *jwt.SigningMethodHMAC:
				return provider.HmacKey(alg, kid)
			case *jwt.SigningMethodRSA:
				return provider.RsaKey(alg, kid)
			case *jwt.SigningMethodECDSA:
				return provider.EcdsaKey(alg, kid)
			default:
				return nil, serviceerror.NewPermissionDenied(
					fmt.Sprintf("unexpected signing method: %v for algorithm: %v", token.Method, token.Header["alg"]), "")
			}
		}
	}

	token, err := parser.Parse(tokenString, keyFunc)
	if err != nil {
		return nil, err
	}
	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return nil, serviceerror.NewPermissionDenied("invalid token with no claims", "")
	}
	if err := claims.Valid(); err != nil {
		return nil, err
	}
	if strings.TrimSpace(audience) != "" && !claims.VerifyAudience(audience, true) {
		return nil, serviceerror.NewPermissionDenied("audience mismatch", "")
	}
	return claims, nil
}
