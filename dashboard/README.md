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
