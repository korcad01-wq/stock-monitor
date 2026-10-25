"""이동평균선 골든크로스 감시.

여러 분봉(cross_intervals)에서 이평선 쌍(cross_pairs)을 보고
- 임박: 단기선이 장기선 아래에서 올라오며 간격이 cross_approach_gap(%) 이내로 좁혀짐
- 발생: 직전 완성 봉에서 단기선이 장기선을 위로 뚫음
- 정배열: ma_lines 가 짧은 것부터 차례로 위에 놓이는 배열이 새로 완성됨
을 알린다. 프로그램을 켠 시점에 이미 지나간 신호는 알리지 않는다.
"""
import time
from datetime import datetime, timedelta, timezone

from . import alerts, upbit

KST = timezone(timedelta(hours=9))


def _parse_list(s, sep=','):
    return [x.strip() for x in str(s).split(sep) if x.strip()]


def _sma(cl, n, end):
    """cl[:end] 의 마지막 n개 평균. end 는 슬라이스 끝(배타)."""
    return sum(cl[end - n:end]) / n if end >= n else None


def _label(interval):
    return '일봉' if interval == 'day' else f'{interval}분봉'


class CrossWatcher:
    def __init__(self, cfg, market=None):
        self.market = market or cfg['market']
        self.intervals = _parse_list(cfg.get('cross_intervals', '5'))
        self.pairs = [tuple(int(v) for v in p.split('/')) for p in _parse_list(cfg.get('cross_pairs', '5/20'))]
        self.lines = sorted(int(v) for v in _parse_list(cfg.get('ma_lines', '5,10,20,60,120')))
        self.gap = float(cfg.get('cross_approach_gap', 0.15))
        self.enabled = bool(cfg.get('cross_enabled', True))
        self.need = max([l for _, l in self.pairs] + self.lines) + 5
        self.last_bar = {}      # 봉 단위 → 마지막으로 판단한 완성 봉 시각
        self.next_fetch = {}    # 봉 단위 → 다음 조회 시각(요청 수 줄이기)
        self.approach_armed = {}  # (봉, 쌍) → 임박 알림 가능 여부
        self.aligned = {}       # 봉 단위 → 정배열 상태

    def describe(self):
        if not self.enabled:
            return '골든크로스 감시 꺼짐'
        pairs = ', '.join(f'{s}/{l}' for s, l in self.pairs)
        return f"골든크로스 감시 {'·'.join(_label(i) for i in self.intervals)} | 쌍 {pairs} | 임박 {self.gap}% 이내"

    BACKLOG = 60  # 실행이 밀렸을 때 거슬러 확인할 최대 봉 수

    def check(self):
        if not self.enabled:
            return
        now = time.time()
        for iv in self.intervals:
            if now < self.next_fetch.get(iv, 0):
                continue
            self.next_fetch[iv] = now + 20
            c = upbit.candles(self.market, iv, count=self.need + self.BACKLOG + 1)[:-1]  # 진행 중인 봉 제외
            if len(c) < self.need - 4 or c[-1]['t'] == self.last_bar.get(iv):
                continue
            cl = [b['c'] for b in c]
            last = self.last_bar.get(iv)
            if last is None:  # 처음: 현재 상태만 기억하고 알리지 않음
                self._evaluate(iv, cl, cl[-1], True, c[-1]['t'])
            else:
                # 지난번 이후 완성된 봉을 하나씩 따라간다(감시가 밀려도 교차를 놓치지 않게)
                start = max(self.need - 4, len(c) - self.BACKLOG)
                for j in range(start, len(c)):
                    if c[j]['t'] > last:
                        self._evaluate(iv, cl[:j + 1], cl[j], False, c[j]['t'])
            self.last_bar[iv] = c[-1]['t']

    # 클라우드 실행처럼 매번 새로 켜질 때 상태를 이어받기 위한 저장/복원
    def to_state(self):
        return {'last_bar': self.last_bar, 'aligned': self.aligned,
                'armed': {f'{iv}|{s}|{l}': v for (iv, s, l), v in self.approach_armed.items()}}

    def load_state(self, st):
        self.last_bar = dict(st.get('last_bar', {}))
        self.aligned = dict(st.get('aligned', {}))
        for k, v in st.get('armed', {}).items():
            iv, s, l = k.split('|')
            self.approach_armed[(iv, int(s), int(l))] = v

    def _evaluate(self, iv, cl, price, first, bar_t=None):
        n = len(cl)
        tag = f'{self.market} {_label(iv)}'
        notify = alerts.notify
        if bar_t:
            start = datetime.strptime(bar_t, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
            close = start + timedelta(minutes=1440 if iv == 'day' else int(iv))
            tag += f" {close.astimezone(KST):%H:%M} 마감봉"
            late = (datetime.now(timezone.utc) - close).total_seconds() / 60
            minutes = 1440 if iv == 'day' else int(iv)
            if late > max(60, 3 * minutes):
                # 너무 지난 신호는 매수점으로 쓸모가 없어 휴대폰으로 보내지 않고 기록만 한다
                notify = lambda t, b, level=None: print(f'(지난 신호, 알림 생략) {t} | {b}', flush=True)
            elif late > 20:  # 클라우드 실행이 밀려 늦게 알게 된 신호
                tag = f'⏱{late:.0f}분 늦은 알림 | ' + tag
        for s, l in self.pairs:
            if n < l + 4:
                continue
            s0, l0 = _sma(cl, s, n - 1), _sma(cl, l, n - 1)
            s1, l1 = _sma(cl, s, n), _sma(cl, l, n)
            key = (iv, s, l)
            # 발생
            if s0 <= l0 and s1 > l1:
                self.approach_armed[key] = False
                if not first:
                    notify(f'골든크로스 {s}/{l} 발생',
                                  f'{tag} | {s}선 {s1:,.2f} > {l}선 {l1:,.2f} | 종가 {price:,.2f}원', level='cross')
                continue
            if s1 >= l1:
                self.approach_armed[key] = True  # 위에 있는 동안은 다음 하락 후 접근을 기다림
                continue
            # 임박: 아래에 있으면서 간격이 좁아지고 단기선이 오르는 중
            gap1 = (l1 - s1) / l1 * 100
            s3, l3 = _sma(cl, s, n - 3), _sma(cl, l, n - 3)
            gap3 = (l3 - s3) / l3 * 100 if s3 and l3 else None
            closing = gap3 is not None and gap1 < gap3 and s1 > s0
            armed = self.approach_armed.get(key, True)
            if armed and closing and gap1 <= self.gap:
                self.approach_armed[key] = False
                speed = (gap3 - gap1) / 2  # 봉당 좁혀지는 폭
                bars = gap1 / speed if speed > 0 else None
                eta = '' if bars is None else (', 다음 봉에 교차 가능' if bars < 1.5 else f', 이 속도면 약 {bars:.0f}봉 뒤')
                if not first:
                    notify(f'골든크로스 {s}/{l} 임박',
                                  f'{tag} | 간격 {gap1:.2f}%{eta} | 종가 {price:,.2f}원', level='approach')
            elif not armed and gap1 > self.gap * 2:
                self.approach_armed[key] = True  # 다시 벌어지면 재무장
        # 정배열 (짧은 선이 위)
        if n >= self.lines[-1] + 1:
            vals = [_sma(cl, k, n) for k in self.lines]
            ok = all(a > b for a, b in zip(vals, vals[1:]))
            if ok and self.aligned.get(iv) is False:
                notify('이평선 정배열 완성',
                              f"{tag} | {' > '.join(str(k) for k in self.lines)} | 종가 {price:,.2f}원", level='cross')
            self.aligned[iv] = ok
