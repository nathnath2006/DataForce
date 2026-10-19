# SR19 - M4 phase 2: saved models and scoring, opt-in GenAI, mailbox

Scope: the uncommitted M4 phase-2 code (2026-10-19):
- **Models:** saved models and scoring (`services/saved_models.py`, `flows/scoring.py`, `routes/saved_models.py`, the `score`, `velocity`, `engagement` and `touchpoint` blocks, the Models tab).
- **GenAI:** opt-in GenAI on deals and accounts (`services/genai.py`, `routes/genai.py`, `src/genai/**`).
- **Mailbox:** Gmail and Outlook linking (see the mailbox section below).

Method: one read-only Sonnet verifier per area, plus browser checks by the tech lead.

## Opt-in GenAI: 0 high, 1 medium, 3 low (all fixed)

### SR19-G1 (medium) The number check in summaries was a substring test
- **Where:** `services/genai.py`.
- **Failure:** a number written by the model passed if its digits appeared anywhere in the cited text. "4" passed inside "40000", "1" inside "2025", "400" as a prefix of "40000".
- **Fix:** numbers are compared as whole tokens, and thousands separators are normalised (10,000 = 10.000 = 10000).
- **Test:** `test_numbers_must_match_whole_tokens_and_titles_carry_no_markup`.

### SR19-G2 (low) Task titles are free model text
- A verbatim quote can carry any title, for example from an injected note.
- **Guard:** a person must accept every suggested task, and the quote is shown with the title.
- **Fix:** titles containing `<`, `>` or a link are dropped. Test as above.

### SR19-G3 (low) The consent button had no re-entry guard
- **Fix:** a ref guard in `DealAiPanel.confirm`. The daily cap and the budget already bounded the damage.

### SR19-G4 (low) No GenAI-specific erasure test
- **Fix:** `test_erasing_a_contact_masks_ai_task_evidence`. A contact's full name is masked in an AI task's quote on erasure. A first name alone is left as is, which is the existing documents rule (it is ambiguous).

### Passed
- **Untrusted text:**
  - every item is wrapped as untrusted, with look-alike tags neutralised and NFKC applied;
  - the prompts say the data are not instructions;
  - citations must be real item ids of this deal or account;
  - quotes must be verbatim in the named item, 12 to 300 characters.
- **Consent:**
  - the preview never calls the model;
  - only the POST does, after the dialog;
  - with no key, the answer is a 409.
- **Isolation:** every source query is filtered by workspace and by deal or account, and another workspace's id gives a 404.
- **Budget and logging:**
  - the budget is taken before the call, so failures count;
  - errors are sanitised;
  - `llm_call` stores no prompt or answer text.
- **Tasks:** they are created as `suggested` / `ai_suggested`, and the evidence holds only the quote and its origin.

## Saved models and scoring: 0 high, 1 medium, 4 low

### SR19-M1 (medium) An RBF model stores training rows
- SVM and SVR support vectors are training rows, up to 2,000 (MAX_EXPORTED_SV), stored as standardised numbers. They survive the erasure of a contact. Workspace deletion cascades.
- **Decision:** accepted as a residual risk.
  - Features are deal and account columns, not contact identifiers.
  - *Save model* now says how many training rows an RBF model stores, that a linear kernel stores none, and that deleting the model removes them.
- **Not done:** linking a saved model to the rows it was trained on, to delete it on erasure. Revisit when models train on contact-level data.

### SR19-M2 (low) The scorer did not validate parameter shapes
- **Failure:** a mismatched or missing key gave an unhandled 500.
- **Fix:** `score_frame` turns ValueError, KeyError, TypeError and IndexError into a clear ScoringError (422). K-means distances are computed in chunks of 5,000 rows instead of rows × centroids × features at once.
- **Test:** `test_parameters_that_do_not_fit_give_a_scoring_error`.

### SR19-M3 (low) Non-finite parameters reached JSONB
- **Fix:** the size check uses `json.dumps(allow_nan=False)`. NaN or infinity gives a 422, not a database error.

### SR19-M4 (low) Scoring ran outside the analysis slot
- **Fix:** *Score now* takes an analysis slot and the 20 s budget, like a viz query.

### SR19-M5 (low) The 200-model cap is a count then an insert
- Two concurrent saves can overshoot by one. Accepted on a single-user local app; revisit with M3b.

### Passed
- **Isolation:** every saved-model query is scoped. `resolve_models` filters by workspace, so a `score` block cannot use another workspace's model.
- **Trust:** saving re-runs the saved flow on the server and stores only its own parameters, metrics and status. No route accepts parameters or a status from the client.
- **Formats:** no pickle, joblib or eval.
- **Limits:** scoring returns at most 200 rows, and the velocity and engagement outputs are bounded.
- **Frontend:** no HTML rendering; *Save model* is hidden while the flow has unsaved changes.

## Mailbox (Gmail, Outlook): 0 high, 1 medium, 3 low

### SR19-B1 (medium) HTML-to-text was quadratic on unterminated tags
- **Where:** `connectors/mailbox/base.py`. The regexes for `<script…</script>` and tags were run before the 10,000-character cap.
- **Measured:** 160k characters of `<script ` took 11 s, and 200k of `<` took 15 s.
- **Failure:** linking one crafted email froze a worker thread.
- **Fix:** the text is extracted with the standard library's `HTMLParser`, which is linear. The same inputs now take at most 0.1 s. Script, style, head and title content is dropped, the collected text is bounded, and the input is cut at 2 MB.
- **Test:** `test_html_to_text_is_linear_on_unterminated_tags`.

### SR19-B2 (low) The Gmail redirect follows the Host header
- **Where:** `oauth.redirect_uri_for`. The redirect is `127.0.0.1` or `localhost`, on the UI or Vite port.
- **Kept on purpose:**
  - the binding cookie is host-only, so the callback must return to the host the browser used;
  - a Google *Desktop app* client accepts any loopback address;
  - the Host header is already limited to loopback names on those two ports.
- `docs/MAILBOX-SETUP.md` says which address to open.

### SR19-B3 (low) Outlook login CSRF, residual
- **Cause:** the callback comes back on `localhost`, so the `127.0.0.1` cookie is not sent, and a missing cookie is tolerated for Outlook.
- **What still binds the callback:**
  - the state is created only by an Origin-guarded POST;
  - it is 256-bit random, single-use, hashed and expiring;
  - PKCE.
- **Residual:** another local process that learns the state could race the callback. This is accepted on a single-user loopback app. Settings shows the connected account address, so a wrong mailbox is visible.
- **Revisit with hosting (M3b).**

### SR19-B4 (low) The refresh token was dropped in memory after a Google refresh
- Google does not rotate refresh tokens, so later calls in the same request saw none. The stored token was already correct.
- **Fix:** `tokens.refresh_token or grant.refresh`.

### Passed
- **OAuth:** PKCE S256, and a hashed, single-use, expiring state bound to workspace and provider. `invalid_grant` marks the connection for reconnection, and callback inputs are bounded.
- **Scopes:** read-only and minimal. Gmail uses `gmail.readonly`. Outlook uses `Mail.Read`, `User.Read`, `openid email` and `offline_access`.
- **Secrets:** the client secret, tokens and account address are sealed. Error messages are clipped and carry no token.
- **Minimisation:**
  - only candidate emails are stored, where a participant is a CRM contact or the address is on an account's company domain;
  - subject at most 300 characters, snippet 200, 20 addresses;
  - the body is fetched only when an email is linked, capped at 10,000 characters;
  - the sync run row holds counts only.
- **GDPR:** erasing a contact deletes the stored emails naming it. Disconnecting deletes the tokens and unlinked emails. Workspace deletion cascades.
- **Requests:** every mutation is a guarded POST, PUT or DELETE. The only GET that writes is the OAuth callback, as for TamTam.
- **Frontend:** email text is rendered as text, and the secret fields are write-only.
- **Docs:** the redirect addresses and scopes match the code. The Outlook step now names the exact redirect `http://localhost/api/mailbox/callback`.
