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

The backend only allows origins `http://127.0.0.1:5173` and `http://localhost:5173`. If you see CORS errors:

1. Make sure you are accessing the dashboard at `http://localhost:5173` (not `http://127.0.0.1:5173` or a different port)
2. The Vite dev server port is printed in its startup output — use exactly that URL

### Dashboard loads but panels are empty

1. Run at least one runtime cycle: `make runtime-once`
2. Check the backend health: `curl http://127.0.0.1:8000/api/health`
3. Check the runtime status: `curl http://127.0.0.1:8000/api/runtime/status`

If the runtime has never run, there is no data to display.

