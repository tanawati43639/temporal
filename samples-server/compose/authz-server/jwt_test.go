package main

import (
	"crypto/ecdsa"
	"crypto/rand"
	"crypto/rsa"
	"errors"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v4"
	"go.temporal.io/server/common/authorization"
)

type stubKeyProvider struct {
	pub *rsa.PublicKey
}

func (s stubKeyProvider) EcdsaKey(alg string, kid string) (*ecdsa.PublicKey, error) {
	return nil, errors.New("ecdsa not supported")
}

func (s stubKeyProvider) HmacKey(alg string, kid string) ([]byte, error) {
	return nil, errors.New("hmac not supported")
}

func (s stubKeyProvider) RsaKey(alg string, kid string) (*rsa.PublicKey, error) {
	return s.pub, nil
}

func (s stubKeyProvider) SupportedMethods() []string { return []string{"RS256"} }

func (s stubKeyProvider) Close() {}

func newTestKeyProvider(t *testing.T) (authorization.TokenKeyProvider, *rsa.PrivateKey) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("generate rsa key: %v", err)
	}
	return stubKeyProvider{pub: &key.PublicKey}, key
}

func signTestToken(t *testing.T, key *rsa.PrivateKey, claims jwt.MapClaims) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	tok.Header["kid"] = "test-key"
	s, err := tok.SignedString(key)
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return s
}

func TestStripBearer(t *testing.T) {
	cases := []struct {
		in      string
		want    string
		wantErr bool
	}{
		{"Bearer abc", "abc", false},
		{"bearer abc", "abc", false},
		{"abc", "", true},
		{"Basic abc", "", true},
		{"", "", true},
	}
	for _, c := range cases {
		got, err := StripBearer(c.in)
		if (err != nil) != c.wantErr {
			t.Errorf("StripBearer(%q) err = %v, wantErr %v", c.in, err, c.wantErr)
		}
		if got != c.want {
			t.Errorf("StripBearer(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestParseAndValidate(t *testing.T) {
	provider, key := newTestKeyProvider(t)
	_, otherKey := newTestKeyProvider(t)

	t.Run("valid", func(t *testing.T) {
		tok := signTestToken(t, key, jwt.MapClaims{
			"sub": "user-1",
			"exp": time.Now().Add(time.Hour).Unix(),
		})
		claims, err := ParseAndValidate(tok, provider)
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if claims["sub"] != "user-1" {
			t.Errorf("sub = %v, want user-1", claims["sub"])
		}
	})

	t.Run("expired", func(t *testing.T) {
		tok := signTestToken(t, key, jwt.MapClaims{
			"sub": "user-1",
			"exp": time.Now().Add(-time.Hour).Unix(),
		})
		if _, err := ParseAndValidate(tok, provider); err == nil {
			t.Fatal("expected error for expired token")
		}
	})

	t.Run("wrong signing key", func(t *testing.T) {
		tok := signTestToken(t, otherKey, jwt.MapClaims{
			"sub": "user-1",
			"exp": time.Now().Add(time.Hour).Unix(),
		})
		if _, err := ParseAndValidate(tok, provider); err == nil {
			t.Fatal("expected error for token signed by a different key")
		}
	})

	t.Run("alg none", func(t *testing.T) {
		tok := jwt.NewWithClaims(jwt.SigningMethodNone, jwt.MapClaims{
			"sub": "user-1",
			"exp": time.Now().Add(time.Hour).Unix(),
		})
		tok.Header["kid"] = "test-key"
		s, err := tok.SignedString(jwt.UnsafeAllowNoneSignatureType)
		if err != nil {
			t.Fatalf("sign none token: %v", err)
		}
		if _, err := ParseAndValidate(s, provider); err == nil {
			t.Fatal("expected error for alg=none token")
		}
	})

	t.Run("garbage", func(t *testing.T) {
		if _, err := ParseAndValidate("not-a-jwt", provider); err == nil {
			t.Fatal("expected error for garbage token")
		}
	})
}

func TestParseAndValidateWithAudience(t *testing.T) {
	provider, key := newTestKeyProvider(t)
	tok := signTestToken(t, key, jwt.MapClaims{
		"sub": "user-1",
		"aud": "api://temporal",
		"exp": time.Now().Add(time.Hour).Unix(),
	})

	if _, err := ParseAndValidateWithAudience(tok, provider, "api://temporal"); err != nil {
		t.Errorf("matching audience: unexpected error: %v", err)
	}
	if _, err := ParseAndValidateWithAudience(tok, provider, "api://other"); err == nil {
		t.Error("expected error for mismatched audience")
	}
	if _, err := ParseAndValidateWithAudience(tok, provider, ""); err != nil {
		t.Errorf("empty audience must skip the check: %v", err)
	}
	if _, err := ParseAndValidateWithAudience(tok, provider, "  "); err != nil {
		t.Errorf("blank audience must skip the check: %v", err)
	}
	noAud := signTestToken(t, key, jwt.MapClaims{"exp": time.Now().Add(time.Hour).Unix()})
	if _, err := ParseAndValidateWithAudience(noAud, provider, "api://temporal"); err == nil {
		t.Error("expected error for token with no aud when audience required")
	}
}
