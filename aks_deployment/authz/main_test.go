package main

import (
	"os"
	"reflect"
	"testing"

	"go.temporal.io/server/temporal"
)

func TestServicesFromEnv(t *testing.T) {
	cases := []struct {
		name  string
		unset bool
		value string
		want  []string
	}{
		{name: "unset", unset: true, want: temporal.DefaultServices},
		{name: "empty", value: "", want: temporal.DefaultServices},
		{name: "single", value: "frontend", want: []string{"frontend"}},
		{name: "two", value: "frontend,worker", want: []string{"frontend", "worker"}},
		{name: "trimmed", value: " frontend , worker ", want: []string{"frontend", "worker"}},
		{name: "empties dropped", value: "frontend,,worker", want: []string{"frontend", "worker"}},
		{name: "only comma", value: ",", want: temporal.DefaultServices},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("TEMPORAL_SERVICES", tc.value) // registers restore on cleanup
			if tc.unset {
				os.Unsetenv("TEMPORAL_SERVICES")
			}
			got := servicesFromEnv()
			if !reflect.DeepEqual(got, tc.want) {
				t.Errorf("servicesFromEnv() = %v, want %v", got, tc.want)
			}
		})
	}
}
