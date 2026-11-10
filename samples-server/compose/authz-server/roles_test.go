package main

import (
	"testing"

	"go.temporal.io/server/common/authorization"
	"go.temporal.io/server/common/primitives"
)

func TestParsePermission(t *testing.T) {
	cases := []struct {
		in        string
		namespace string
		role      authorization.Role
		ok        bool
	}{
		{"uat:reader", "uat", authorization.RoleReader, true},
		{"uat:read", "uat", authorization.RoleReader, true},
		{"dev:writer", "dev", authorization.RoleWriter, true},
		{"dev:write", "dev", authorization.RoleWriter, true},
		{"default:admin", "default", authorization.RoleAdmin, true},
		{"foo:worker", "foo", authorization.RoleWorker, true},
		{"uat:READER", "uat", authorization.RoleReader, true},
		{"system:admin", primitives.SystemLocalNamespace, authorization.RoleAdmin, true},
		{"temporal-system:admin", primitives.SystemLocalNamespace, authorization.RoleAdmin, true},
		{"Prod:reader", "Prod", authorization.RoleReader, true},
		{"dev:write:extra", "", authorization.RoleUndefined, false},
		{"uatreader", "", authorization.RoleUndefined, false},
		{":read", "", authorization.RoleUndefined, false},
		{"uat:", "", authorization.RoleUndefined, false},
		{"uat:bogus", "", authorization.RoleUndefined, false},
		{"", "", authorization.RoleUndefined, false},
	}
	for _, c := range cases {
		t.Run(c.in, func(t *testing.T) {
			ns, role, ok := ParsePermission(c.in)
			if ns != c.namespace || role != c.role || ok != c.ok {
				t.Errorf("ParsePermission(%q) = (%q, %v, %v), want (%q, %v, %v)",
					c.in, ns, role, ok, c.namespace, c.role, c.ok)
			}
		})
	}
}
