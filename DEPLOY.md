# Deploying the dev instance (Hugging Face Space)

The Space builds from this repo's Dockerfile. One-time setup lives in the
Space settings; after that, deploys are just `git push hf main`.

## Space secrets (Settings > Variables and secrets)

| Secret             | Value                                                       |
| ------------------ | ----------------------------------------------------------- |
| CCR_SESSION_SECRET | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| SUPABASE_URL       | from Supabase > Project Settings > API                      |
| SUPABASE_ANON_KEY  | from the same page (anon public key, NOT service_role)      |
| CCR_APP_URL        | https://devaanand-ccr-platform.hf.space                     |
| CCR_COOKIE_SECURE  | 1                                                           |
| CCR_MAX_ROWS       | 20000 (global upload ceiling; code default is 100000)       |

Retention (CCR_ANON_TTL_HOURS=24) and model pre-warm are already defaults in
the Dockerfile.

## Tester guide

The deployed instance serves a click-through testing guide at /guide with
download links for every demo corpus (served from /samples). Send the PI and
students that URL; no files need to be shared out of band.

## Supabase setup for Google sign-in (one time)

1. supabase.com > New project (free tier).
2. Authentication > Providers > Google > Enable. Copy the shown callback URL
   (https://PROJECT_REF.supabase.co/auth/v1/callback).
3. console.cloud.google.com > OAuth consent screen (External) > Credentials >
   Create OAuth client ID (Web application) > add the Supabase callback URL as
   an authorized redirect URI. Paste client id/secret back into the Supabase
   Google provider form.
4. Authentication > URL Configuration: add BOTH redirect URLs:
   - http://127.0.0.1:8000/api/auth/google/callback
   - https://devaanand-ccr-platform.hf.space/api/auth/google/callback
5. Project Settings > API: copy the Project URL and anon key into the Space
   secrets (and your local .env).

## Push

```bash
git push origin main        # GitHub
git push hf main            # Hugging Face Space (rebuilds + redeploys)
```

The hf remote has no stored token; use your HF username and a WRITE token as
the password when prompted (or a credential helper).

## Caveats of the free dev instance

- Ephemeral disk: SQLite resets on rebuild/restart. Google users are recreated
  on next sign-in automatically; password accounts must re-register. Fine for
  feedback; a persistent volume or Postgres arrives with the launch decision.
- The Space sleeps after ~48 h idle; first visit wakes it (~1 min).
