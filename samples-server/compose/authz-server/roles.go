package main

import (
	"strings"

	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/primitives"
)

// ParsePermission converts an Entra ID app-role value such as "uat:reader"
// into a Temporal namespace and role. It splits on the first colon, ignores
// any trailing ":..." segment, accepts both "read"/"reader" and "write"/"writer" (case-insensitively), and
// rewrites the exact namespace "system" to the cluster scope. Namespaces are
// never case-folded. When ok is false the other results are zero values.
func ParsePermission(s string) (namespace string, role authorization.Role, ok bool) {
	ns, word, found := strings.Cut(s, ":")
	// Anything after a second colon is ignored ("dev:write:extra" is dev/writer).
	word, _, _ = strings.Cut(word, ":")
	if !found || ns == "" || word == "" {
		return "", authorization.RoleUndefined, false
	}
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
