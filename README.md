# Crypto AI Trader

Local-first AI-assisted cryptocurrency quantitative trading system.

The first implementation target is automatic paper trading for Binance spot with:

- Medium-frequency 15m/1h signals
- 4h trend context
- AI scoring for rule-generated candidates
- Dynamic risk profiles
- SQLite storage
- Local dashboard API
- Telegram notifications in a later milestone

## Safety

The default mode is paper trading.

Live trading must remain locked until the approved live unlock milestones are implemented and reviewed.

## First Local Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn trading.main:app --reload
```
