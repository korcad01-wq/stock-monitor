import json
import os
from pathlib import Path

# 데이터 폴더: 환경변수 STOCK_SIM_HOME 이 있으면 그곳, 없으면 패키지 옆 data/
HOME = Path(os.environ.get('STOCK_SIM_HOME') or Path(__file__).resolve().parent.parent / 'data')
HOME.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = HOME / 'config.json'

# 종목 선택 목록: 업비트 원화 마켓 중 거래대금이 크고 상장 기간이 긴 대형 코인(2026-10 데이터 비교).
# "꾸준히 오르는 코인"이 아니다 — 지난 1년은 BTC -37%, 나머지 -44~-73% 였다(TRX 만 -1%).
WATCHLIST = ['KRW-BTC', 'KRW-ETH', 'KRW-XRP', 'KRW-SOL', 'KRW-TRX', 'KRW-LINK',
             'KRW-ADA', 'KRW-DOGE', 'KRW-XLM', 'KRW-BCH']
COIN_NAMES = {'BTC': '비트코인', 'ETH': '이더리움', 'XRP': '리플', 'SOL': '솔라나', 'TRX': '트론',
              'LINK': '체인링크', 'ADA': '에이다', 'DOGE': '도지코인', 'XLM': '스텔라루멘', 'BCH': '비트코인캐시'}


def market_label(m):
    """'KRW-BTC' → 'KRW-BTC 비트코인' (화면 표시용)."""
    name = COIN_NAMES.get(m.split('-')[-1])
    return f'{m} {name}' if name else m


def market_code(label):
    """화면 표시 'KRW-BTC 비트코인' → 'KRW-BTC'."""
    return label.split()[0] if label.strip() else label

DEFAULTS = {
    'market': 'KRW-XRP',
    'target_rate': 1.4,       # 하루 목표 수익률(%)
    'alert_rate': -2.0,       # 하루 수익률이 이 값 이하로 떨어지면 알람(%)
    'max_daily_loss': -5.0,   # 모의계좌 하루 손실이 이 값 이하면 그날 신규 매수 중단(%)
    'max_trades_per_day': 3,  # 하루 매수 횟수 한도(자동+수동). 0이면 제한 없음
    'monthly_loss_limit': -15.0,  # 이달 손실이 이 값 이하면 그달 신규 매수 중단(%)
    'fee_rate': 0.05,         # 업비트 KRW 마켓 수수료(편도, %)
    'slippage': 0.05,         # 체결 미끄러짐 가정(편도, %)
    'initial_cash': 1000000,
    'monthly_deposit': 500000,
    'position_size': 100,     # 매수 시 현금의 몇 %를 쓸지
    'poll_seconds': 10,
    'strategy': 'volume_spike',
    'interval': '5',          # 분봉 단위(1,3,5,10,15,30,60,240) 또는 day
    'tp': 2.0,                # 익절(%)
    'sl': 1.0,                # 손절(%)
    'max_hold': 48,           # 최대 보유 봉 수(0이면 제한 없음)
    'params': {},             # 전략별 파라미터 덮어쓰기
    'ntfy_topic': '',         # 휴대폰 알림(ntfy 앱) 구독 주제
    'telegram_token': '',     # 휴대폰 알림(텔레그램 봇) 토큰
    'telegram_chat_id': '',
    'push_level': 'all',      # all = 전부, signal = 경보+골든크로스, warn = 하락 경보만
    'cross_enabled': True,    # 골든크로스 감시
    # 5분봉·5/20 까지 켜면 리플 기준 하루 40건 넘게 울려서(2026-10 지난 7일 재생) 기본은 하루 5건 안팎으로 둔다
    'cross_intervals': '15,60',        # 감시할 분봉(쉼표로 여러 개, day 가능)
    'cross_pairs': '20/60,60/120',     # 단기/장기 이평선 쌍
    'ma_lines': '5,10,20,60,120',      # 정배열 판단 이평선
    'cross_approach_gap': 0.15,        # 단기선이 장기선 아래 이 간격(%) 이내로 다가오면 '임박'
    # 차트 밖 위험(market.py)
    'regime_enabled': True,   # 비트코인 20일선 아래면 하락장 → 골든크로스 알림에 경고
    'cross_in_downtrend': 'tag',  # tag = 경고 붙여 보냄, mute = 하락장엔 골든크로스 알림 안 보냄
    'rapid_drop_pct': -3.0,   # 1시간 최고가 대비 이만큼 떨어지면 급락 경보(%). 0이면 끔
    'btc_drop_pct': -2.0,     # 비트코인 1시간 최고가 대비 이만큼 떨어지면 경보 + 매수 중단(%). 0이면 끔
    'buy_in_downtrend': 'half',  # 비트코인 하락장일 때 신규 매수: half = 비중 절반, block = 중단, allow = 그대로
    'stop_step': 3.0,         # 평단 손절선(-sl%) 아래로 이만큼(%p) 더 빠질 때마다 손절 경보를 다시 울림
    'digest_enabled': True,   # 관심 종목(WATCHLIST) 하루 한 번 요약 알림(클라우드 감시가 보냄, 무음)
    'digest_time': '08:00',   # 요약 보내는 시각(한국 시간)
    'mover_pct': 5.0,         # 관심 종목 하루 등락률이 ±이만큼 넘으면 최우선 알림, 이만큼 더 움직일 때마다 다시(%). 0이면 끔
    'event_block_hours': 2,   # 경제 일정 전후 N시간은 모의 신규 매수 중단. 0이면 끔
    'events': [               # 한국 시간. FOMC 는 미국 14:00, CPI 는 미국 08:30 발표
        {'at': '2026-10-29T03:00:00+09:00', 'title': 'FOMC 금리 결정'},
        {'at': '2026-11-10T22:30:00+09:00', 'title': '미국 10월 CPI'},
        {'at': '2026-12-10T04:00:00+09:00', 'title': 'FOMC 금리 결정(점도표)'},
        {'at': '2026-12-10T22:30:00+09:00', 'title': '미국 11월 CPI'},
    ],
    'quiet_start': '00:00',   # 이 시각부터 휴대폰 알림 보내지 않음(PC 시각 기준)
    'quiet_end': '07:00',     # 이 시각부터 다시 보냄. 둘이 같으면 방해금지 없음
    # 초단타 모의(scalp.py) — 모의계좌(paper.db)의 현금으로 사고판다(거래 구분 '초단타'). 수익률(%)은 수수료 왕복을 뺀 순수익 기준
    'scalp_size': 20.0,          # 1회 진입 금액 = 모의계좌 평가자산의 몇 %
    'scalp_max_pos': 3,          # 동시에 들고 있을 수 있는 종목 수
    'scalp_tp': 0.4,             # 익절(%). 0.6→0.4(2026-11-01 시험: 손실 줄어듦)
    'scalp_sl': 0.4,             # 손절(%) — 최소값. 흔들림이 크면 더 넓어짐
    'scalp_trail_on': 0.35,      # 이만큼 오른 적이 있으면 추적 손절 시작(%)
    'scalp_trail_gap': 0.2,      # 최고 수익에서 이만큼 밀리면 청산(%p)
    'scalp_hold_min': 10,        # 최대 보유 시간(분). 지나면 시간 청산
    'scalp_win_sec': 60,         # 판단 구간(초). 60 = 1분 기준, 10 = 10초 기준(초단타). 아래 거래량·상승·체결강도를 이 구간으로 잰다
    'scalp_vol_x': 3.0,          # 진입 조건: 판단 구간 거래대금이 평소(같은 길이)의 몇 배 이상
    'scalp_r1': 0.3,             # 진입 조건: 판단 구간 상승률(%) 이상
    'scalp_r5_max': 0.3,         # 진입 금지: 5분 사이 이미 이만큼(%) 넘게 올랐으면 추격하지 않음
    'scalp_strength': 150.0,     # 진입 조건: 1분 체결강도(매수 체결 ÷ 매도 체결 ×100) 이상
    'scalp_imb': 1.0,            # 진입 조건: 호가 5단계 매수잔량 ÷ 매도잔량(원화) 이상
    'scalp_spread_max': 0.15,    # 진입 금지: 호가 간격(%)이 이보다 크면(호가 한 칸이 큰 저가 코인)
    'scalp_cooldown_min': 5,     # 한 종목을 판 뒤 다시 들어가기까지 쉬는 시간(분)
    'scalp_hour_start': 9,       # 새로 사는 시간: 이 시(PC 시각)부터
    'scalp_hour_end': 21,        # 이 시 전까지. 둘이 같으면 24시간. 1분봉 시험·실거래 모두 밤~새벽(21~09시) 진입이 손실 대부분(2026-11-01)
    'scalp_confirm_sec': 10,     # 추격 금지: 신호 뒤 이 시간(초) 동안 오른 값을 지키고 매수 우위가 이어질 때만 산다. 0 = 바로 매수
    'scalp_min_ticks': 15,       # 판단 구간 체결 건수가 이보다 적으면 체결강도를 믿지 않음(몇 건뿐일 때 999 로 나오는 것 막기)
    'scalp_sl_noise_x': 2.5,     # 손절 폭 = max(손절%, 평소 10초 흔들림 × 이 배수 + 수수료 왕복 + 호가간격). 익절도 같은 비율로 넓힘
    'scalp_sl_max': 1.0,         # 흔들림 기준 손절 폭이 이보다 크면(%) 그 종목은 들어가지 않음
    'scalp_daily_loss': -3.0,    # 하루(09:00 기준) 손실이 이만큼이면 그날 신규 진입 중단(%)
    'scalp_loss_streak': 3,      # 연속 손절이 이 횟수면
    'scalp_pause_min': 15,       # 이 시간(분) 동안 신규 진입 쉼
    'scalp_btc_guard': -0.7,     # 비트코인 5분 등락이 이 값(%) 이하면 신규 진입 중단
    'scalp_push': True,          # 초단타 매수·청산·멈춤·하루 결산을 휴대폰(ntfy)으로. 방해금지 시간엔 보내지 않음
    # False = 새로 사지 않고 신호만 기록(관찰). 2026-11-08 실적 56건 -20.9만 원(손절 27건이 -20.5만) → 끔
    'scalp_on': True,
    # 지정가 줍기 모의(dip.py) — 매 정시 현재가보다 dip_pct% 아래에 매수 주문을 걸어 두고(1시간 유효),
    # 던지는 물량에 체결되면 체결가 +dip_tp% 에 매도 주문. 모의계좌 현금 사용(거래 구분 '줍기'), 실제 주문 없음.
    # 2026-11-01 1분봉 14일×10종목 시험: -2%/+1%/1일이 앞·뒤 기간 모두 1회 평균 +0.6~0.8%(승률 96%, 최악 -3.95%).
    #  손절을 짧게 걸면 꼬리 중간에 털려 오히려 나빠졌다 → 기본은 손절 없음, 대신 비트코인 급락 차단·종목당 금액 상한
    'dip_pct': 2.0,              # 매수 주문가 = 주문 걸 때 현재가보다 이만큼(%) 아래
    'dip_tp': 1.0,               # 체결되면 체결가보다 이만큼(%) 위에 매도 주문
    'dip_hold_min': 1440,        # 익절이 안 나면 이 시간(분) 뒤 시장가 정리. 1440 = 1일
    'dip_sl': 0.0,               # 손절(%). 0 = 손절 없음(시험에서 손절이 결과를 나쁘게 함)
    'dip_size': 5.0,             # 주문 1건 금액 = 모의계좌 평가자산의 몇 %(주문을 거는 순간 현금이 묶임)
    'dip_max_pos': 10,           # 보유 + 대기 주문 합계 상한(종목 수)
    'dip_btc_guard': -3.0,       # 비트코인이 1시간 최고가 대비 이만큼(%) 빠지면 대기 주문 모두 취소, 새로 걸지 않음
    'dip_coins': '',             # 줍기 종목(쉼표로, 예: BTC,ETH,XRP). 비우면 관심 10종목 전부
    'dip_push': True,            # 줍기 체결·청산을 휴대폰(ntfy)으로
    'engines_autostart': True,   # stock 을 열면 초단타·줍기 엔진을 바로 시작(창은 최소화)
    # 자동 매매(모의투자 시작 버튼) — True 면 stock 을 열 때 시작하고, 끄지 않았는데 멈추면 30초 뒤 다시 켠다.
    # 사용자가 '중지'를 누르면 False 로 저장되어 다음에도 켜지 않는다
    'paper_autostart': True,
    'fut_cash': 100000,          # 선물·옵션 모의 시작 자금(달러, 초기화 때 적용)
    'fut_margin_pct': 8.0,       # 선물 증거금 % (모의 가정)
    'fut_maint_ratio': 0.9,      # 유지 증거금 = 증거금 × 이 비율. 평가자산이 이 아래면 강제청산
    'fut_opt_spread_pct': 2.0,   # 옵션 이론가에 더하는 호가 폭 %(절반씩, 모의 가정)
    'fut_use_gate': True,        # 세계 지수 진입 판단이 막으면 새 진입을 막는다(청산은 항상 가능)
    'fut_push': True,            # 강제청산을 휴대폰으로
    # 국내 선물·옵션 모의(futures_kr.py, 한국투자 시세) — 해외(달러) 계좌와 따로. 증거금·수수료는 모의 가정값
    'kfut_cash': 50_000_000,     # 시작 자금(원, 초기화 때 적용)
    'kfut_margin_pct': 10.0,     # 선물 증거금 % (가정. 실제 거래소 위탁증거금률과 다를 수 있음)
    'kfut_maint_ratio': 0.9,     # 유지 증거금 = 증거금 × 이 비율
    'kfut_opt_spread_pct': 0.0,  # 국내 옵션은 실제 호가로 체결해 쓰지 않음(호가가 없을 때만 이론가 대신)
    'kfut_use_gate': True,       # 경제 일정 전후 새 진입 막기
    'kfut_push': True,           # 강제청산을 휴대폰으로
    # 자동 스트래들(모의): 예상 흔들림 vs 옵션값이 품은 흔들림. 2026-11-18 10년 시험(뒤 40%)에서 사기·팔기 모두 +, 내재변동성은 어림값이라 실전 호가로 검증 중
    'kfut_auto': True,           # 켜 두면 매일 09:05~10:00 한 번 판단, 15:10 청산
    'kfut_auto_edge': 1.3,       # 예상이 옵션값 흔들림의 ×1.3 넘으면 사기, ÷1.3 밑이면 팔기
    'kfut_auto_qty': 1,          # 다리당 계약 수(콜 1 + 풋 1)
    'kfut_auto_stop': 0.5,       # 판 스트래들 값이 진입 때보다 50% 오르면 손절
    'kfut_auto_max_spread_buy': 0.02,   # 사기: 콜·풋 호가 차이 합이 스트래들 값의 2% 넘으면 쉼(10년 시험 손익분기)
    'kfut_auto_max_spread_sell': 0.01,  # 팔기: 1% 넘으면 쉼
    # 공격 모드 그림자 기록(2026-11-20 사용자 선택): 계좌는 위 신중 규칙, 공격 규칙이 했을 거래는 실제 호가로 가상 기록만
    'kfut_shadow': True,
    'kfut_shadow_edge': 1.1,          # 예상이 옵션값 흔들림의 ×1.1 넘으면 사기, ÷1.1 밑이면 팔기
    'kfut_shadow_max_spread': 0.07,   # 호가 비용 7%까지 허용(11-20 사용자 지정, 10%→7%)
    # 줍기 실전 판정 감시(2026-11-22 사용자 요청, dipwatch.py): 매일 21시 요약, 최악 -8%·누적 마이너스면 즉시 경보
    'dipwatch': True,
    'dipwatch_until': '2026-12-25',
    'dipwatch_dd': 8.0,
    'dipwatch_hour': 21,
    'macro_on': True,            # stock 을 열면 세계 지수 자료를 계속 모은다
    'macro_refresh_sec': 60,     # 세계 지수 시세 간격(초, 최소 30)
    'macro_block_min': 30,       # macro.gate: 중요 일정 전후 N분 진입 막기
    'macro_shock_pct': 3.0,      # macro.gate: 선물·지수 하루 ±N% 이상이면 막기
    'macro_max_age_sec': 300,    # macro.gate: 자료가 이보다 오래되면 막기
}


def load():
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding='utf-8')))
    return cfg


def save(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


def parse_value(key, raw):
    """문자열 입력을 기본값의 타입에 맞춰 바꾼다."""
    if key not in DEFAULTS:
        raise KeyError(key)
    base = DEFAULTS[key]
    if isinstance(base, bool):
        return raw.lower() in ('1', 'true', 'yes', 'y', 'on')
    if isinstance(base, int) and not isinstance(base, bool):
        return int(float(raw))
    if isinstance(base, float):
        return float(raw)
    if isinstance(base, (dict, list)):
        return json.loads(raw)
    return raw
