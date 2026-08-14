# Pulse web

The reviewer app. Not a dashboard. Money at the top.

```
sign in → import CSV → run rules → confirm / dismiss → download pack
```

## Run (API must already be up on :8000)

```powershell
cd web
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/auth`, `/imports`, `/runs`, `/exceptions`, `/reports` to the API.

An operator creates the login. There is no self-serve signup. In local `ENV=dev` the API seeds `admin@pulse.local`.

## Build

```powershell
npm run build
```

`dist/` is gitignored. A later single-tenant deploy serves this folder behind Caddy next to the API.

## What this is not

The page on accumo.co/pulse is a **browser sales demo**. This app is the product. It talks to the real API and stores nothing in the browser except the session cookie.
