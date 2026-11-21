# n8n orchestration for Agent 5 (WhatsApp alerts)

Agent 5 sends every alerting triage (severity **High**) to this n8n workflow. n8n checks a shared
secret, decides whether to alert, and sends the WhatsApp message with its Twilio node, or returns
`mocked` in test mode. If n8n is not configured or not reachable, the backend falls back to the direct
Twilio path. The channel used (`n8n`, `twilio_direct` or `mocked`) is stored in the alert log and the
agent trace.

```text
FastAPI (Agent 5) --POST /webhook/triage-alert--> [Webhook] -> [Check secret] -> [Severity needs alert?]
                                                                   | no: 401             | no: {"status":"skipped"}
                                                                   v                     v yes
                                                            [Twilio test mode?] -- yes --> [Test mode - do not send] -> {"status":"mocked"}
                                                                   | no
                                                                   v
                                                         [Send WhatsApp (Twilio)] -> {"status":"sent","message_sid":"SM..."}
```

## Files

| File | Purpose |
|---|---|
| `triage_alert_workflow.json` | Importable workflow (10 nodes) |
| `README.md` | This guide |

## Request and response

`POST http://localhost:5678/webhook/triage-alert`, header `X-Webhook-Secret: <N8N_WEBHOOK_SECRET>`

```json
{"session_id": "8b7c...", "severity": "High", "chief_complaint": "Crushing central chest pain ...",
 "reasoning": "Cardiac features ...", "news2_score": 6, "low_evidence": false,
 "created_at": "2026-11-21T00:57:41", "message": "🚨 TRIAGE ALERT — PRIORITY: HIGH ...", "test_mode": true}
```

Responses: `{"status": "mocked" | "sent" | "skipped", "channel": "n8n", "message_sid": null | "SM..."}`,
or HTTP 401 `{"status": "unauthorized"}` when the secret is wrong.

Backend settings: timeout `N8N_TIMEOUT_SECONDS=5`, `N8N_MAX_RETRIES=2` (network errors and 5xx), then
fallback to direct Twilio.

## Run n8n locally (free)

Requirements: Node.js 24 or newer (`node -v`). Docker also works (`docker run -it --rm -p 5678:5678 n8nio/n8n`).

1. Pick a long random secret and use it in **both** places below (never commit it).
2. Start n8n in PowerShell (the environment variables let the workflow read the secret and the
   WhatsApp numbers):

   ```powershell
   $env:N8N_BLOCK_ENV_ACCESS_IN_NODE = "false"
   $env:TRIAGE_WEBHOOK_SECRET = "<your secret>"
   $env:TWILIO_WHATSAPP_FROM = "+14155238886"      # Twilio WhatsApp sandbox number
   $env:DOCTOR_WHATSAPP_NUMBER = "<your phone, +44...>"
   npx n8n
   ```

3. In the project `.env` add:

   ```text
   N8N_WEBHOOK_URL=http://localhost:5678/webhook/triage-alert
   N8N_WEBHOOK_SECRET=<your secret>
   ```

   Keep `TWILIO_TEST_MODE=true` until you want a real WhatsApp message (then `false`).

## First-time setup in the browser (click by click)

1. Open <http://localhost:5678>. Fill in the **Set up owner account** form (email, name, password: your
   choice, stored only on your computer) and click **Next**. Skip the optional survey.
2. On the **Overview** page click **Create Workflow** (or the **+** button, top left).
3. Click the **⋯** menu (top right) → **Import from File...** → select `n8n/triage_alert_workflow.json`.
4. Double-click the **Send WhatsApp (Twilio)** node → **Credential to connect with** → **Create New
   Credential** → paste your Twilio **Account SID** and **Auth Token** → **Save** → close the node.
   n8n 2.x will not publish a workflow whose Twilio node has no credential. If you only want test mode
   (`TWILIO_TEST_MODE=true`), any placeholder values work (for example SID `ACtest`, token `test`),
   because the test-mode branch never calls Twilio.
5. Click **Save** (top right), then click **Publish** (top right). The webhook becomes live a few
   seconds later.
6. Test: run a High demo case in the app (Clinician Intake → **Demo: High** → **Run triage**). The card shows
   `Alert (Agent 5): mocked via n8n` (or `sent via n8n`). In n8n open **Executions** (left menu) to see the
   run: take the screenshot of the canvas and the successful execution for the report.

## Verified locally (21 Nov 2026, n8n 2.48.7, Node 24.14.0)

| Request | Response |
|---|---|
| High, correct secret, `test_mode: true` | `{"status":"mocked","channel":"n8n","message_sid":null,"session_id":"t1"}` |
| Medium, correct secret | `{"status":"skipped","channel":"n8n","message_sid":null,"reason":"severity Medium does not alert"}` |
| wrong secret | HTTP 401 `{"status":"unauthorized","channel":"n8n"}` |
| backend `N8nOrchestrator.send()` -> real n8n | `{"status":"mocked","channel":"n8n","message_sid":null}`; `health()` -> `{"configured":true,"reachable":true}` |

CLI alternative used for the test above (no browser): `npx n8n import:workflow --input=n8n/triage_alert_workflow.json`,
then `npx n8n publish:workflow --id=<id>` (needs a Twilio credential on the node first).

## Hugging Face Space

The Space cannot reach an n8n running on your own computer, so on the Space `N8N_WEBHOOK_URL` is left
unset and Agent 5 uses the direct Twilio path (or `mocked`). The n8n channel is demonstrated locally.
