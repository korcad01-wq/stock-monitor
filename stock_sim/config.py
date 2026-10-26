import json
import os
from pathlib import Path

# 데이터 폴더: 환경변수 STOCK_SIM_HOME 이 있으면 그곳, 없으면 패키지 옆 data/
HOME = Path(os.environ.get('STOCK_SIM_HOME') or Path(__file__).resolve().parent.parent / 'data')
HOME.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = HOME / 'config.json'

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
    'event_block_hours': 2,   # 경제 일정 전후 N시간은 모의 신규 매수 중단. 0이면 끔
    'events': [               # 한국 시간. FOMC 는 미국 14:00, CPI 는 미국 08:30 발표
        {'at': '2026-10-29T03:00:00+09:00', 'title': 'FOMC 금리 결정'},
        {'at': '2026-11-10T22:30:00+09:00', 'title': '미국 10월 CPI'},
        {'at': '2026-12-10T04:00:00+09:00', 'title': 'FOMC 금리 결정(점도표)'},
        {'at': '2026-12-10T22:30:00+09:00', 'title': '미국 11월 CPI'},
    ],
    'quiet_start': '00:00',   # 이 시각부터 휴대폰 알림 보내지 않음(PC 시각 기준)
    'quiet_end': '07:00',     # 이 시각부터 다시 보냄. 둘이 같으면 방해금지 없음
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
