# Render client-IP header check

This test decides whether `TRUSTED_CLIENT_IP_HEADER` can be set safely for the ApexRx backend on Render.

**Leave `TRUSTED_CLIENT_IP_HEADER` unset until this test passes.**

## Why
- Render passes `X-Forwarded-For` through without clearing it, so a client can forge it.
- Cloudflare documents `True-Client-IP` as an Enterprise feature that is added only when enabled. If it isn't added, "its value can be spoofed to any value".
- Render doesn't document which header it guarantees, so it has to be observed directly.

## Steps
1. In Render, create a **new, temporary** web service from this repository. Do not change the existing ApexRx backend.
   - Root directory: `tools/render-ip-check`
   - Runtime: Python
   - Build command: `true`
   - Start command: `python app.py`
2. Find your real public IP, for example at https://ifconfig.me.
3. Open `https://<temp-service>.onrender.com/` in a browser. Note which headers show your real IP.
4. Send forged values:
   ```bash
   curl -s https://<temp-service>.onrender.com/ \
     -H "True-Client-IP: 203.0.113.7" \
     -H "CF-Connecting-IP: 203.0.113.8" \
     -H "X-Forwarded-For: 203.0.113.9"
   ```
5. Repeat steps 3 and 4 from a second network (for example, a phone hotspot).
6. **Delete the temporary service.**

## Reading the result
A header is safe to use only if **both** of these are true:
- It shows your real IP in step 3, from both networks.
- In step 4 it still shows your real IP, not the forged `203.0.113.x` value.

Then set `TRUSTED_CLIENT_IP_HEADER` on the backend to that header name (for example `CF-Connecting-IP`).

If a forged value comes through, or the header is missing, leave `TRUSTED_CLIENT_IP_HEADER` unset. The backend then skips the per-IP limit, and the per-account and per-device limits keep protecting sign-in.
