# Web (S3)

Operator UI. React + Vite. Compose port **5173**.

Talks **only** to control (`:8081`) via the Vite `/api` proxy. Does not inject. Does not bypass the clerk.

- Catalog (three experiments)
- Create draft
- Approve + unseal (one click; clerk still unseals). Separate Unseal remains.
- Abort reseals
- Timeline + last seal

## Local

Control must be on `:8081`.

```
cd apps/web
npm install
npm run dev
```

Open http://localhost:5173
