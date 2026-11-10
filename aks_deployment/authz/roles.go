package main

import (
	"strings"

	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/primitives"
)

// ParsePermission converts an Entra ID app-role value such as "uat:reader"
// into a Temporal namespace and role. It splits on the first colon only
// (so "dev:write:extra" is rejected), accepts both "read"/"reader" and "write"/"writer" (case-insensitively), and
// rewrites the exact namespace "system" to the cluster scope. Namespaces are
// never case-folded. When ok is false the other results are zero values.
func ParsePermission(s string) (namespace string, role authorization.Role, ok bool) {
	parts := strings.SplitN(s, ":", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return "", authorization.RoleUndefined, false
	}
	ns, word := parts[0], parts[1]
	switch strings.ToLower(word) {
	case "read", "reader":
		role = authorization.RoleReader
	case "write", "writer":
		role = authorization.RoleWriter
	case "admin":
		role = authorization.RoleAdmin
	case "worker":
		role = authorization.RoleWorker
	default:
		return "", authorization.RoleUndefined, false
	}
	if ns == "system" {
		ns = primitives.SystemLocalNamespace
	}
	return ns, role, true
}
