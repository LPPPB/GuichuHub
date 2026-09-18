# Synchronous API egress

The API remains on the internal `core` network. Existing QR generation/polling,
UP lookup/navigation, and image routes use `HTTP_PROXY`/`HTTPS_PROXY` to reach
the dedicated Squid service. Worker retains its own egress network.

Squid permits `api.bilibili.com`, `passport.bilibili.com`, `www.bilibili.com`,
and the existing image families `*.hdslb.com` and `*.biliimg.com`. Only ports
80/443 are permitted, with CONNECT limited to 443. Private, loopback,
link-local, multicast and benchmark destinations are denied even when an
allowed hostname resolves there. Reverse DNS cannot turn an IP URL into an
allowed hostname. The proxy has no host port, credentials, or data mounts;
request/access logs and caching are disabled. HTTPS is tunneled, not decrypted.

The image is pinned to the verified Canonical digest in Compose. Refresh that
digest through a reviewed dependency update and rerun the local proxy tests.
The implementation follows [Canonical's Squid image configuration](https://hub.docker.com/r/ubuntu/squid)
and [Squid's ordered access control rules](https://www.squid-cache.org/Doc/config/http_access/).

This preserves the existing synchronous frontend contracts while restricting
destination hosts. A domain allowlist cannot constrain paths inside an HTTPS
tunnel. Removing that remaining capability would require changing the API to
an asynchronous Worker or application-proxy workflow before deployment.

Verification uses a temporary internal network, public-shaped fixture IPs,
an HTTP stub and the exact pinned Squid policy. No live Bilibili calls occur.
