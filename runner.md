cp .env.example .env          # Add your Dhan credentials
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python tools/download_data.py  --intraday --interval 5  # Generate test data
python run_backtest.py --csv data/nifty_intraday_5m.csv --trades --export
python run_live.py --mode paper        # Paper trading




for frontend 
python run_api.py --reload // api server
npm run dev // for UI











NIFTY (daily, last 90 days)

python tools/download_data.py --symbol NIFTY --security-id 13 --exchange IDX_I --instrument INDEX --days 90
BANKNIFTY (daily, last 90 days)

python tools/download_data.py --symbol BANKNIFTY --security-id 25 --exchange IDX_I --instrument INDEX --days 90
SENSEX (daily, last 90 days)

python tools/download_data.py --symbol SENSEX --security-id 1 --exchange IDX_I --instrument INDEX --days 90
NIFTY intraday 5m (last 5 trading days)

python tools/download_data.py --intraday --interval 5
BANKNIFTY intraday 1m

python tools/download_data.py --symbol BANKNIFTY --security-id 25 --exchange IDX_I --instrument INDEX --intraday --interval 1
Custom date range

python tools/download_data.py --from-date 2025-01-01 --to-date 2025-06-30 --days 365
Equity (e.g., RELIANCE)

python tools/download_data.py --symbol RELIANCE --security-id 2885 --exchange NSE --instrument EQUITY
