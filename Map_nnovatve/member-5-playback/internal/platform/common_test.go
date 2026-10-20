package platform

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestAuthorityTimeoutControlsOutboundCancellation(t *testing.T) {
	t.Setenv("SERVICE_KEY", "test-key")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-r.Context().Done():
			return
		case <-time.After(100 * time.Millisecond):
			JSON(w, 200, map[string]bool{"ok": true})
		}
	}))
	defer server.Close()
	request := httptest.NewRequest("GET", "http://local.invalid/", nil)
	var result map[string]bool
	t.Setenv("AUTHORITY_TIMEOUT_MS", "10")
	if err := Call(request, "GET", server.URL, nil, &result); err == nil {
		t.Fatal("slow authority ignored the configured deadline")
	}
	t.Setenv("AUTHORITY_TIMEOUT_MS", "1000")
	if err := Call(request, "GET", server.URL, nil, &result); err != nil || !result["ok"] {
		t.Fatalf("authority did not complete within the longer deadline: %v", err)
	}
}

func TestSignatureBindsPathExpiryAndKey(t *testing.T) {
	now := time.Unix(100, 0)
	signature := Signature("/media/a/1.ts", 200, "key")
	if !ValidSignature("/media/a/1.ts", 200, signature, "key", now) {
		t.Fatal("valid signature rejected")
	}
	for _, path := range []string{"/media/b/1.ts", "/media/a/2.ts"} {
		if ValidSignature(path, 200, signature, "key", now) {
			t.Fatal("path substitution accepted")
		}
	}
	if ValidSignature("/media/a/1.ts", 100, signature, "key", now) {
		t.Fatal("expired signature accepted")
	}
	if ValidSignature("/media/a/1.ts", 200, signature, "wrong", now) {
		t.Fatal("wrong key accepted")
	}
}
func TestStableAdmissionIdentity(t *testing.T) {
	if StableID("a", "key") != StableID("a", "key") {
		t.Fatal("retry changed identity")
	}
	if StableID("a", "key") == StableID("b", "key") {
		t.Fatal("cross-account collision")
	}
}
func TestReplayDoesNotExtendRetention(t *testing.T) {
	end := time.Now().Add(-731 * 24 * time.Hour)
	if RemainingTTL(end, time.Now()) != 0 {
		t.Fatal("old event resurrected")
	}
	end = time.Now().Add(-24 * time.Hour)
	if RemainingTTL(end, time.Now()) >= 730*86400 {
		t.Fatal("retention reset")
	}
}
