# -*- coding: utf-8 -*-
"""
抓取结果通知 —— 邮件 / 企业微信 / 钉钉 / Server酱 / 通用 Webhook

配置方式（环境变量优先，其次读 notify.json）
------------------------------------------------
1) 配置文件：在 exe（或项目）同目录放 notify.json：
   {
     "enabled": true,
     "notify_on": "always",
     "email": {"host": "smtp.qq.com", "port": 465, "ssl": true,
               "user": "you@qq.com", "password": "授权码",
               "to": ["friend@example.com"], "sender_name": "A股人气雷达"},
     "wecom_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
     "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
     "dingtalk_secret": "",
     "serverchan_key": "SCTxxxxxxxx",
     "webhook_url": "https://your-endpoint"
   }

2) 环境变量：
   NOTIFY_ENABLED=1  NOTIFY_ON=always|issues_only
   SMTP_HOST SMTP_PORT SMTP_SSL SMTP_USER SMTP_PASSWORD SMTP_TO(逗号分隔)
   WECOM_WEBHOOK  DINGTALK_WEBHOOK  DINGTALK_SECRET  SERVERCHAN_KEY  NOTIFY_WEBHOOK

说明
----
- 全部通道可选，不配置就什么都不发（安全默认）。
- 所有发送函数内部捕获异常，绝不向调用方抛出。
- notify_on = always（每次都发） / issues_only（仅校验不通过时发）。
"""
import json
import os
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

_TIMEOUT = 15


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _config_path():
    p = (os.environ.get("NOTIFY_CONFIG") or "").strip()
    if p:
        return p
    return os.path.join(_app_dir(), "notify.json")


def _load_file_cfg():
    p = _config_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception as e:
        try:
            sys.stderr.write("[notifier] notify.json 解析失败: %s\n" % e)
        except Exception:
            pass
        return {}


def _truthy(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "off", "")


def config():
    """合并后的配置（环境变量覆盖文件）"""
    fc = _load_file_cfg()
    em = dict(fc.get("email") or {})

    def env(name, key, target):
        v = os.environ.get(name)
        if v not in (None, ""):
            target[key] = v

    env("SMTP_HOST", "host", em)
    env("SMTP_PORT", "port", em)
    env("SMTP_USER", "user", em)
    env("SMTP_PASSWORD", "password", em)
    env("SMTP_TO", "to", em)
    env("SMTP_SENDER_NAME", "sender_name", em)
    if os.environ.get("SMTP_SSL") not in (None, ""):
        em["ssl"] = _truthy(os.environ.get("SMTP_SSL"), True)

    cfg = {
        "enabled": _truthy(os.environ.get("NOTIFY_ENABLED"), fc.get("enabled", True)),
        "notify_on": (os.environ.get("NOTIFY_ON") or fc.get("notify_on") or "always").strip(),
        "email": em,
        "wecom_webhook": os.environ.get("WECOM_WEBHOOK") or fc.get("wecom_webhook") or "",
        "dingtalk_webhook": os.environ.get("DINGTALK_WEBHOOK") or fc.get("dingtalk_webhook") or "",
        "dingtalk_secret": os.environ.get("DINGTALK_SECRET") or fc.get("dingtalk_secret") or "",
        "serverchan_key": os.environ.get("SERVERCHAN_KEY") or fc.get("serverchan_key") or "",
        "webhook_url": os.environ.get("NOTIFY_WEBHOOK") or fc.get("webhook_url") or "",
    }
    # 邮件 to 统一成列表
    to = cfg["email"].get("to")
    if isinstance(to, str):
        cfg["email"]["to"] = [x.strip() for x in to.replace(";", ",").split(",") if x.strip()]
    elif isinstance(to, list):
        cfg["email"]["to"] = [str(x).strip() for x in to if str(x).strip()]
    else:
        cfg["email"]["to"] = []
    return cfg


def channels():
    """已配置的通道名列表"""
    c = config()
    out = []
    if c["email"].get("host") and c["email"].get("to"):
        out.append("email")
    if c["wecom_webhook"]:
        out.append("wecom")
    if c["dingtalk_webhook"]:
        out.append("dingtalk")
    if c["serverchan_key"]:
        out.append("serverchan")
    if c["webhook_url"]:
        out.append("webhook")
    return out


def status():
    """给前端展示的配置概览（不含密钥明文）"""
    c = config()
    def mask(v, keep=8):
        v = str(v or "")
        return (v[:keep] + "…") if len(v) > keep else (v or "")
    return {
        "enabled": c["enabled"],
        "notify_on": c["notify_on"],
        "config_path": _config_path(),
        "config_exists": os.path.isfile(_config_path()),
        "channels": channels(),
        "email_host": c["email"].get("host") or "",
        "email_to": c["email"].get("to") or [],
        "wecom": mask(c["wecom_webhook"]),
        "dingtalk": mask(c["dingtalk_webhook"]),
        "serverchan": mask(c["serverchan_key"]),
        "webhook": mask(c["webhook_url"]),
    }


# ---------------------------------------------------------------------------
# HTTP 工具
# ---------------------------------------------------------------------------

def _post_json(url, payload, timeout=_TIMEOUT):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "ignore")
    return resp.status, body


def _get(url, timeout=_TIMEOUT):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "ignore")


# ---------------------------------------------------------------------------
# 各通道
# ---------------------------------------------------------------------------

def send_email(subject, text, cfg=None):
    cfg = cfg or config()
    em = cfg.get("email") or {}
    host = em.get("host")
    to = em.get("to") or []
    if not host or not to:
        return False, "未配置邮件"
    port = int(em.get("port") or (465 if _truthy(em.get("ssl"), True) else 587))
    user = em.get("user") or ""
    pwd = em.get("password") or ""
    use_ssl = _truthy(em.get("ssl"), True)
    sender_name = em.get("sender_name") or "A股人气雷达"
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(sender_name, "utf-8")), user or "noreply@local"))
    msg["To"] = ",".join(to)
    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT, context=ctx) as s:
                if user:
                    s.login(user, pwd)
                s.sendmail(user or "noreply@local", to, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=_TIMEOUT) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                except Exception:
                    pass
                if user:
                    s.login(user, pwd)
                s.sendmail(user or "noreply@local", to, msg.as_string())
        return True, "OK"
    except Exception as e:
        return False, str(e)


def send_wecom(text, cfg=None):
    cfg = cfg or config()
    url = cfg.get("wecom_webhook")
    if not url:
        return False, "未配置"
    try:
        code, body = _post_json(url, {"msgtype": "text", "text": {"content": text}})
        if code == 200 and '"errcode":0' in body.replace(" ", ""):
            return True, "OK"
        return False, "HTTP %s %s" % (code, body[:120])
    except Exception as e:
        return False, str(e)


def send_dingtalk(text, cfg=None):
    cfg = cfg or config()
    url = cfg.get("dingtalk_webhook")
    if not url:
        return False, "未配置"
    try:
        secret = (cfg.get("dingtalk_secret") or "").strip()
        if secret:
            import hmac, hashlib, base64, time as _t
            ts = str(round(_t.time() * 1000))
            sign_str = "%s\n%s" % (ts, secret)
            h = hmac.new(secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(h).decode("utf-8"))
            url = url + ("&" if "?" in url else "?") + "timestamp=%s&sign=%s" % (ts, sign)
        code, body = _post_json(url, {"msgtype": "text", "text": {"content": text}})
        if code == 200 and '"errcode":0' in body.replace(" ", ""):
            return True, "OK"
        return False, "HTTP %s %s" % (code, body[:120])
    except Exception as e:
        return False, str(e)


def send_serverchan(title, text, cfg=None):
    cfg = cfg or config()
    key = (cfg.get("serverchan_key") or "").strip()
    if not key:
        return False, "未配置"
    try:
        url = "https://sctapi.ftqq.com/%s.send" % key
        data = urllib.parse.urlencode({"title": title, "desp": text}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "ignore")
        ok = '"code":0' in body.replace(" ", "") or '"errno":0' in body.replace(" ", "")
        return (True if ok else False), (body[:120] if not ok else "OK")
    except Exception as e:
        return False, str(e)


def send_webhook(title, text, meta=None, cfg=None):
    cfg = cfg or config()
    url = cfg.get("webhook_url")
    if not url:
        return False, "未配置"
    try:
        payload = {"title": title, "text": text, "content": text,
                   "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        if meta:
            payload.update(meta)
        code, body = _post_json(url, payload)
        return (200 <= int(code) < 300), ("OK" if 200 <= int(code) < 300 else body[:120])
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

CHANNEL_NAMES = {
    "email": "邮件", "wecom": "企业微信", "dingtalk": "钉钉",
    "serverchan": "Server酱(微信)", "webhook": "通用Webhook",
}


def send(title, text, meta=None, only=None):
    """向所有已配置通道发送。返回 [{'channel','ok','error'}]"""
    cfg = config()
    results = []
    if not cfg.get("enabled"):
        return [{"channel": "all", "ok": False, "error": "通知已关闭（NOTIFY_ENABLED=0）"}]
    want = only or channels()
    for ch in want:
        try:
            if ch == "email":
                ok, err = send_email(title, text, cfg)
            elif ch == "wecom":
                ok, err = send_wecom(text, cfg)
            elif ch == "dingtalk":
                ok, err = send_dingtalk(text, cfg)
            elif ch == "serverchan":
                ok, err = send_serverchan(title, text, cfg)
            elif ch == "webhook":
                ok, err = send_webhook(title, text, meta, cfg)
            else:
                ok, err = False, "未知通道"
        except Exception as e:
            ok, err = False, str(e)
        results.append({"channel": ch, "name": CHANNEL_NAMES.get(ch, ch), "ok": ok, "error": err})
        try:
            sys.stderr.write("[notifier] %s -> %s %s\n" % (ch, "OK" if ok else "FAIL", "" if ok else err))
        except Exception:
            pass
    return results


def should_send(integrity_ok):
    cfg = config()
    if not cfg.get("enabled"):
        return False
    if not channels():
        return False
    mode = (cfg.get("notify_on") or "always").lower()
    if mode == "issues_only":
        return not integrity_ok
    return True


# ---------------------------------------------------------------------------
# 汇总文案
# ---------------------------------------------------------------------------

_JOB_LABEL = {"morning": "早盘", "close": "收盘"}
_JOB_MODE = {"light": "轻量", "full": "全量"}


def format_summary(job=None, integrity=None, stats=None, target=None):
    """生成 (title, text)"""
    job = job or {}
    steps = job.get("steps") or {}
    ic = integrity or {}
    d = target or job.get("target") or ic.get("trade_date") or "-"
    ok = bool(job.get("ok"))
    mark = "✅" if (ok and ic.get("ok", True)) else ("⚠️" if ok else "❌")
    jn = job.get("job") or ""
    tag = (" " + _JOB_LABEL[jn]) if jn in _JOB_LABEL else ""
    title = "【A股人气雷达】%s%s 数据抓取%s" % (d, tag, mark)

    lines = ["【A股人气雷达】数据抓取汇总",
             "交易日：%s    状态：%s" % (d, mark)]
    if jn:
        lines.append("任务：%s（%s）" % (_JOB_LABEL.get(jn, jn),
                                      _JOB_MODE.get(job.get("mode") or "", "")))
    if job.get("elapsed") is not None:
        lines.append("用时：%.1f 秒" % job["elapsed"])

    labels = {"calendar": "交易日历", "hotlist": "人气榜",
              "screen": "全市场扫描", "themes": "题材热度"}
    lines.append("")
    lines.append("— 抓取明细 —")
    for k, v in steps.items():
        if k in ("integrity", "notify"):
            continue
        lines.append("· %s：%s" % (labels.get(k, k), v))

    if ic.get("items"):
        lines.append("")
        lines.append("— 完整性校验：%s —" % ("通过" if ic.get("ok") else "不通过"))
        for it in ic["items"]:
            sign = "=" if it["mode"] == "exact" else "≥"
            lines.append("· %s：%s  %d（期望%s%d）%s" % (
                it["label"], "OK" if it["ok"] else "缺失",
                it["actual"], sign, it["expected"], "" if it["ok"] else "  ⚠"))
        if ic.get("issues"):
            lines.append("缺失项：" + "；".join(ic["issues"]))

    rep = job.get("repair") or {}
    acts = rep.get("actions") or []
    if acts:
        lines.append("")
        lines.append("— 自动补抓：%s —" % (rep.get("summary") or ""))
        amap = {"calendar": "交易日历", "hotlist": "人气榜",
                "scan": "全市场扫描(日K/涨停池/选股)", "themes": "题材热度"}
        for a in acts:
            lines.append("· %s：%s %s" % (amap.get(a.get("action"), a.get("action")),
                                          "成功" if a.get("ok") else "失败",
                                          a.get("detail") or ""))

    if stats and stats.get("tables"):
        lines.append("")
        lines.append("— 本地数据库 —")
        try:
            total = sum(v for v in stats["tables"].values() if isinstance(v, int))
        except Exception:
            total = None
        lines.append("总记录：%s 条" % (total if total is not None else "-"))
        if stats.get("db_size_mb") is not None:
            lines.append("库大小：%s MB" % stats["db_size_mb"])
        lines.append("路径：%s" % (stats.get("db_path") or "-"))

    lines.append("")
    lines.append("（本消息由程序自动发送；数据仅供参考，不构成投资建议）")
    return title, "\n".join(lines)
