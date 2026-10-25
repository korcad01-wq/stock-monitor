"""업비트 공개 시세 API (인증 불필요, 조회 전용)."""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = 'https://api.upbit.com/v1'
MINUTE_UNITS = {'1', '3', '5', '10', '15', '30', '60', '240'}


def _get(path, params):
    url = f'{BASE}{path}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1 + attempt)


def ticker(market):
    """현재가. change_rate 는 업비트 기준(전일 종가 대비, 09:00 KST 경계) 하루 등락률(%)."""
    d = _get('/ticker', {'markets': market})[0]
    return {
        'price': d['trade_price'],
        'open': d['opening_price'],
        'prev_close': d['prev_closing_price'],
        'change_rate': d['signed_change_rate'] * 100,
        'ts': d['timestamp'] / 1000,
    }


def markets():
    return [m['market'] for m in _get('/market/all', {'isDetails': 'false'}) if m['market'].startswith('KRW-')]


def candles(market, interval, count=None, days=None):
    """과거→최신 순 봉 목록. 마지막 봉은 아직 진행 중일 수 있다.

    각 봉: {'t': UTC 시작시각 문자열, 'o','h','l','c','v'}
    """
    interval = str(interval)
    path = '/candles/days' if interval == 'day' else f'/candles/minutes/{interval}'
    if interval != 'day' and interval not in MINUTE_UNITS:
        raise ValueError(f'지원하지 않는 봉 단위: {interval}')
    if count is None:
        per_day = 1 if interval == 'day' else 1440 // int(interval)
        count = max(1, int(days * per_day))
    out, to = {}, None
    while len(out) < count:
        params = {'market': market, 'count': min(200, count - len(out))}
        if to:
            params['to'] = to
        data = _get(path, params)
        if not data:
            break
        for d in data:
            out[d['candle_date_time_utc']] = {
                't': d['candle_date_time_utc'], 'o': d['opening_price'], 'h': d['high_price'],
                'l': d['low_price'], 'c': d['trade_price'], 'v': d['candle_acc_trade_volume'],
            }
        to = data[-1]['candle_date_time_utc'] + 'Z'
        if len(data) < params['count']:
            break
        time.sleep(0.12)  # 초당 요청 제한 회피
    return [out[k] for k in sorted(out)]


def kst_now():
    return datetime.now(timezone(timedelta(hours=9)))


def trading_day(ts=None):
    """업비트 일봉 경계(09:00 KST = 00:00 UTC) 기준 날짜."""
    dt = datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)
    return dt.strftime('%Y-%m-%d')
