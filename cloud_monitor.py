"""GitHub Actions 에서 몇 분마다 한 번 실행되는 감시(실제 주문 없음).

- 하락 경보: 업비트 하루 등락률이 alert_rate 이하(하루 1회)
- 내 평단 기준 손절 경보: entry_price 를 넣었을 때(손절선에서 한 번, 더 빠지면 단계마다)
- 골든크로스 임박·발생, 정배열: stock_sim.crosswatch 와 같은 규칙
상태(state.json)는 워크플로가 actions/cache 로 다음 실행에 넘겨준다.
휴대폰 알림 주제는 Secrets 의 NTFY_TOPIC 에서 읽는다.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('STOCK_SIM_HOME', tempfile.mkdtemp())

from stock_sim import alerts, config, crosswatch, upbit  # noqa: E402
from stock_sim import market as market_mod  # noqa: E402

STATE = ROOT / 'state.json'


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    cfg = dict(config.DEFAULTS)
    cfg.update(json.loads((ROOT / 'cloud_config.json').read_text(encoding='utf-8')))
    cfg['ntfy_topic'] = os.environ.get('NTFY_TOPIC', '').strip()
    if not cfg['ntfy_topic']:
        print('NTFY_TOPIC 비밀값이 없습니다. Settings → Secrets and variables → Actions 에 등록하세요.')
        return 1
    config.save(cfg)  # alerts.notify 가 이 설정(방해금지·범위·주제)을 읽는다

    st = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    market = cfg['market']
    day = upbit.trading_day()
    t = upbit.ticker(market)
    print(f"{market} {t['price']:,.2f}원 오늘 {t['change_rate']:+.2f}% (거래일 {day})")

    if t['change_rate'] <= cfg['alert_rate'] and st.get('drop_day') != day:
        alerts.notify(f'{market} 하락 경보', f"오늘 {t['change_rate']:+.2f}% (기준 {cfg['alert_rate']}%) 현재가 {t['price']:,.2f}원")
        st['drop_day'] = day
    entry = float(cfg.get('entry_price') or 0)
    if entry:  # 손절선(-sl%)에서 한 번, 이후 stop_step %p 더 빠질 때마다 다시
        if st.get('stop_entry') != entry:
            st.pop('stop', None)
        st['stop_entry'] = entry
        pr = market_mod.stop_check(cfg, st, t['price'], entry, alerts.notify)
        print(f"내 평단 {entry:,.2f}원 대비 {pr:+.2f}% (손절선 -{abs(cfg['sl'])}%)")
    if t['change_rate'] >= cfg['target_rate'] and st.get('up_day') != day:
        alerts.notify(f'{market} 목표 상승', f"오늘 {t['change_rate']:+.2f}% (목표 {cfg['target_rate']}%)", level='info')
        st['up_day'] = day

    # 차트 밖 위험: 하루 -5% 한도, 1시간 급락, 하락장 판정, FOMC·CPI 일정
    caution = market_mod.run_checks(cfg, st, t)
    if caution:
        print(caution)
    try:  # 관심 종목 ±5% 급등락은 실시간 최우선 알림
        market_mod.run_movers(cfg, st)
    except Exception as e:
        print('급등락 확인 실패:', e)
    try:  # 관심 종목 하루 한 번 요약(실시간 알림은 보유 종목만)
        market_mod.run_digest(cfg, st)
    except Exception as e:
        print('요약 실패:', e)

    cw = crosswatch.CrossWatcher(cfg)
    if st.get('market') == market:
        cw.load_state(st.get('cross', {}))
    cw.caution = caution
    cw.check()
    print(cw.describe(), '| 마지막 확인 봉', cw.last_bar)
    st.update({'market': market, 'cross': cw.to_state()})
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
