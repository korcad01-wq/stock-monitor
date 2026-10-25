"""윈도우 알림(토스트) + 경고음 + 로그 파일 + 휴대폰 푸시(ntfy / 텔레그램)."""
import json
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from . import config
from .config import HOME

KST = timezone(timedelta(hours=9))
LOG = HOME / 'alerts.log'
SOUNDS = Path(__file__).resolve().parent.parent / 'sounds'

# 알림 종류 → (PC 소리 파일, ntfy 우선순위, ntfy 태그, 화면 표시 기호)
# 휴대폰은 ntfy 우선순위별로 소리를 따로 지정할 수 있어서 종류마다 등급을 다르게 둔다.
# ntfy 는 태그 이름이 이모지면 제목 앞에 붙여 주므로 제목에는 기호를 넣지 않는다.
LEVELS = {
    'warn': ('stock_alarm.wav', 5, 'red_circle', '🔴'),            # 하락 경보 → 최대
    'cross': ('stock_cross.wav', 4, 'green_circle', '🟢'),          # 골든크로스 발생·정배열 → 높음
    'approach': ('stock_approach.wav', 3, 'yellow_circle', '🟡'),   # 골든크로스 임박 → 기본
    'info': ('stock_notice.wav', 2, 'large_blue_circle', '🔵'),     # 체결·목표 → 낮음(휴대폰 무음)
}
PUSH_LEVELS = {
    'all': {'warn', 'cross', 'approach', 'info'},
    'signal': {'warn', 'cross', 'approach'},
    'warn': {'warn'},
}
# 등록된 앱 ID가 있어야 토스트가 뜬다. Windows PowerShell 의 ID를 빌려 쓴다.
APP_ID = r'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

_PS = r'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml('<toast scenario="reminder"><visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual><audio silent="true" /><actions><action content="확인" arguments="ok" activationType="foreground"/></actions></toast>')
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app}').Show([Windows.UI.Notifications.ToastNotification]::new($x))
'''


def notify(title, body, level='warn'):
    stamp = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    mark = LEVELS.get(level, LEVELS['info'])[3]
    line = f'[{stamp}] {mark} {title} | {body}'
    out = ('\a' if level == 'warn' else '') + line
    try:
        print(out, flush=True)
    except UnicodeEncodeError:  # 이모지를 못 찍는 콘솔에서도 알림은 계속 보낸다
        enc = sys.stdout.encoding or 'ascii'
        print(out.encode(enc, 'replace').decode(enc), flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    cfg = config.load()
    if in_quiet_hours(cfg):
        return  # 방해금지 시간: 휴대폰·PC 알림 없이 로그만 남김
    if level in PUSH_LEVELS.get(cfg.get('push_level', 'all'), PUSH_LEVELS['all']):
        # 네트워크가 느려도 감시 루프를 막지 않도록 별도 스레드로 보낸다
        threading.Thread(target=push, args=(cfg, title, body, level)).start()
    if sys.platform != 'win32':
        return
    try:
        import winsound
        wav = SOUNDS / LEVELS.get(level, LEVELS['info'])[0]
        if wav.exists():
            winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            winsound.MessageBeep(winsound.MB_ICONHAND if level == 'warn' else winsound.MB_ICONASTERISK)
    except Exception:
        pass
    # PowerShell 문자열 안 작은따옴표는 두 번 써서 이스케이프
    ps = _PS.replace('{title}', escape(f'{mark} {title}').replace("'", "''")) \
            .replace('{body}', escape(body).replace("'", "''")).replace('{app}', APP_ID)
    try:
        subprocess.Popen(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        pass


def in_quiet_hours(cfg, now=None):
    """quiet_start ~ quiet_end 사이면 True. 자정을 넘는 구간(예: 23:00~07:00)도 처리한다.
    시각은 한국 시간 기준(클라우드 서버는 UTC 라서)."""
    s, e = cfg.get('quiet_start', ''), cfg.get('quiet_end', '')
    if not s or not e or s == e:
        return False
    t = (now or datetime.now(KST)).strftime('%H:%M')
    return s <= t < e if s < e else (t >= s or t < e)


def _post_json(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def push(cfg, title, body, level='warn'):
    """설정된 휴대폰 채널로 보낸다. 보낸 채널 이름 목록을 돌려준다(실패는 로그에 기록)."""
    sent = []
    if cfg.get('ntfy_topic'):
        try:
            _, prio, tag, _ = LEVELS.get(level, LEVELS['info'])
            _post_json('https://ntfy.sh', {
                'topic': cfg['ntfy_topic'], 'title': title, 'message': body,
                'priority': prio, 'tags': [tag],
            })
            sent.append('ntfy')
        except Exception as e:
            _log_error(f'ntfy 전송 실패: {e}')
    if cfg.get('telegram_token') and cfg.get('telegram_chat_id'):
        try:
            _post_json(f"https://api.telegram.org/bot{cfg['telegram_token']}/sendMessage",
                       {'chat_id': cfg['telegram_chat_id'], 'text': f"{LEVELS.get(level, LEVELS['info'])[3]} {title}\n{body}"})
            sent.append('telegram')
        except Exception as e:
            _log_error(f'텔레그램 전송 실패: {e}')
    return sent


def _log_error(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n')


def telegram_chat_id(token):
    """봇에게 메시지를 한 번 보낸 뒤 호출하면 그 대화의 chat_id 를 찾는다."""
    with urllib.request.urlopen(f'https://api.telegram.org/bot{token}/getUpdates', timeout=10) as r:
        data = json.load(r)
    for u in reversed(data.get('result', [])):
        msg = u.get('message') or u.get('channel_post') or {}
        if msg.get('chat', {}).get('id'):
            return str(msg['chat']['id'])
    return None


class Threshold:
    """값이 기준 이하로 '떨어지는 순간'에만 알리고, 기준 + 여유폭 위로 회복하면 다시 무장한다."""

    def __init__(self, hysteresis=0.5):
        self.armed = {}
        self.h = hysteresis

    def below(self, key, value, limit):
        armed = self.armed.get(key, True)
        if armed and value <= limit:
            self.armed[key] = False
            return True
        if not armed and value > limit + self.h:
            self.armed[key] = True
        return False

    def above(self, key, value, limit):
        armed = self.armed.get(key, True)
        if armed and value >= limit:
            self.armed[key] = False
            return True
        if not armed and value < limit - self.h:
            self.armed[key] = True
        return False

    def reset(self):
        self.armed.clear()
