# Crypto AI Trader Dashboard

Local control room for the crypto-ai-trader system.

## Getting Started

```bash
cd dashboard
npm install
npm run dev
```

The dashboard consumes the backend API at `http://127.0.0.1:8000` by default.

Override the API base URL:

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

## Mode

This dashboard is **read-only** and **paper-mode oriented**. No trade execution, live trading controls, or API key handling is available.

## Troubleshooting

### Dashboard panels show "offline" or API errors

The dashboard expects the backend at `http://127.0.0.1:8000`. If the backend is not running:

```bash
# In the backend tab
make backend
```

### CORS blocked requests

Both `http://127.0.0.1:5173` and `http://localhost:5173` are valid dashboard origins. If you see CORS errors:

1. Check the URL in your browser address bar — use whichever host (`127.0.0.1` or `localhost`) is printed in the Vite startup output
2. Be consistent: do not switch between `127.0.0.1` and `localhost` in the same browser session, as they may be treated as separate origins

### Dashboard loads but panels are empty

1. Run at least one runtime cycle: `make runtime-once`
2. Check the backend health: `curl http://127.0.0.1:8000/health`
3. Check the runtime status: `curl http://127.0.0.1:8000/runtime/status`

If the runtime has never run, there is no data to display.

