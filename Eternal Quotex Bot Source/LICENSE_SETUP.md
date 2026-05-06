# License System Setup

This project already includes the desktop-side license client and admin UI.

Use the included Supabase starter if you want a free hosted API for license checks.

## What The Desktop App Expects

The app sends a `POST` request to your license API with this JSON body:

```json
{
  "license_key": "YOUR-KEY",
  "machine_id": "ABCDEF1234567890",
  "machine_fingerprint": "long-sha256-fingerprint",
  "app": "Eternal Quotex Bot"
}
```

Your API should return JSON like this for validation:

```json
{
  "valid": true,
  "status": "active",
  "reason": "License active.",
  "expires_at": "2027-12-31T00:00:00Z",
  "machine_id": "ABCDEF1234567890"
}
```

If `valid` is `false`, the desktop app will reject the session. If the app is already connected and a later poll returns `valid: false`, the bot disconnects and closes.

The included Supabase function also supports admin actions through the same endpoint:

- `action: "create"` to create a key with duration or lifetime
- `action: "revoke"` to disable a key immediately
- `action: "list"` to load recent keys into the admin panel

## Free API Recommendation

Use Supabase:

- Create a free project
- Run the SQL in `supabase/sql/license_schema.sql`
- Deploy the Edge Function in `supabase/functions/license-validate/index.ts`
- Deploy it without JWT verification so the desktop app can call it directly

## Supabase Setup

1. Create a Supabase project.
2. Open the SQL editor and run `supabase/sql/license_schema.sql`.
3. Create or deploy an Edge Function named `license-validate`.
4. Paste in the code from `supabase/functions/license-validate/index.ts`.
5. Deploy it without JWT verification:

```text
supabase functions deploy license-validate --no-verify-jwt
```

You can also keep the same setting in `supabase/config.toml`.

6. Add the function secret:

```text
LICENSE_SHARED_TOKEN=your-long-random-secret
```

7. Insert license keys into the `public.license_keys` table.

You can manage licenses directly in the Supabase Dashboard too:

- Go to `Table Editor`
- Open `public.license_keys`
- Insert new rows for new users
- Change `status` to `revoked`, `disabled`, or `expired` to cut access
- Edit `expires_at`, `notes`, or `machine_lock` any time

Recommended starter rows:

```sql
insert into public.license_keys (
  license_key,
  status,
  expires_at,
  machine_lock,
  notes
) values
  ('TEST-LIFETIME-001', 'active', null, true, 'Permanent key'),
  ('TEST-30DAY-001', 'active', now() + interval '30 days', true, '30 day key');
```

## App Integration

Open the desktop app:

1. Go to `Settings`
2. End user section:
   - turn on `Require a license before connecting`
   - enter the user key in `License Key`
   - leave `Remember this license key` off if you want the app to ask every launch
3. Go to `Admin`
4. Unlock the panel with password `00440404`
5. Fill these fields:
   - `API URL`: `https://vxwfmqvjwjxlrfskopts.supabase.co/functions/v1/license-validate`
   - `API Token`: leave it alone if your build already embeds the shared token
   - `Poll`: `5 s` for near-immediate revocation
   - `Lock licenses to machine ID`: enabled
6. Click `Save Settings`
7. Click `Validate License`
8. In the same locked Admin page, use `Generate Key`, `Create License`, `Revoke License`, and `Refresh Licenses`

## Embedded Defaults

The desktop app can auto-fill these values:

- `LICENSE_API_URL` for the Supabase function URL
- `LICENSE_SHARED_TOKEN` for admin-only create, revoke, and list actions

Normal end-user validation no longer needs the shared token. The token is only required for the locked admin actions.
If the function is still deployed with JWT verification on, Supabase will reject the request before your code runs and both validation and license creation will fail.

## How Revocation Works

- If you change a row from `active` to `disabled`, `revoked`, or `expired`, the next poll will invalidate the desktop session.
- With poll set to `5 seconds`, shutdown happens on the next check, not instantly at the network layer.

## Key Table Fields

- `license_key`: the key the user types
- `status`: `active`, `disabled`, `revoked`, or `expired`
- `expires_at`: optional UTC timestamp
- `machine_lock`: whether first successful use binds the key to one machine
- `machine_id`: stored machine ID after first activation
- `machine_fingerprint`: optional stronger device trace
- `last_seen_at`: updated on successful checks

## Important Security Notes

- PyInstaller apps can be hardened, but not made impossible to reverse engineer.
- Keep secrets on the server. Never rely on the desktop app alone to enforce licensing.
- The shared API token is only a gate to your function. The actual license decision must still come from your server-side table.
