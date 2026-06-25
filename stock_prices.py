"""
관심 종목 전일 등락폭 수집 모듈
- watchlist.txt 에 등록된 티커의 전날 종가 및 등락률 조회
- yfinance 사용 (무료, API 키 불필요)
"""
import os
import datetime
from datetime import timedelta, timezone
from pathlib import Path

import yfinance as yf

KST = timezone(timedelta(hours=9))
ALERT_THRESHOLD = 3.0  # ±3% 이상 시 알림


def get_trading_day_prices(tickers: list[str], target_date: datetime.date) -> list[dict]:
    results = []
    # 주말/미국 휴장일 대비 넉넉하게 5일치 조회 후 최근 2거래일 사용
    start = target_date - timedelta(days=7)
    end = target_date + timedelta(days=1)

    for ticker in tickers:
        ticker = ticker.strip().upper()
        if not ticker:
            continue
        try:
            data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
            if data.empty or len(data) < 1:
                print(f"  {ticker}: 데이터 없음 (미국 휴장일 또는 상장 전)")
                continue

            latest = data.iloc[-1]
            prev = data.iloc[-2] if len(data) >= 2 else None

            close = float(latest['Close'].iloc[0] if hasattr(latest['Close'], 'iloc') else latest['Close'])
            prev_close = None
            if prev is not None:
                prev_close = float(prev['Close'].iloc[0] if hasattr(prev['Close'], 'iloc') else prev['Close'])

            change_pct = ((close - prev_close) / prev_close * 100) if prev_close else None

            result = {
                'ticker': ticker,
                'date': str(data.index[-1].date()),
                'close': round(close, 2),
                'prev_close': round(prev_close, 2) if prev_close else None,
                'change_pct': round(change_pct, 2) if change_pct is not None else None,
                'alert': (abs(change_pct) >= ALERT_THRESHOLD) if change_pct is not None else False,
            }
            results.append(result)

            if change_pct is not None:
                arrow = "⚠️ " if result['alert'] else ""
                print(f"  {ticker}: ${close:.2f} ({change_pct:+.1f}%) {arrow}")
            else:
                print(f"  {ticker}: ${close:.2f} (전일 비교 불가)")

        except Exception as e:
            print(f"  {ticker}: 조회 실패 - {e}")

    return results


def collect_stock_prices(watchlist_file: str = "watchlist.txt") -> list[dict]:
    """
    관심 종목 전일 종가 및 등락폭 수집.
    반환: [{'ticker', 'date', 'close', 'prev_close', 'change_pct', 'alert'}, ...]
    """
    if not os.path.exists(watchlist_file):
        print(f"⚠️  {watchlist_file} 없음, 등락폭 수집 건너뜀")
        return []

    lines = Path(watchlist_file).read_text(encoding='utf-8').splitlines()
    tickers = [l.strip().upper() for l in lines if l.strip() and not l.startswith('#')]

    if not tickers:
        print("⚠️  watchlist.txt 에 종목이 없음")
        return []

    target_date = (datetime.datetime.now(KST) - timedelta(days=1)).date()
    print(f"\n=== [관심 종목 등락폭] 대상: {target_date} | {len(tickers)}개 종목 ===")

    results = get_trading_day_prices(tickers, target_date)

    alerts = [r for r in results if r['alert']]
    print(f"  ✔️ {len(results)}건 수집 완료 | ±{ALERT_THRESHOLD}% 이상: {len(alerts)}건\n")
    return results
