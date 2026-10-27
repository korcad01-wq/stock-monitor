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


_guard_cache = {}


def buy_guard(cfg):
    """신규 매수 전 시장 점검. (막는 이유 또는 None, 매수 비중 배수, 설명).
    리플은 비트코인을 따라가므로 비트코인 하락장·급락을 먼저 본다. API 호출은 60초 캐시."""
    import time
    key = (cfg['market'], cfg.get('rapid_drop_pct'), cfg.get('btc_drop_pct'), cfg.get('buy_in_downtrend'))
    hit = _guard_cache.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    res = (None, 1.0, '')
    try:
        th = cfg.get('rapid_drop_pct')
        if th and rapid_drop(cfg['market'])[0] <= th:
            res = (f"{cfg['market']} 1시간 급락 중({th}% 이하) → 진정될 때까지 매수 중단", 0, '')
        bth = cfg.get('btc_drop_pct')
        if not res[0] and bth and cfg['market'] != 'KRW-BTC' and rapid_drop('KRW-BTC')[0] <= bth:
            res = (f'비트코인 1시간 급락 중({bth}% 이하) → 매수 중단', 0, '')
        mode = cfg.get('buy_in_downtrend', 'half')
        if not res[0] and cfg.get('regime_enabled', True) and mode != 'allow':
            regime, desc = btc_regime(cfg)
            if regime == 'down':
                res = (f'하락장({desc}) → 매수 중단', 0, '') if mode == 'block' else \
                      (None, 0.5, f'하락장({desc}) → 매수 비중 절반')
    except Exception:  # 시세를 못 읽으면 막지 않는다(다른 규칙은 그대로)
        pass
    _guard_cache[key] = (time.time(), res)
    return res


def stop_check(cfg, st, price, entry, notify, key='stop'):
    """평단 대비 손절선(-sl%) 경보. 더 떨어지면 stop_step %p 마다 다시 울리고,
    손절선 위로 0.5%p 회복하면 처음부터 다시 감시한다. 반환: 평단 대비 %."""
    pr = (price / entry - 1) * 100
    line = -abs(float(cfg.get('sl') or 2))
    step = abs(float(cfg.get('stop_step') or 3))
    done = st.get(key)  # 마지막으로 울린 단계(0 = 손절선, 1 = 한 단계 더 아래 …)
    if pr > line + 0.5:
        st.pop(key, None)
        return pr
    if pr <= line and not alerts.in_quiet_hours(cfg, _now()):  # 방해금지 중이면 끝난 뒤 울린다
        n = int((line - pr) // step)
        if done is None or n > done:
            extra = f' — 손절선보다 {line - pr:.1f}%p 더 내려감' if n else ''
            notify(f"{cfg['market']} 손절 규칙 경보" + (f' {n + 1}단계' if n else ''),
                   f'평단 {entry:,.2f}원 → 현재 {price:,.2f}원 ({pr:+.2f}%, 손절선 {line}%){extra} → 규칙: 매도 검토')
            st[key] = n
    return pr


def cross_proximity(closes, short=20, long=60, look=5):
    """단기선이 장기선 아래일 때 간격(%)과, 최근 look봉 속도로 좁혀지면 몇 봉 뒤 만나는지.
    반환: (간격%, 예상 봉 수 또는 None) — 이미 위면 간격이 양수, 벌어지는 중이면 예상 None."""
    if len(closes) < long + look:
        return None, None
    ma = lambda n, end: sum(closes[end - n:end]) / n
    n = len(closes)
    gap = (ma(short, n) / ma(long, n) - 1) * 100
    gap0 = (ma(short, n - look) / ma(long, n - look) - 1) * 100
    speed = (gap - gap0) / look  # 봉당 좁혀지는 폭(%p)
    if gap >= 0 or speed <= 0:
        return gap, None
    return gap, -gap / speed


def digest_text(watch=None):
    """관심 종목 하루 요약. 일봉 기준(완성된 봉만): 20일선 위/아래, 20/60 골든·데드크로스.
    실시간 알림은 보유 종목만 받고 나머지는 이 요약 하나로 본다(알림 피로 방지). 반환: (제목, 본문)."""
    from .config import WATCHLIST, COIN_NAMES
    watch = watch or WATCHLIST
    tk = upbit.tickers(watch)
    lines, above, crosses, near = [], 0, [], []
    for m in watch:
        coin = m.split('-')[1]
        name = COIN_NAMES.get(coin, coin)
        c = [b['c'] for b in upbit.candles(m, 'day', count=70)[:-1]]  # 진행 중인 오늘 봉은 뺀다
        gap, eta = cross_proximity(c)
        if eta is not None:
            near.append((eta, f'{name} 간격 {gap:.1f}%, 좁혀지는 중(지금 속도면 약 {eta:.0f}일)'))
        ma = lambda n, end: sum(c[end - n:end]) / n
        t = tk.get(m, {'price': c[-1], 'change_rate': 0})
        pos = ''
        if len(c) >= 21:
            up = c[-1] > ma(20, len(c))
            above += up
            pos = '20일선 위' if up else '20일선 아래'
        if len(c) >= 61:
            a0, b0, a1, b1 = ma(20, len(c) - 1), ma(60, len(c) - 1), ma(20, len(c)), ma(60, len(c))
            if a0 <= b0 and a1 > b1:
                crosses.append(f'🟢 {name} 일봉 골든크로스(20/60)')
            elif a0 >= b0 and a1 < b1:
                crosses.append(f'🔻 {name} 일봉 데드크로스(20/60)')
        px = f"{t['price']:,.0f}" if t['price'] >= 100 else f"{t['price']:,.4g}"
        lines.append(f"{name} {px}원 {t['change_rate']:+.1f}% · {pos}")
    head = f'20일선 위 {above}개 / 아래 {len(watch) - above}개'
    near = [f'  {t}' for _, t in sorted(near)[:3]]
    body = '\n'.join([head] + (crosses or ['새 일봉 크로스 없음'])
                     + (['일봉 골든크로스 가까운 순:'] + near if near else []) + [''] + lines)
    return f'관심 종목 요약 ({_now():%m/%d %H:%M})', body


def run_digest(cfg, st, notify=None):
    """하루 한 번 digest_time(한국 시간) 이후 첫 실행에서 요약을 보낸다. 클라우드 감시에서만 부른다(PC와 중복 방지)."""
    if not cfg.get('digest_enabled', True):
        return
    now = _now()
    if f'{now:%H:%M}' < cfg.get('digest_time', '08:00') or st.get('digest_day') == f'{now:%Y-%m-%d}':
        return
    if alerts.in_quiet_hours(cfg, now):
        return
    title, body = digest_text()
    (notify or alerts.notify)(title, body, 'info')  # 휴대폰에서는 소리 없이(낮음)
    st['digest_day'] = f'{now:%Y-%m-%d}'


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

    # 2-1) 비트코인 1시간 급락: 리플은 보통 비트코인을 따라 늦게 빠진다
    bth = cfg.get('btc_drop_pct')
    if bth and market != 'KRW-BTC':
        drop, high = rapid_drop('KRW-BTC')
        # 진정 알림 뒤 다시 급락하면 30분 지나서부터 다시 알린다(기준선 근처 오락가락 방지)
        if drop <= bth and not st.get('btc_drop_on') and now.timestamp() - st.get('btc_rapid_at', 0) > 1800 and not quiet:
            notify(f'비트코인 급락 경보 (1시간 {drop:+.1f}%)',
                   f'비트코인 1시간 최고 대비 {drop:+.1f}% | {market}도 따라 빠질 수 있음 '
                   f'→ 모의 매수 중단(진정되면 다시 알림), 손절선 확인', 'warn')
            st['btc_rapid_at'] = now.timestamp()
            st['btc_drop_on'] = True
        elif drop > bth and st.get('btc_drop_on') and not quiet:  # buy_guard 와 같은 기준으로 풀린다
            notify('비트코인 급락 진정 → 모의 매수 재개',
                   f'비트코인 1시간 최고 대비 {drop:+.1f}% (기준 {bth}%) | 하락장 비중 규칙은 그대로 적용', 'event')
            st.pop('btc_drop_on', None)

    # 3) 하락장 판정 → 골든크로스 경고 + 모의 매수 비중(buy_in_downtrend). 상태나 설정이 바뀔 때 한 번 알림
    caution = ''
    if cfg.get('regime_enabled', True):
        regime, desc = btc_regime(cfg)
        if regime == 'down':
            caution = f'⚠ 하락장({desc}): 차트 신호 신뢰도 낮음'
        mode = cfg.get('buy_in_downtrend', 'half')
        if mode not in ('block', 'allow'):
            mode = 'half'
        cur, sent_r = f'{regime}|{mode}', st.get('regime_sent')
        if regime in ('down', 'normal') and cur != sent_r and not quiet:
            ps = cfg.get('position_size', 100)
            if regime == 'down':
                title, body = {
                    'half': ('비트코인 하락장 → 모의 매수 비중 절반', f'1회 매수 현금의 {ps:g}% → {ps / 2:g}%'),
                    'block': ('비트코인 하락장 → 모의 매수 중단', '하락장을 벗어나면 다시 알림'),
                    'allow': ('비트코인 하락장 진입', '매수 비중은 그대로(allow 설정)'),
                }[mode]
                notify(title, f'{desc} | {body} | 골든크로스 신호는 경고를 붙여 보냅니다', 'event')
            elif sent_r and sent_r.startswith('down'):  # 처음 켰을 때 정상장이면 조용히 기록만
                notify('하락장 벗어남 → 모의 매수 원래대로', f'{desc} | 1회 매수 현금의 {ps:g}%', 'event')
            st['regime_sent'] = cur
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
    # 4-1) 앞으로 남은 일정이 없으면 한 달에 한 번 추가하라고 알린다
    month = f'{now:%Y-%m}'
    if not quiet and st.get('events_empty') != month and not any(at > now for at, _ in parse_events(cfg)):
        notify('경제 일정 추가 필요', '등록된 FOMC·CPI 일정이 모두 지났습니다 → 새 일정을 config 의 events 에 넣고 stock cloud config', 'info')
        st['events_empty'] = month
    st['event_sent'] = sorted(sent)[-40:]
    return caution
