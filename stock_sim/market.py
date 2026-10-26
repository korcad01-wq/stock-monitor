"""차트 밖 위험 알람: 하락장 판정, 1시간 급락, 경제 일정(FOMC·CPI), 하루 손실 한도.

이번 하락처럼 원인이 금리·유가·전쟁·ETF 자금이면 골든크로스 같은 차트 신호가 잘 안 맞는다.
그래서 (1) 시장 전체가 하락장인지 알려 신호에 경고를 붙이고, (2) 큰 일정 앞뒤로 매수를 자제시키고,
(3) 레버리지 청산으로 커지는 급락과 손실 한도를 따로 알린다.
PC 감시(stock watch)와 클라우드 감시(cloud_monitor.py)가 같은 코드를 쓴다. state 는 dict 로 이어받는다.
"""
from datetime import datetime, timedelta, timezone

from . import alerts, upbit

KST = timezone(timedelta(hours=9))


def _now():
    return datetime.now(KST)


def parse_events(cfg):
    out = []
    for e in cfg.get('events') or []:
        try:
            out.append((datetime.fromisoformat(e['at']).astimezone(KST), e['title']))
        except (KeyError, ValueError):
            continue
    return sorted(out)


def event_window(cfg, now=None, hours=None):
    """지금이 일정 전후 N시간 안이면 (시각, 제목), 아니면 None. 모의 매수 차단에 쓴다."""
    h = cfg.get('event_block_hours', 2) if hours is None else hours
    if not h:
        return None
    now = now or _now()
    for at, title in parse_events(cfg):
        if at - timedelta(hours=h) <= now <= at + timedelta(hours=h):
            return at, title
    return None


def btc_regime(cfg):
    """비트코인 일봉 종가가 20일 이동평균 아래면 하락장. (상태, 설명)"""
    c = upbit.candles('KRW-BTC', 'day', count=22)
    closes = [b['c'] for b in c]
    if len(closes) < 21:
        return 'unknown', ''
    ma20 = sum(closes[-21:-1]) / 20  # 어제까지 20일
    price = closes[-1]
    gap = (price / ma20 - 1) * 100
    state = 'down' if gap < 0 else 'normal'
    return state, f'비트코인 20일선 대비 {gap:+.1f}%'


def rapid_drop(market, minutes=60):
    """최근 minutes 분 최고가 대비 현재가 하락률(%)."""
    c = upbit.candles(market, '5', count=minutes // 5 + 1)
    if not c:
        return 0.0, 0.0
    high = max(b['h'] for b in c)
    price = c[-1]['c']
    return (price / high - 1) * 100, high


def run_checks(cfg, st, ticker, notify=None):
    """모든 차트 밖 점검을 한 번 돈다. 반환: 하락장 경고 문구(없으면 '')."""
    notify = notify or alerts.notify
    market = cfg['market']
    now = _now()
    day = upbit.trading_day()
    quiet = alerts.in_quiet_hours(cfg, now)

    # 1) 하루 손실 한도(업비트 하루 등락률)
    lim = cfg.get('max_daily_loss')
    if lim and ticker['change_rate'] <= lim and st.get('halt_day') != day and not quiet:
        notify(f'{market} 하루 {lim}% 한도 도달',
               f"오늘 {ticker['change_rate']:+.2f}% → 규칙: 오늘은 신규 매수 중단, 보유분 손절선 확인", 'warn')
        st['halt_day'] = day

    # 2) 1시간 급락(레버리지 청산 연쇄 대비)
    th = cfg.get('rapid_drop_pct')
    if th:
        drop, high = rapid_drop(market)
        last = st.get('rapid_at', 0)
        if drop <= th and now.timestamp() - last > 2 * 3600 and not quiet:
            notify(f'{market} 급락 경보 (1시간 {drop:+.1f}%)',
                   f'1시간 최고 {high:,.2f}원 → 현재 {ticker["price"]:,.2f}원 | 레버리지 청산 연쇄 가능, 손절선 확인', 'warn')
            st['rapid_at'] = now.timestamp()

    # 3) 하락장 판정(바뀔 때 한 번 알림) → 골든크로스 알림에 경고를 붙이는 데 씀
    caution = ''
    if cfg.get('regime_enabled', True):
        regime, desc = btc_regime(cfg)
        if regime == 'down':
            caution = f'⚠ 하락장({desc}): 차트 신호 신뢰도 낮음'
        prev = st.get('regime')
        if prev and regime != prev and regime in ('down', 'normal') and not quiet:
            notify('시장 하락장 진입' if regime == 'down' else '시장 하락장 벗어남',
                   desc + (' | 골든크로스 신호는 경고를 붙여 보냅니다' if regime == 'down' else ''), 'event')
        if regime in ('down', 'normal'):
            st['regime'] = regime

    # 4) 경제 일정: 발표 전(14시간~1시간 전)과 발표 후(10시간 안) 한 번씩
    sent = set(st.get('event_sent', []))
    for at, title in parse_events(cfg):
        key = at.isoformat()
        when = f'{at:%m/%d(%a) %H:%M}'.replace('Mon', '월').replace('Tue', '화').replace('Wed', '수') \
            .replace('Thu', '목').replace('Fri', '금').replace('Sat', '토').replace('Sun', '일')
        if quiet:
            break
        if f'pre|{key}' not in sent and at - timedelta(hours=14) <= now < at - timedelta(hours=1):
            notify(f'일정 경고: {title}', f'한국시간 {when} 발표 | 전후로 급변동 가능 → 신규 매수 자제, 손절선 확인', 'event')
            sent.add(f'pre|{key}')
        if f'post|{key}' not in sent and at <= now < at + timedelta(hours=10):
            notify(f'{title} 발표됨', f'{when} 발표 | 결과에 따라 변동이 커질 수 있음 → 규칙대로만 매매', 'event')
            sent.add(f'post|{key}')
    st['event_sent'] = sorted(sent)[-40:]
    return caution
