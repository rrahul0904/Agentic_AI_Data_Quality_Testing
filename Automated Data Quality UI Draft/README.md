# Automated Data Quality UI Draft

This is the canonical operator console for the local Automated Data Quality
demo. The backend and hospitality runtime live in the sibling
`Automated Data Quality Testing` directory.

Use the backend launcher for the reproducible production demo:

```bash
cd "/Users/297159/Documents/Agentic_AI/Automated Data Quality Testing"
make demo-ui
```

Open <http://127.0.0.1:3020>.

For direct UI development only:

```bash
npm install
npm run dev -- --hostname 127.0.0.1 --port 3020
```

When the UI is deployed behind authenticated ADE API access, configure these
server-side variables (never expose the API key as a `NEXT_PUBLIC_*` value):

```bash
ADE_API_BASE_URL=http://127.0.0.1:8011
ADE_UI_PROJECT_ID=data-quality-testing-beta
ADE_UI_ENVIRONMENT=development
# Optional server-only credential for ADE_AUTH_MODE=required
ADE_UI_API_KEY=<secret-reference>
```
