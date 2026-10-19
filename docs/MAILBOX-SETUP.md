# Mailbox setup (Gmail and Outlook)

DataForce reads your mailbox with **read-only** access to suggest which emails belong to which
open deal. You register your own OAuth client with Google and/or Microsoft (DataForce ships none),
then paste its client id (and secret) in **Settings > Mailbox**. Do this once per provider.

The redirect addresses below must match exactly what DataForce sends. Settings > Mailbox also
shows the address under each provider.

| Provider | Redirect address DataForce sends |
|---|---|
| Gmail | `http://127.0.0.1:8800/api/mailbox/callback` |
| Outlook | `http://localhost:8800/api/mailbox/callback` |

Open DataForce at `http://127.0.0.1:8800` (or `http://localhost:8800`) while connecting. If you run
`dataforce ui --port N`, replace 8800 by N in the address you register.

## Google (Gmail)

1. Go to <https://console.cloud.google.com/> and sign in with the Google account you will connect.
2. Top bar > project picker > **New project**. Name it `DataForce` > **Create**, then select it.
3. **APIs & Services > Library**. Search **Gmail API** > **Enable**.
4. **APIs & Services > OAuth consent screen** (or *Google Auth platform > Branding*):
   1. User type **External** > **Create**.
   2. App name `DataForce`, your email as support and developer contact > **Save and continue**.
   3. **Data access / Scopes** > **Add or remove scopes**. Add `openid`, `.../auth/userinfo.email`
      and the restricted scope `https://www.googleapis.com/auth/gmail.readonly`
      (Gmail API, "View your email messages and settings") > **Update** > **Save**.
   4. **Audience / Test users** > **Add users** > enter your own Gmail address > **Save**.
   5. Keep the publishing status **Testing**. Do not submit for verification: it is only for you.
5. **APIs & Services > Credentials > Create credentials > OAuth client ID**:
   1. Application type **Desktop app**. Name `DataForce local`. **Create**.
   2. Copy the **Client ID** and the **Client secret** (Google calls the secret non-confidential for
      desktop apps, but DataForce still stores it sealed).
   3. A Desktop client accepts any loopback address `http://127.0.0.1:<port>`, so there is no
      redirect field to fill in.
6. In DataForce: **Settings > Mailbox > Gmail**, paste the client id and secret > **Save client** >
   **Connect Gmail**. Google warns "Google hasn't verified this app": **Advanced > Go to DataForce
   (unsafe)** (it is your own app), then allow the read-only access.

Testing-mode caveat: Google expires refresh tokens of apps in Testing after **7 days**. After a
week, Gmail shows "needs reconnect" and you click **Reconnect Gmail** (one click). Publishing the
app to production would lift this but requires Google's verification of the restricted scope, which
is not worth it for personal use.

## Microsoft (Outlook, Microsoft 365)

1. Go to <https://entra.microsoft.com/> and sign in (a work, school or personal Microsoft account).
2. **Entra ID > App registrations > New registration**.
3. Name `DataForce local`. **Supported account types**: choose
   *Accounts in any organizational directory and personal Microsoft accounts* (works for Outlook.com
   and for Microsoft 365 mailboxes). If your organisation only allows its own tenant, choose
   *this directory only* and also set `MAILBOX_MICROSOFT_TENANT=<your tenant id>` in `backend/.env`.
4. **Redirect URI**: platform **Public client/native (mobile & desktop)**, value
   `http://localhost/api/mailbox/callback` (with the path, without a port). Click **Register**.
   Microsoft ignores the port of a `localhost` redirect, so the `:8800` that DataForce sends
   matches, but the path must be the same. Do not use `127.0.0.1`, which the portal refuses.
5. In the app: **Authentication** > confirm that the platform **Mobile and desktop applications**
   lists `http://localhost/api/mailbox/callback` > **Allow public client flows** = **Yes** >
   **Save**. If sign-in later says the reply URL does not match (error `AADSTS50011`), check this
   address character by character.
6. **API permissions > Add a permission > Microsoft Graph > Delegated permissions**: tick
   `Mail.Read`, `offline_access` and `User.Read` > **Add permissions**. (`Mail.Read` is read-only.
   `Grant admin consent` is only needed if your organisation blocks user consent.)
7. **Overview**: copy the **Application (client) ID**. A public client needs no secret: leave the
   secret field empty in DataForce (only add one if you created a confidential client).
8. In DataForce: **Settings > Mailbox > Outlook**, paste the client id > **Save client** >
   **Connect Outlook** and accept the read-only permissions.

## After connecting

- **Sync now** reads the last 30 days, at most 500 emails (`MAILBOX_LOOKBACK_DAYS`,
  `MAILBOX_MAX_MESSAGES` in `backend/.env`).
- Only emails where a participant is a known contact (an email found by enrichment) or on an
  account's company domain (free webmail such as gmail.com is ignored) are stored, as metadata
  only. A body is fetched only when you press **Link** on an email.
- **Disconnect** deletes the access and the unlinked emails; linked emails stay as deal activities.
- Client ids can also be set as `MAILBOX_GOOGLE_CLIENT_ID` / `MAILBOX_GOOGLE_CLIENT_SECRET` /
  `MAILBOX_MICROSOFT_CLIENT_ID` in `backend/.env`; values entered in Settings take precedence.
