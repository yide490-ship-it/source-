# -*- coding: utf-8 -*-
"""搜索聚合小工具：关键词 → GitHub 仓库 / 网页(Bing) / Stack Overflow / npm 链接
功能：多源搜索 · 搜索历史 · 收藏夹 · 深色模式 · 数量调节 · 导出结果 · 快捷键"""
import sys, os, json, re, html, urllib.request, urllib.parse, threading, webbrowser, subprocess, time, tkinter as tk
from tkinter import ttk

if getattr(sys, "frozen", False):
    BASE = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "圆圆搜索")
    os.makedirs(BASE, exist_ok=True)
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "config.json")  # 配置固定存这里（含便携模式开关）
DATA_DIR = BASE  # 数据目录：便携模式开启时改为 exe 旁 data
HIST_FILE = os.path.join(DATA_DIR, "history.json")
FAV_FILE = os.path.join(DATA_DIR, "favorites.json")
LOG_FILE = os.path.join(DATA_DIR, "error.log")
PROXY = ""  # HTTP 代理，如 "http://192.168.1.5:7897"；留空 = 直连
CLASH_DIR = os.path.join(DATA_DIR, "clash")
CLASH_PORT = 7890
CLASH_PROC = None
UPDATE_URL = "https://raw.githubusercontent.com/yide490-ship-it/source-/main/version.txt"  # 在线更新源（GitHub 仓库 version.txt）
UPDATE_MIRRORS = ["https://ghfast.top/", "https://gh-proxy.com/", "https://ghproxy.net/"]  # GitHub 加速镜像（国内无代理可达）


def _load_default_sub():
    """默认订阅从本地 sub_url.txt 读取（不写进源码，避免公开仓库泄露）"""
    try:
        base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        p = os.path.join(base, "sub_url.txt")
        with open(p, "r", encoding="utf-8") as f:
            u = f.read().strip()
        return u if u.startswith("http") else ""
    except Exception:
        return ""


# 内置机场订阅（默认开箱即用；在「代理」里可改为其它订阅或清除）
SUB_URL_DEFAULT = _load_default_sub()
APP_VERSION = "1.0.56"

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.bing.com/",
}

def _free_port(start):
    import socket
    for p in range(start, start + 20):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            continue
    return start


def clash_exe_path():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "mihomo.exe")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "mihomo.exe")


def _copy_geo():
    """把随程序打包的 GeoIP/GeoSite 数据库复制到内核目录（避免启动时联网下载）"""
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    for name in ("Country.mmdb", "geosite.dat"):
        src = os.path.join(base, name)
        dst = os.path.join(CLASH_DIR, name)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                import shutil
                shutil.copyfile(src, dst)
            except Exception:
                pass


def start_builtin_clash(sub_url):
    """用机场订阅启动内置 Clash 内核，成功返回 True（端口自动避让冲突）"""
    global CLASH_PROC, CLASH_PORT
    try:
        # 清理历史残留 mihomo 进程（崩溃/强杀遗留会堆积导致端口混乱，verge 用的是 verge-mihomo.exe 不受影响）
        try:
            subprocess.run(["taskkill", "/IM", "mihomo.exe", "/F"],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        return _start_builtin_clash_impl(sub_url)
    except Exception as e:
        import traceback
        try:
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1024 * 1024:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write("")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write("\n[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), sub_url[:60]))
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise


def clash_api(path, method="GET", body=None):
    """调内置 Clash 内核的 control API（127.0.0.1:9090）"""
    req = urllib.request.Request("http://127.0.0.1:9090" + path, method=method)
    req.add_header("User-Agent", "yuanyuan-search")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode("utf-8")
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode("utf-8", "ignore")
    return json.loads(raw) if raw else {}


def _builtin_sub():
    """读内置订阅内容（打包在 exe 里，离线可用）"""
    base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, "builtin_sub.yaml")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return None


def _start_builtin_clash_impl(sub_url):
    """用机场订阅启动内置 Clash 内核，成功返回 True（端口自动避让冲突）"""
    global CLASH_PROC, CLASH_PORT
    exe = clash_exe_path()
    if not os.path.exists(exe):
        raise RuntimeError("内置内核缺失: " + exe)
    if CLASH_PROC is not None and CLASH_PROC.poll() is None:
        stop_builtin_clash()
    os.makedirs(CLASH_DIR, exist_ok=True)
    _copy_geo()
    sub_path = os.path.join(CLASH_DIR, "subscription.yaml")
    raw = None
    # 订阅缓存：6 小时内直接用本地缓存，避免每次启动都下载
    if os.path.exists(sub_path) and time.time() - os.path.getmtime(sub_path) < 6 * 3600:
        try:
            with open(sub_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            raw = None
    if raw is None:
        try:
            req = urllib.request.Request(sub_url, headers={
                "User-Agent": "clash-verge/v2.0.0", "Accept": "application/yaml,*/*"})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read().decode("utf-8", "ignore")
            if "proxies:" not in raw and "Proxy:" not in raw:
                raise RuntimeError("订阅格式无效")
            with open(sub_path, "w", encoding="utf-8") as f:
                f.write(raw)
        except Exception as e:
            # 联网下载失败 → 用内置订阅（离线兜底）
            raw = _builtin_sub()
            if not raw:
                raise RuntimeError("订阅下载失败且无内置订阅: " + str(e)[:60])
    # 2. 选空闲端口并注入配置（先剔除订阅里已有的同名顶层键，避免重复键启动失败）
    port = _free_port(CLASH_PORT)
    CLASH_PORT = port
    keep = [ln for ln in raw.split("\n")
            if not re.match(r"^\s*(mixed-port|allow-lan|mode|log-level|external-controller)\s*:", ln)]
    cfg = ("mixed-port: %d\nallow-lan: false\nmode: rule\nlog-level: silent\n"
           "external-controller: 127.0.0.1:9090\n" % port) + "\n".join(keep)
    cfg_path = os.path.join(CLASH_DIR, "config.yaml")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(cfg)
    # 3. 启动内核（-f 必须用绝对路径，相对路径会按进程 cwd 解析导致用默认配置）
    CLASH_PROC = subprocess.Popen([exe, "-d", CLASH_DIR, "-f", cfg_path],
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # 4. 等端口就绪（首次启动可能要加载规则，放宽到 30 秒）
    import socket
    for _ in range(60):
        if CLASH_PROC.poll() is not None:
            raise RuntimeError("内置内核启动失败")
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
            s.close()
            return True
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("内置内核端口未就绪")


def stop_builtin_clash():
    global CLASH_PROC
    if CLASH_PROC is not None:
        try:
            CLASH_PROC.terminate()
        except Exception:
            pass
        try:
            CLASH_PROC.wait(timeout=3)
        except Exception:
            try:
                CLASH_PROC.kill()
            except Exception:
                pass
        CLASH_PROC = None


def fetch(url, timeout=8, use_proxy=True):
    req = urllib.request.Request(url, headers=HDRS)
    if PROXY and use_proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
        with opener.open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

# GitHub 网页加速镜像前缀：国内无代理电脑直连用（双击结果链接时生效）
# 可替换成其它镜像；留空 "" = 用原始 github.com 链接
GH_MIRROR = "https://gh-proxy.net/"

def github_search(q, limit=10):
    # 每页 100 条翻页并行抓取（未认证 API 限流 10 req/min，上限 5 页）
    from concurrent.futures import ThreadPoolExecutor
    api = "https://api.github.com/search/repositories?q=" + urllib.parse.quote(q) + "&per_page=100&sort=stars&order=desc"  # 按访问量(star)降序
    pages = range(1, min((limit + 99) // 100, 10) + 1)  # \u89e3\u9664 500 \u6761\u4e0a\u9650\uff1a\u6700\u591a 10 \u9875 = 1000 \u6761\uff08GitHub API \u641c\u7d22\u786c\u9876 1000\uff0c\u672a\u8ba4\u8bc1 10 req/min\uff09
    items = []

    def grab(page):
        u = api + "&page=%d" % page
        try:
            return json.loads(fetch(u))
        except Exception:
            for m in ("https://gh-proxy.com/", "https://gh-proxy.net/", "https://ghps.cc/"):
                try:
                    return json.loads(fetch(m + u, use_proxy=False))
                except Exception:
                    continue
        return None

    ex = ThreadPoolExecutor(max_workers=3)
    try:
        for data in ex.map(grab, pages):
            its = data.get("items", []) if isinstance(data, dict) else []
            if not its:
                break
            items.extend(its)
            if len(items) >= limit:
                break
    finally:
        ex.shutdown(wait=False)
    if not items:
        return [("GitHub 搜索失败（API 限流或网络异常，可尝试更换节点）", "")]
    return [("★%d  %s  |  %s" % (it["stargazers_count"], it["full_name"], (it.get("description") or "")[:60]),
             (GH_MIRROR if not PROXY else "") + it["html_url"]) for it in items[:limit]]

def _extract(html_text, patterns):
    out = []
    for pat in patterns:
        for m in re.finditer(pat, html_text, re.S):
            link = html.unescape(m.group(1)).strip()
            title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            if link.startswith("http") and title and len(title) > 2:
                out.append((title[:90], link))
    return out


def _sogou_page(q, limit):
    """360 \u641c\u7d22\uff1aPC \u7248 www.so.com \u7ffb\u9875\uff1b\u7a7a\u9875/\u9a8c\u8bc1\u98ce\u63a7\u81ea\u52a8\u964d\u7ea7 m.so.com \u79fb\u52a8\u7248\uff0c\u518d\u964d\u7ea7 news.so.com \u65b0\u95fb\u641c\u7d22\uff08IP \u98ce\u63a7\u65f6\u4ecd\u53ef\u7528\uff09"""
    from concurrent.futures import ThreadPoolExecutor
    out, seen = [], set()

    def grab(pn):
        url = "https://www.so.com/s?q=%s&pn=%d" % (urllib.parse.quote(q), pn)
        try:
            d = fetch(url, use_proxy=False)  # \u56fd\u5185\u76f4\u8fde\u4f18\u5148
        except Exception:
            return []
        if not d or "\u9a8c\u8bc1" in d or "\u5f02\u5e38" in d or len(d) < 4000:
            return []  # \u98ce\u63a7\u9875/\u7a7a\u7ed3\u679c\u9875 \u2192 \u4ea4\u7ed9\u964d\u7ea7\u8def\u5f84
        res = []
        for t, u in _extract(d, [r'<h3[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>']):
            if "ai.so.com" in u or "so.com/s?q=" in u:
                continue  # \u8fc7\u6ee4 AI \u63a8\u8350\u4f4d/\u7ad9\u5185\u641c\u7d22\u94fe\u63a5
            t2 = re.sub(r"^\d{2}:\d{2}:\d{2}", "", t).strip()  # \u53bb\u6389\u65f6\u95f4\u6233\u524d\u7f00
            res.append((t2, u))
        return res

    ex = ThreadPoolExecutor(max_workers=3)
    try:
        for chunk in ex.map(grab, range(1, 7)):  # PC \u7248 6 \u9875\u5e76\u884c
            for t, u in chunk:
                if len(out) >= limit:
                    break
                key = _dedup_key(u)
                if key in seen:
                    continue
                seen.add(key)
                out.append((t, u))
    finally:
        ex.shutdown(wait=False)
    if out:
        return out
    # \u964d\u7ea71\uff1am.so.com \u79fb\u52a8\u7248\uff08\u7a33\u5b9a 12 \u6761\uff1b\u7ffb\u9875\u53c2\u6570\u65e0\u6548\uff0c\u4ec5\u53d6\u7b2c\u4e00\u9875\uff09
    try:
        d = fetch("https://m.so.com/s?q=%s" % urllib.parse.quote(q), use_proxy=False)
        if d and "\u9a8c\u8bc1" not in d:  # \u9a8c\u8bc1\u7801\u9875(IP\u98ce\u63a7) \u76f4\u63a5\u8df3\u8fc7
            for m in re.finditer(r'<h3[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', d, re.S):
                u = html.unescape(m.group(1)).strip()
                if "jump?u=" in u:  # \u79fb\u52a8\u7248\u8df3\u8f6c\u94fe\u63a5\u8fd8\u539f\u771f\u5b9e\u5730\u5740
                    u = urllib.parse.unquote(u.split("jump?u=")[1].split("&")[0])
                t = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                t = re.sub(r"^(\u6587\u7ae0\u6d4f\u89c8\u9605\u8bfb[\d.]+w?\u6b21\s*\u70b9\u8d5e\u6570\u6b21\s*|\u7b80\u4ecb\uff1a)", "", t).strip()
                if u.startswith("http") and t and "#close" not in u and "m.so.com/s?" not in u:
                    key = _dedup_key(u)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((t[:90], u))
                    if len(out) >= limit:
                        break
    except Exception:
        pass
    if out:
        return out
    # \u964d\u7ea72\uff1anews.so.com \u65b0\u95fb\u641c\u7d22\uff08IP \u9a8c\u8bc1\u98ce\u63a7\u65f6\u4ecd\u53ef\u7528\uff0c\u771f\u5b9e\u94fe\u63a5\uff09
    try:
        d = fetch("https://news.so.com/ns?q=%s" % urllib.parse.quote(q), use_proxy=False)
        for blk in re.findall(r'<li class="full-txt.*?</li>', d, re.S):
            mh = re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*title="([^"]*)"', blk)
            if not mh:
                continue
            u = html.unescape(mh.group(1)).strip()
            t = html.unescape(mh.group(2)).strip()
            if u.startswith("http") and t and len(t) > 2 and "so.com" not in u:
                key = _dedup_key(u)
                if key in seen:
                    continue
                seen.add(key)
                out.append((t[:90], u))
                if len(out) >= limit:
                    break
    except Exception:
        pass
    return out


def _ddg_page(q, limit):
    """DDG 双入口(lite/html) x 双通道(直连/代理)，空结果自动切换，保证稳定出结果"""
    urls = [
        "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(q),
        "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q),
    ]
    best = []
    for url in urls:
        for use_proxy in (False, True):
            try:
                d = fetch(url, use_proxy=use_proxy)
            except Exception:
                continue
            out = []
            for m in re.finditer(r'<a[^>]*rel="nofollow"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', d, re.S):
                link = html.unescape(m.group(1)).strip()
                if "uddg=" in link:  # DDG 跳转链接还原真实地址
                    link = urllib.parse.unquote(link.split("uddg=")[1].split("&")[0])
                title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                if link.startswith("http") and title and len(title) > 2 and "duckduckgo.com" not in link:
                    out.append((title[:90], link))
            if len(out) > len(best):
                best = out
            if len(best) >= limit:
                return best[:limit]
    return best[:limit]



def _google_page(q, limit):
    # Google 网页搜索已全线 JS 渲染（无 JS 拿不到结果），改用 Google News RSS（同为 Google 索引结果，走内置代理稳定可用）
    import xml.etree.ElementTree as ET
    d = fetch("https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans")
    out = []
    root = ET.fromstring(d)
    for it in root.iter("item"):
        t = html.unescape((it.findtext("title") or "").strip())
        u = (it.findtext("link") or "").strip()
        if t and u.startswith("http"):
            out.append((t[:90], u))
        if len(out) >= limit:
            break
    return out


def _dedup_key(url):
    """去重键：360 跳转链接(so.com/link?m=)含加密参数必须保留完整 URL，其余去掉 query"""
    if "so.com/link" in url:
        return url
    return url.split("?")[0].rstrip("/")


def bing_search(q, limit=10):
    """全网网页搜索：360/DDG/Google 并行贡献，Bing 最后补齐到满额"""
    from concurrent.futures import ThreadPoolExecutor
    engines = [("360", _sogou_page, max(8, min(limit // 2, 15))),
               ("ddg", _ddg_page, max(3, min(limit // 5, 10))),
               ("google", _google_page, max(3, min(limit // 10, 15)))]
    out, seen = [], set()
    labels = {"bing": "Bing", "ddg": "DuckDuckGo", "360": "360", "google": "Google"}
    ex = ThreadPoolExecutor(max_workers=3)
    futs = [(name, per, ex.submit(fn, q, limit)) for name, fn, per in engines]
    try:
        for name, per, fut in futs:
            try:
                got = 0
                for title, url in fut.result(timeout=45):
                    if got >= per:
                        break
                    key = _dedup_key(url)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(("[%s] %s" % (labels.get(name, name), title), url))
                    got += 1
                    if len(out) >= limit:
                        break
            except Exception:
                continue
            if len(out) >= limit:
                break
    finally:
        ex.shutdown(wait=False)  # 不等待卡住的引擎线程
    # Bing 最后串行补满（避免与其它引擎并发触发 Bing 限流只给第 1 页）
    if len(out) < limit:
        try:
            for title, url in bing_page(q, limit):
                key = _dedup_key(url)
                if key in seen:
                    continue
                seen.add(key)
                out.append(("[Bing] %s" % title, url))
                if len(out) >= limit:
                    break
        except Exception:
            pass
    # 四源保底：缺哪个引擎 → 专项重抓（换入口/通道），保证四个引擎都有结果
    have = set()
    for t, _u in out:
        for k in labels.values():
            if t.startswith("[" + k + "]"):
                have.add(k)
    for name, fn, lab in [("ddg", _ddg_page, "DuckDuckGo"), ("360", _sogou_page, "360"),
                          ("google", _google_page, "Google"), ("bing", bing_page, "Bing")]:
        if lab in have:
            continue  # 已有该引擎；缺失的引擎必须补至少 1 条（即使总数已到 limit）
        try:
            for title, url in fn(q, max(5, limit - len(out))):
                key = _dedup_key(url)
                if key in seen:
                    continue
                seen.add(key)
                out.append(("[" + lab + "] " + title, url))
                if len(out) >= limit:
                    break
        except Exception:
            continue
    # Bing 结果置顶（避免被 Google 大量结果淹没，用户第一眼看到 [Bing]）
    bing_items = [(t, u) for t, u in out if t.startswith("[Bing]")]
    others = [(t, u) for t, u in out if not t.startswith("[Bing]")]
    out = bing_items + others
    return out if out else [("网页结果获取失败", "")]


def bing_page(q, limit):
    from concurrent.futures import ThreadPoolExecutor
    out = []
    pages = list(range(1, min(limit, 60) + 1, 10))  # Bing \u6bcf\u9875\u5b9e\u9645\u7ea6 10 \u6761\uff0c\u6b65\u8fdb 10 \u8fde\u7eed\u7ffb\u9875

    def _fb(url, use_proxy, cn=False):
        # Bing \u5e26 Cookie \u8bf7\u6c42\uff08\u65e0 cookie \u8fde\u7eed\u8bf7\u6c42\u6613\u89e6\u53d1\u9650\u6d41\uff09
        if cn:  # cn.bing.com \u56fd\u5185\u76f4\u8fde\u901a\u9053\uff08\u4ee3\u7406\u51fa\u53e3 IP \u88ab\u9650\u6d41\u65f6\u4f7f\u7528\uff09
            url = url.replace("www.bing.com", "cn.bing.com")
        hdr = dict(HDRS)
        hdr["Cookie"] = "SRCHHPGUSR=SRCHLANG=zh-Hans; _EDGE_S=mkt=zh-cn; MUID=0A1B2C3D4E5F60718293A4B5C6D7E8F9"
        req = urllib.request.Request(url, headers=hdr)
        if PROXY and use_proxy:
            op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
            with op.open(req, timeout=8) as r:
                return r.read().decode("utf-8", "ignore")
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read().decode("utf-8", "ignore")

    def grab(first):
        url = ("https://www.bing.com/search?q=" + urllib.parse.quote(q)
               + "&mkt=zh-CN&count=30&first=%d" % first)

        def parse(d):
            if not d or len(d) < 3000:
                return []
            res = []
            for m in re.finditer(r'<h2[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', d, re.S):
                link = html.unescape(m.group(1)).strip()
                title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                if link.startswith("http") and title and "bing.com" not in link:
                    res.append((title[:90], link))
            return res

        # \u4ee3\u7406\u4f18\u5148\uff08GUI \u5185\u7f6e\u4ee3\u7406\u7a33\u5b9a\u51fa\u7ed3\u679c\uff09
        res = []
        try:
            res = parse(_fb(url, True))
        except Exception:
            res = []
        if not res:  # \u9650\u6d41/\u7a7a\u7ed3\u679c \u2192 \u51b7\u5374\u540e\u91cd\u8bd5\u4e00\u6b21
            try:
                time.sleep(1.5)
                res = parse(_fb(url, True))
            except Exception:
                res = []
        if not res:  # cn.bing.com \u56fd\u5185\u76f4\u8fde\uff08\u4ee3\u7406\u51fa\u53e3 IP \u88ab\u9650\u6d41\u65f6\u7684\u5907\u7528\u901a\u9053\uff09
            try:
                res = parse(_fb(url, False, cn=True))
            except Exception:
                res = []
        if not res:  # \u76f4\u8fde\u515c\u5e95\uff08www.bing.com\uff09
            try:
                res = parse(_fb(url, False))
            except Exception:
                res = []
        return res

    ex = ThreadPoolExecutor(max_workers=3)
    try:
        for chunk in ex.map(grab, pages):
            for t, u in chunk:
                if len(out) >= limit:
                    break
                out.append((t, u))
    finally:
        ex.shutdown(wait=False)
    return out



def so_search(q, limit=10):
    # 中文关键词先翻译成英文再搜（Stack Overflow 是英文站）；每页 100 条翻页并行
    from concurrent.futures import ThreadPoolExecutor
    sq = translate_cn(q) if re.search(r"[\u4e00-\u9fff]", q) else q
    url = ("https://api.stackexchange.com/2.3/search/advanced?q=" + urllib.parse.quote(sq)
           + "&site=stackoverflow&pagesize=100&order=desc&sort=votes")  # 按访问量(投票数)降序
    out = []

    def grab(page):
        u = url + "&page=%d" % page
        try:
            return json.loads(fetch(u, use_proxy=False))  # 直连优先：避开机场共享 IP 被 SO 限流
        except Exception:
            try:
                return json.loads(fetch(u))  # 直连失败走代理重试
            except Exception:
                return None

    ex = ThreadPoolExecutor(max_workers=3)
    try:
        for data in ex.map(grab, range(1, min((limit + 99) // 100, 5) + 1)):
            if not data:
                break
            its = data.get("items", [])
            if not its:
                break
            out.extend(its)
            if len(out) >= limit:
                break
    finally:
        ex.shutdown(wait=False)
    if not out:
        return [("Stack Overflow 搜索失败（网络或限流，可稍后重试）", "")]
    return [("%d↑  %s" % (it.get("score", 0), it["title"][:80]), it["link"]) for it in out[:limit]]

def npm_search(q, limit=10):
    # npm 搜索 API size 硬顶 250，from 参数翻页补足
    from concurrent.futures import ThreadPoolExecutor
    base = "https://registry.npmjs.org/-/v1/search?text=" + urllib.parse.quote(q)
    out = []

    def grab(frm):
        u = base + "&size=100&from=%d" % frm
        try:
            return json.loads(fetch(u, use_proxy=False))  # 直连优先：registry.npmjs.org 国内可直连
        except Exception:
            try:
                return json.loads(fetch(u))
            except Exception:
                return None

    ex = ThreadPoolExecutor(max_workers=3)
    try:
        for data in ex.map(grab, range(0, min(limit, 2000), 100)):  # npm 搜索接口单次最多 2000 条（接口硬顶）
            if not data:
                break
            objs = data.get("objects", [])
            if not objs:
                break
            out.extend(objs)
            if len(out) >= limit:
                break
    finally:
        ex.shutdown(wait=False)
    if out:
        top = out[0].get("searchScore", 0) or 1
        out = [o for o in out if o.get("searchScore", 0) >= top * 0.2]
        out.sort(key=lambda o: (o.get("score") or {}).get("detail", {}).get("popularity", 0), reverse=True)  # 按下载热度降序
    ret = []
    for o in out:
        p = o["package"]
        link = (p.get("links", {}) or {}).get("npm") or (p.get("links", {}) or {}).get("homepage") or ""
        ret.append((p["name"] + "  |  " + (p.get("description") or "")[:60], link))
    return ret if ret else [("npm 搜索失败（网络异常）", "")]

SOURCES = [("GitHub 仓库", github_search), ("网页结果", bing_search),
           ("Stack Overflow", so_search), ("npm 包", npm_search)]
FAV_LABEL = "★ 收藏"
ICONS = {"GitHub 仓库": "◆ GitHub", "网页结果": "◎ 网页", "Stack Overflow": "▲ Stack Overflow",
         "npm 包": "● npm", FAV_LABEL: "★ 收藏"}

TERM_MAP = {
    "机器人": "bot", "爬虫": "crawler", "教程": "tutorial", "框架": "framework",
    "插件": "plugin", "脚本": "script", "定时": "cron", "聊天": "chat",
    "图片": "image", "视频": "video", "网页": "web", "服务器": "server",
    "部署": "deploy", "测试": "test", "调试": "debug", "日志": "log",
    "监控": "monitor", "验证码": "captcha", "支付": "payment", "接口": "api",
    "前端": "frontend", "后端": "backend", "机器学习": "machine learning",
    "深度学习": "deep learning", "人工智能": "ai", "大模型": "llm",
    "数据库": "database", "自动化": "automation", "翻译": "translate",
    "搜索": "search", "下载": "download", "上传": "upload", "登录": "login",
    "注册": "signup", "爬取": "scrape", "分析": "analyze", "数据": "data",
    "网络": "network", "安全": "security", "加密": "encryption",
    "性能": "performance", "优化": "optimize", "异步": "async",
    "并发": "concurrency", "缓存": "cache", "队列": "queue", "消息": "message",
    "邮件": "email", "短信": "sms", "定位": "location", "地图": "map",
    "天气": "weather", "文件": "file", "压缩": "zip", "备份": "backup",
    "恢复": "recovery", "系统": "system", "游戏": "game", "工具": "tool",
    "客户端": "client", "验证": "verify", "处理": "process", "生成": "generate",
    "转换": "convert", "推送": "push", "通知": "notification",
    "会话": "session", "认证": "auth", "权限": "permission",
    "批量": "batch", "实时": "realtime", "统计": "stats", "报表": "report",
    "表单": "form", "页面": "page", "样式": "css", "布局": "layout",
    "浏览器": "browser", "手机": "mobile", "桌面": "desktop", "跨平台": "cross platform",
    "开源": "open source", "免费": "free", "云": "cloud", "容器": "docker",
    "微信": "wechat", "公众号": "wechat official account",
    "安装": "install", "使用": "use", "如何": "how", "为什么": "why",
    "错误": "error", "报错": "error", "异常": "exception", "解决": "fix",
    "问题": "problem", "请求": "request", "发送": "send", "获取": "get",
    "读取": "read", "写入": "write", "设置": "set", "配置": "config",
    "运行": "run", "启动": "start", "停止": "stop", "重启": "restart",
    "导入": "import", "模块": "module", "包": "package", "依赖": "dependency",
    "代码": "code", "函数": "function", "方法": "method", "类": "class",
    "对象": "object", "变量": "variable", "数组": "array", "列表": "list",
    "字典": "dict", "字符串": "string", "数字": "number", "循环": "loop",
    "线程": "thread", "进程": "process", "内存": "memory", "端口": "port",
    "连接": "connection", "版本": "version", "环境": "environment",
    "编程": "programming", "开发": "development", "项目": "project",
    "源码": "source code", "编译": "compile", "解释": "interpret",
    "正则": "regex", "时间": "time", "日期": "date", "列表推导": "list comprehension",
    "虚拟环境": "virtualenv", "包管理": "package manager", "命令行": "cli",
    "怎么": "how", "什么": "what", "哪个": "which", "可以": "can", "能": "can",
    "需要": "need", "想要": "want", "还有": "also", "一个": "a", "这个": "this",
    "那个": "that", "现在": "now", "最新": "latest", "简单": "simple",
    "完整": "full", "详细": "detail", "例子": "example", "示例": "example",
    "文档": "docs", "参考": "reference", "实现": "implement", "调用": "call",
    "返回": "return", "参数": "parameter", "输出": "output", "输入": "input",
    "保存": "save", "删除": "delete", "创建": "create", "更新": "update",
    "修改": "modify", "查找": "find", "过滤": "filter", "排序": "sort",
    "合并": "merge", "拆分": "split", "拼接": "concat", "格式化": "format",
    "解析": "parse", "编码": "encode", "解码": "decode", "区别": "difference",
    "比较": "compare", "无法": "cannot", "失败": "fail", "成功": "success",
    "之间": "between", "里面": "inside", "外部": "external", "所有": "all",
    "每个": "each", "多个": "multiple", "单个": "single", "同时": "simultaneously",
    "自动": "automatic", "手动": "manual", "本地": "local", "远程": "remote",
    "静态": "static", "动态": "dynamic", "全局": "global", "局部": "local",
    "装饰器": "decorator", "生成器": "generator", "迭代器": "iterator",
    "元组": "tuple", "集合": "set", "上下文": "context", "闭包": "closure",
    "继承": "inheritance", "多态": "polymorphism", "抽象": "abstract",
    "构造函数": "constructor", "类方法": "classmethod", "静态方法": "staticmethod",
}

def translate_cn(q):
    try:
        import translators as ts
        for t in ("alibaba", "iciba"):
            try:
                r = (ts.translate_text(q, translator=t, from_language="zh", to_language="en") or "").strip()
                if r and any(c.isascii() and c.isalpha() for c in r):
                    return r
            except Exception:
                continue
    except Exception:
        pass
    parts = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", q)
    en, mapped = [], False
    words = sorted(TERM_MAP, key=len, reverse=True)
    for p in parts:
        if "\u4e00" <= p[0] <= "\u9fff":
            i = 0
            while i < len(p):
                hit = False
                for w in words:
                    if p.startswith(w, i):
                        en.append(TERM_MAP[w])
                        i += len(w)
                        mapped = True
                        hit = True
                        break
                if not hit:
                    i += 1  # 未收录中文词丢弃，不阻断翻译
        else:
            en.append(p)
    if mapped and en:
        return " ".join(en)
    return None

def is_cjk(s):
    return any('\u4e00' <= c <= '\u9fff' for c in s)

def search_one(args):
    label, fn, q, limit = args
    try:
        if label == "Stack Overflow" and is_cjk(q):
            en = translate_cn(q)
            if en:
                return label, [("已自动翻译为英文: " + en, "")] + fn(en, limit)
            return label, [("词典未收录，建议用英文搜 SO（如 wechat bot）", "")]
        return label, fn(q, limit)
    except Exception as e:
        return label, [("搜索失败: " + str(e)[:80], "")]

_CACHE = {}
CACHE_TTL = 60  # 搜索结果缓存秒数（1 分钟内重复搜索走缓存）
FETCH_LIMIT = 10 ** 9  # 无上限（各引擎内部仍有 API 限流保护性 cap，如 GitHub/SO 最多 5 页、Bing 最多 60 页）  # 每源抓取上限（API 硬顶内尽力多抓：GitHub/SO 翻3页、npm 250、网页多引擎累加）
PAGE_SIZE = 10  # 每页展示条数(初始值)


def _dedup(results):
    """跨源去重：同一链接只保留第一个来源"""
    seen = set()
    out = {l: [] for l, _ in SOURCES}
    for label, _ in SOURCES:
        for line, url in results.get(label, []):
            key = (url or line).strip().rstrip("/") or line
            if key in seen:
                continue
            seen.add(key)
            out[label].append((line, url))
    return out


def search_all(q, limit, lang=None):
    key = (q, limit, lang)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    from concurrent.futures import ThreadPoolExecutor
    gh_q = (q + " language:" + lang) if lang else q
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = dict(ex.map(search_one,
                              [(l, f, (gh_q if l == "GitHub 仓库" else q), limit) for l, f in SOURCES]))
    results = _dedup(results)
    fail = any(not u for v in results.values() for _, u in v)
    # 失败结果只缓存 15 秒，正常结果缓存 CACHE_TTL
    age = CACHE_TTL - 15 if fail else 0
    _CACHE[key] = (time.time() - age, results)
    return results

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception:
        pass

THEMES = {
    "light": {"bg": "#f0f4f8", "card": "#ffffff", "line": "#e2e8f0", "fg": "#1e293b",
              "sub": "#64748b", "accent": "#2563eb", "accent_h": "#1d4ed8", "tab": "#dbe4ee",
              "tab_h": "#c9d6e4", "status": "#e2e8f0", "scroll": "#c3cedb"},
    "dark": {"bg": "#0f172a", "card": "#1e293b", "line": "#334155", "fg": "#e2e8f0",
             "sub": "#94a3b8", "accent": "#3b82f6", "accent_h": "#2563eb", "tab": "#334155",
             "tab_h": "#475569", "status": "#1e293b", "scroll": "#475569"},
}

def system_dark():
    """读 Windows 系统深浅色设置（True=深色）"""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        winreg.CloseKey(k)
        return v == 0
    except Exception:
        return False


def ver_slug(dl):
    """从下载链接提取版本号，用于临时安装包文件名"""
    m = re.search(r"Setup-([\d.]+)\.exe", dl or "")
    return m.group(1) if m else "latest"


class App:
    def __init__(self, root):
        self.root = root
        cfg = load_json(CONFIG_FILE, {}) or {}
        self._apply_data_dir(cfg)
        self.dark = cfg.get("dark") if "dark" in cfg else system_dark()
        global PROXY
        PROXY = (cfg.get("proxy") or "").strip()
        self.sub_url = cfg.get("sub_url") if "sub_url" in cfg else SUB_URL_DEFAULT
        self.builtin_off = bool(cfg.get("builtin_off", False))
        self.history = load_json(HIST_FILE, [])
        self.favorites = load_json(FAV_FILE, [])
        self.data = {}
        root.title("搜索聚合 · 圆圆")
        defw = min(1240, root.winfo_screenwidth() - 40)  # DPI 缩放时自动收进屏幕
        defh = min(800, root.winfo_screenheight() - 60)
        if cfg.get("geometry") and cfg.get("geom_v") == APP_VERSION:
            try:
                root.geometry(cfg["geometry"])
            except Exception:
                root.geometry("%dx%d" % (defw, defh))
        else:
            root.geometry("%dx%d" % (defw, defh))
        root.minsize(760, 520)
        self.build()
        self.apply_theme()
        self.switch(SOURCES[0][0])
        self.refresh_fav()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._tray = None
        self._tray_ready = False
        self._setup_tray()
        root.bind("<Unmap>", self._on_unmap)
        if self.sub_url and not self.builtin_off and (PROXY == "" or PROXY.startswith("http://127.0.0.1:")):
            def _auto():
                def _w():
                    try:
                        start_builtin_clash(self.sub_url)
                        ok, msg = True, "内置代理已启动 (127.0.0.1:%d) ✓" % CLASH_PORT
                    except Exception as e:
                        ok, msg = False, "内置代理启动失败: " + str(e)[:60]
                    self.root.after(0, lambda: self._auto_done(ok, msg))
                threading.Thread(target=_w, daemon=True).start()
            root.after(300, _auto)
        # 启动后后台检查更新（等内置代理就绪，再额外延时）
        root.after(6000, lambda: threading.Thread(target=self._check_update, daemon=True).start())
        root.after(100, self.entry.focus_set)

    # ---------- UI 构建 ----------
    def build(self):
        root = self.root
        self.top = ttk.Frame(root)
        self.top.pack(fill="x")
        head = ttk.Frame(self.top)
        head.pack(fill="x", padx=18, pady=(14, 0))
        ttk.Label(head, text="搜索聚合", style="Title.TLabel").pack(side="left")
        self.pin_btn = ttk.Button(head, text="置顶", style="Ghost.TButton",
                                  command=self.toggle_pin, cursor="hand2", width=5)
        self.pin_btn.pack(side="right")
        self.help_btn = ttk.Button(head, text="帮助", style="Ghost.TButton",
                                   command=self.open_help, cursor="hand2", width=6)
        self.help_btn.pack(side="right", padx=(0, 8))
        self.set_btn = ttk.Button(head, text="设置", style="Ghost.TButton",
                                  command=self.open_settings, cursor="hand2", width=6)
        self.set_btn.pack(side="right", padx=(0, 8))
        ttk.Label(self.top, text="GitHub · 网页 · Stack Overflow · npm ｜ 双击打开 · 右键复制 · Ctrl+F 聚焦", style="Sub.TLabel").pack(anchor="w", padx=18, pady=(2, 10))
        self.bar = ttk.Frame(self.top, style="Card.TFrame", padding=(10, 8))
        self.bar.pack(fill="x", padx=18)
        ttk.Label(self.bar, text="关键词", style="Card.TLabel", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left", padx=(2, 8))
        self.entry = ttk.Combobox(self.bar, values=self.history[:20])
        self.entry.pack(side="left", fill="x", expand=True, ipady=2)
        self.entry.bind("<Return>", lambda e: self.run())
        self.lang_var = tk.StringVar(value="全部语言")
        self.lang_combo = ttk.Combobox(self.bar, textvariable=self.lang_var, state="readonly", width=8,
                                       values=["全部语言", "Python", "JavaScript", "TypeScript", "Go", "Java",
                                               "C++", "C", "Rust", "Shell", "HTML", "CSS", "PHP", "C#", "Ruby"])
        self.lang_combo.pack(side="left", padx=(4, 0))
        self.btn = ttk.Button(self.bar, text="搜 索", style="Accent.TButton", command=self.run, cursor="hand2")
        self.btn.pack(side="left", padx=(8, 2))
        self.spinner = ttk.Label(self.bar, text="", style="Spin.TLabel")
        self.spinner.pack(side="left", padx=(8, 0))
        self._searching = False
        self._spin_idx = 0
        self.fav_btn = ttk.Button(self.bar, text="☆ 收藏", style="Ghost.TButton", command=self.fav_current, cursor="hand2", width=8)
        self.fav_btn.pack(side="left", padx=(2, 0))
        self.theme_btn = ttk.Button(self.bar, text="深色", style="Ghost.TButton", command=self.toggle_theme, cursor="hand2", width=4)
        self.theme_btn.pack(side="left", padx=(2, 0))
        self.proxy_btn = ttk.Button(self.bar, text="代理", style="Ghost.TButton", command=self.set_proxy, cursor="hand2", width=4)
        self.proxy_btn.pack(side="left", padx=(2, 0))
        self.builtin_btn = ttk.Button(self.bar, text="", style="Ghost.TButton", command=self.toggle_builtin, cursor="hand2", width=11)
        self.builtin_btn.pack(side="left", padx=(2, 0))

        self.tabbar = ttk.Frame(root, style="Card.TFrame", padding=(18, 8))
        self.tabbar.pack(fill="x", pady=(10, 0))
        self.tab_btns = {}
        self.frames = {}
        self.trees = {}
        self.page_bars = {}  # 各标签页底部翻页条 (prev_btn, page_lbl, next_btn)
        self.loading_lbls = {}  # 各标签页搜索中提示（窗口内）
        self.page = {}  # 各标签当前页码
        self.total = {}  # 各标签总条数
        self.page_size = PAGE_SIZE  # 每页条数，随窗口大小自动调节
        self._geom = None
        self._resize_job = None
        self.root.bind("<Configure>", self._on_resize)
        self.unfav_btn = ttk.Button(self.tabbar, text="− 取消收藏", style="Ghost.TButton",
                                    command=self.fav_remove_current, cursor="hand2")
        self.unfav_btn.pack(side="right")
        for label in [l for l, _ in SOURCES] + [FAV_LABEL]:
            b = ttk.Button(self.tabbar, text=ICONS.get(label, label), style="Tab.TButton", cursor="hand2",
                           command=lambda k=label: self.switch(k))
            b.pack(side="left", padx=(0, 6))
            self.tab_btns[label] = b
            f = ttk.Frame(root, style="Card.TFrame")
            tree = ttk.Treeview(f, columns=("desc", "link"), show="headings",
                                style="Result.Treeview", cursor="hand2", selectmode="extended")
            tree.heading("desc", text="结果")
            tree.heading("link", text="链接")
            tree.column("desc", width=560, anchor="w", stretch=True)
            tree.column("link", width=340, anchor="w", stretch=False)
            # 搜索中提示：嵌在窗口内（当前标签页中央），不弹独立窗口
            load_lbl = ttk.Label(f, text="◐ 正在搜索，请稍候…",
                                 font=("Microsoft YaHei UI", 15, "bold"), style="Card.TLabel")
            load_lbl.place_forget()
            self.loading_lbls[label] = load_lbl
            # 底部翻页条（窗口缩窄不会被盖住）
            pbar = ttk.Frame(f, style="Card.TFrame")
            pbar.pack(side="bottom", fill="x", pady=(6, 0))
            pnext = ttk.Button(pbar, text="下一页 ▶", style="Ghost.TButton",
                               command=lambda l=label: self.page_next(l), cursor="hand2")
            pnext.pack(side="right")
            plbl = ttk.Label(pbar, text="", style="Card.TLabel", font=("Microsoft YaHei UI", 9))
            plbl.pack(side="right", padx=8)
            pprev = ttk.Button(pbar, text="◀ 上一页", style="Ghost.TButton",
                               command=lambda l=label: self.page_prev(l), cursor="hand2")
            pprev.pack(side="right", padx=(0, 4))
            self.page_bars[label] = (pprev, plbl, pnext)
            sb = ttk.Scrollbar(f, orient="vertical", command=tree.yview, style="Vertical.TScrollbar")
            tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tree.pack(fill="both", expand=True)
            tree.bind("<Double-Button-1>", lambda e, k=label: self.open_selected(k))
            tree.bind("<Button-3>", lambda e, k=label: self.show_menu(k, e))
            tree.bind("<<TreeviewSelect>>", lambda e: self.update_fav_btn())
            self.frames[label] = f
            self.trees[label] = tree
            self.data[label] = []
        self.content = ttk.Frame(root, style="Card.TFrame")
        self.content.pack(fill="both", expand=True, padx=18, pady=(6, 6))
        for label, f in self.frames.items():
            f.place(in_=self.content, x=0, y=0, relwidth=1, relheight=1)
        self.status = ttk.Label(root, text="就绪", style="Status.TLabel", anchor="w", padding=(18, 6))
        self.status.pack(fill="x")
        self.update_builtin_btn()

        root.bind("<Control-f>", lambda e: (self.entry.focus_set(), self.entry.select_range(0, "end")))
        root.bind("<Control-c>", lambda e: self.copy_selected(self.current))
        root.bind("<Control-d>", lambda e: self.toggle_theme())
        root.bind("<Control-s>", lambda e: self.run())
        root.bind_all("<Delete>", lambda e: self.fav_remove_current())

    def apply_theme(self):
        t = THEMES["dark" if self.dark else "light"]
        self.root.configure(bg=t["bg"])
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", font=("Microsoft YaHei UI", 10), background=t["bg"], foreground=t["fg"])
        style.configure("TFrame", background=t["bg"])
        style.configure("Card.TFrame", background=t["card"])
        style.configure("TLabel", background=t["bg"], foreground=t["fg"])
        style.configure("Card.TLabel", background=t["card"], foreground=t["fg"])
        style.configure("Title.TLabel", background=t["bg"], foreground=t["fg"], font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Sub.TLabel", background=t["bg"], foreground=t["sub"], font=("Microsoft YaHei UI", 9))
        style.configure("TCombobox", fieldbackground=t["card"], background=t["card"], foreground=t["fg"],
                        bordercolor=t["line"], lightcolor=t["line"], darkcolor=t["line"],
                        arrowcolor=t["sub"], padding=6, font=("Microsoft YaHei UI", 11))
        style.map("TCombobox", bordercolor=[("focus", t["accent"])],
                  fieldbackground=[("readonly", t["card"])], foreground=[("readonly", t["fg"])])
        style.configure("Accent.TButton", background=t["accent"], foreground="#ffffff", borderwidth=0,
                        focusthickness=0, padding=(18, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", t["accent_h"]), ("disabled", "#93c5fd")])
        style.configure("Ghost.TButton", background=t["card"], foreground=t["fg"], borderwidth=1,
                        bordercolor=t["line"], focusthickness=0, padding=(10, 8),
                        font=("Microsoft YaHei UI", 10))
        style.map("Ghost.TButton", background=[("active", t["tab"])])
        style.configure("FavOn.TButton", background="#f59e0b", foreground="#ffffff", borderwidth=0,
                        focusthickness=0, padding=(10, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("FavOn.TButton", background=[("active", "#d97706")])
        style.configure("BuiltinOn.TButton", background="#16a34a", foreground="#ffffff", borderwidth=0,
                        focusthickness=0, padding=(10, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("BuiltinOn.TButton", background=[("active", "#15803d"), ("disabled", "#86b98a")])
        style.configure("BuiltinOff.TButton", background=t["tab"], foreground=t["sub"], borderwidth=0,
                        focusthickness=0, padding=(10, 8), font=("Microsoft YaHei UI", 10))
        style.map("BuiltinOff.TButton", background=[("active", t["tab_h"])])
        style.configure("Tab.TButton", background=t["tab"], foreground=t["sub"], borderwidth=0,
                        focusthickness=0, padding=(20, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Tab.TButton", background=[("active", t["tab_h"])])
        style.configure("TabSel.TButton", background=t["accent"], foreground="#ffffff", borderwidth=0,
                        focusthickness=0, padding=(20, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("TabSel.TButton", background=[("active", t["accent_h"])])
        style.configure("Result.Treeview", background=t["card"], fieldbackground=t["card"],
                        foreground=t["fg"], rowheight=30, borderwidth=0, font=("Microsoft YaHei UI", 10))
        style.map("Result.Treeview", background=[("selected", t["accent"])],
                  foreground=[("selected", "#ffffff")])
        style.configure("Result.Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"),
                        background=t["card"], foreground=t["sub"], relief="flat", borderwidth=0)
        style.configure("Vertical.TScrollbar", background=t["scroll"], troughcolor=t["bg"],
                        borderwidth=0, arrowsize=0, width=10)
        style.map("Vertical.TScrollbar", background=[("active", t["accent"])])
        style.configure("Status.TLabel", background=t["status"], foreground=t["sub"], font=("Microsoft YaHei UI", 9))
        style.configure("Spin.TLabel", background=t["card"], foreground=t["accent"],
                        font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Busy.TLabel", background=t["status"], foreground=t["accent"],
                        font=("Microsoft YaHei UI", 9, "bold"))
        self.theme_btn.config(text="浅色" if self.dark else "深色")

    @staticmethod
    def _apply_data_dir(cfg):
        """按便携模式开关决定数据目录（frozen 才生效）"""
        global DATA_DIR, HIST_FILE, FAV_FILE, LOG_FILE, CLASH_DIR
        if cfg.get("portable") and getattr(sys, "frozen", False):
            DATA_DIR = os.path.join(os.path.dirname(sys.executable), "data")
        else:
            DATA_DIR = BASE
        os.makedirs(DATA_DIR, exist_ok=True)
        HIST_FILE = os.path.join(DATA_DIR, "history.json")
        FAV_FILE = os.path.join(DATA_DIR, "favorites.json")
        LOG_FILE = os.path.join(DATA_DIR, "error.log")
        CLASH_DIR = os.path.join(DATA_DIR, "clash")

    def toggle_pin(self):
        cur = bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", not cur)
        self.pin_btn.config(text="已置顶" if not cur else "置顶",
                            style="BuiltinOn.TButton" if not cur else "Ghost.TButton")
        self.status.config(text="窗口已置顶" if not cur else "已取消置顶")

    def toggle_theme(self):
        self.dark = not self.dark
        cfg = load_json(CONFIG_FILE, {}) or {}
        cfg["dark"] = self.dark
        save_json(CONFIG_FILE, cfg)
        self.apply_theme()

    def update_builtin_btn(self):
        running = CLASH_PROC is not None and CLASH_PROC.poll() is None
        self.builtin_btn.config(text="● 内置代理 开" if running else "○ 内置代理 关",
                                style="BuiltinOn.TButton" if running else "BuiltinOff.TButton")

    def toggle_builtin(self):
        global PROXY
        import tkinter.messagebox as mb
        running = CLASH_PROC is not None and CLASH_PROC.poll() is None
        cfg = load_json(CONFIG_FILE, {}) or {}
        if running:
            stop_builtin_clash()
            if PROXY.startswith("http://127.0.0.1:"):
                PROXY = ""
            cfg["builtin_off"] = True
            cfg["proxy"] = PROXY
            save_json(CONFIG_FILE, cfg)
            self.builtin_off = True
            self.status.config(text="内置代理已关闭（可点「代理」设置其它方式）")
            self.update_builtin_btn()
            mb.showinfo("内置代理", "已关闭 ✓", parent=self.root)
            return
        # 启动：后台线程执行，避免卡界面；完成后弹窗提示
        self.builtin_btn.config(state="disabled")
        self.status.config(text="正在启动内置代理...")

        def _work():
            sub = self.sub_url or SUB_URL_DEFAULT
            try:
                start_builtin_clash(sub)
                ok = True
                msg = "内置代理已启动 (127.0.0.1:%d) ✓" % CLASH_PORT
            except Exception as e:
                ok = False
                msg = "内置代理启动失败: " + str(e)[:70]
            self.root.after(0, lambda: self._on_start_done(ok, msg, sub, cfg))

        threading.Thread(target=_work, daemon=True).start()

    def _on_start_done(self, ok, msg, sub, cfg):
        global PROXY
        import tkinter.messagebox as mb
        self.builtin_btn.config(state="normal")
        if ok:
            PROXY = "http://127.0.0.1:%d" % CLASH_PORT
            cfg["builtin_off"] = False
            cfg["proxy"] = PROXY
            cfg["sub_url"] = sub
            save_json(CONFIG_FILE, cfg)
            self.builtin_off = False
            self.status.config(text=msg)
            mb.showinfo("内置代理", msg, parent=self.root)
        else:
            PROXY = ""
            self.status.config(text=msg)
            import tkinter.messagebox as mb2
            if mb2.askyesno("内置代理", msg + "\n\n是否重试？", parent=self.root):
                self.toggle_builtin()
        self.update_builtin_btn()

    def _auto_done(self, ok, msg):
        global PROXY
        if ok:
            PROXY = "http://127.0.0.1:%d" % CLASH_PORT
        self.status.config(text=msg)
        self.update_builtin_btn()
        if ok:
            self._update_node_status()

    def _update_node_status(self):
        """在状态栏显示当前代理节点"""
        if CLASH_PROC is None or CLASH_PROC.poll() is not None:
            return
        try:
            data = clash_api("/proxies")
            proxies = data.get("proxies", {})
            g = next((k for k, v in proxies.items()
                      if v.get("type") in ("Selector", "URLTest", "Fallback") and k != "GLOBAL"), "GLOBAL")
            now = proxies.get(g, {}).get("now", "")
            if now:
                self.status.config(text="内置代理 · 节点: %s" % now)
        except Exception:
            pass

    def open_nodes(self):
        import tkinter.messagebox as mb
        running = CLASH_PROC is not None and CLASH_PROC.poll() is None
        if not running:
            mb.showinfo("节点管理", "内置代理未运行，请先开启代理", parent=self.root)
            return
        t = THEMES["dark" if self.dark else "light"]
        win = tk.Toplevel(self.root)
        win.title("节点管理")
        win.configure(bg=t["bg"])
        win.geometry("460x480")
        win.transient(self.root)
        try:
            data = clash_api("/proxies")
            proxies = data.get("proxies", {})
            groups = {k: v for k, v in proxies.items()
                      if v.get("type") in ("Selector", "URLTest", "Fallback")}
            if not groups:
                mb.showinfo("节点管理", "未找到可切换的节点组", parent=self.root)
                win.destroy()
                return
        except Exception as e:
            mb.showerror("节点管理", "读取节点失败: " + str(e)[:60], parent=self.root)
            win.destroy()
            return
        tk.Label(win, text="代理组", font=("Microsoft YaHei UI", 10, "bold"),
                 fg=t["sub"], bg=t["bg"]).pack(anchor="w", padx=14, pady=(12, 4))
        self._group_var = tk.StringVar(value=list(groups.keys())[0])
        combo = ttk.Combobox(win, textvariable=self._group_var, values=list(groups.keys()), state="readonly")
        combo.pack(fill="x", padx=14)
        combo.bind("<<ComboboxSelected>>", lambda e: self._nodes_refresh(win, groups))
        self._nodes_tree = ttk.Treeview(win, columns=("node", "delay"), show="headings", height=14)
        self._nodes_tree.heading("node", text="节点")
        self._nodes_tree.heading("delay", text="延迟")
        self._nodes_tree.column("node", width=320, anchor="w")
        self._nodes_tree.column("delay", width=80, anchor="center")
        self._nodes_tree.pack(fill="both", expand=True, padx=14, pady=(8, 6))
        bar = tk.Frame(win, bg=t["bg"])
        bar.pack(fill="x", padx=14, pady=(0, 12))
        tk.Button(bar, text="全部测速", font=("Microsoft YaHei UI", 10),
                  fg=t["accent"], bg=t["card"], activebackground=t["tab"], bd=1, relief="solid",
                  cursor="hand2", command=lambda: self._nodes_speed(win, groups)).pack(side="left")
        tk.Button(bar, text="切换选中", font=("Microsoft YaHei UI", 10, "bold"),
                  fg="#ffffff", bg=t["accent"], activebackground=t["accent_h"], bd=0,
                  cursor="hand2", command=lambda: self._nodes_switch(win, groups)).pack(side="left", padx=(8, 0))
        self._nodes_refresh(win, groups)

    def _nodes_refresh(self, win, groups):
        try:
            data = clash_api("/proxies")
            proxies = data.get("proxies", {})
        except Exception:
            return
        g = self._group_var.get()
        grp = proxies.get(g, {})
        tree = self._nodes_tree
        tree.delete(*tree.get_children())
        self._node_names = grp.get("all", []) or []
        now = grp.get("now", "")
        for n in self._node_names:
            tag = "sel" if n == now else ""
            tree.insert("", "end", values=(n, "当前" if n == now else "—"), tags=(tag,))
        tree.tag_configure("sel", background=t["accent"], foreground="#ffffff")

    def _nodes_speed(self, win, groups):
        def _w():
            tree = self._nodes_tree
            names = list(getattr(self, "_node_names", []) or [])
            for i, n in enumerate(names):
                try:
                    r = clash_api("/proxies/" + urllib.parse.quote(n, safe="") + "/delay?url=" +
                                  urllib.parse.quote("http://www.gstatic.com/generate_204") + "&timeout=2500")
                    d = r.get("delay")
                    tree.item(tree.get_children()[i], values=(n, ("%dms" % d) if d else "超时"))
                except Exception:
                    tree.item(tree.get_children()[i], values=(n, "失败"))
        threading.Thread(target=_w, daemon=True).start()

    def _nodes_switch(self, win, groups):
        import tkinter.messagebox as mb
        sel = self._nodes_tree.selection()
        if not sel:
            mb.showinfo("节点管理", "先在列表选中一个节点", parent=self.root)
            return
        node = self._nodes_tree.item(sel[0], "values")[0]
        g = self._group_var.get()
        try:
            clash_api("/proxies/" + urllib.parse.quote(g, safe=""), "PUT", {"name": node})
            mb.showinfo("节点管理", "已切换到: " + node, parent=self.root)
            self._nodes_refresh(win, groups)
            self._update_node_status()
        except Exception as e:
            mb.showerror("节点管理", "切换失败: " + str(e)[:60], parent=self.root)

    def open_settings(self):
        t = THEMES["dark" if self.dark else "light"]
        win = tk.Toplevel(self.root)
        win.title("设置 · 圆圆搜索")
        win.configure(bg=t["bg"])
        install_dir = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                       else os.path.dirname(os.path.abspath(__file__)))
        rows = [("版本", APP_VERSION), ("安装位置", install_dir), ("数据位置", DATA_DIR)]
        win.transient(self.root)
        for i, (k, v) in enumerate(rows):
            tk.Label(win, text=k, font=("Microsoft YaHei UI", 10, "bold"),
                     fg=t["sub"], bg=t["bg"]).grid(row=i, column=0, sticky="w", padx=(18, 8), pady=10)
            tk.Label(win, text=v, font=("Microsoft YaHei UI", 10),
                     fg=t["fg"], bg=t["bg"], anchor="w", justify="left").grid(
                row=i, column=1, sticky="w", pady=10)
            if i > 0:
                tk.Button(win, text="打开文件夹", font=("Microsoft YaHei UI", 9),
                          fg=t["accent"], bg=t["card"], activebackground=t["tab"],
                          activeforeground=t["fg"], bd=1, relief="solid", highlightthickness=0,
                          cursor="hand2",
                          command=lambda d=v: (os.startfile(d) if os.path.isdir(d) else None)
                          ).grid(row=i, column=2, padx=(8, 18))
        tk.Button(win, text="关 闭", font=("Microsoft YaHei UI", 10, "bold"),
                  fg="#ffffff", bg=t["accent"], activebackground=t["accent_h"],
                  activeforeground="#ffffff", bd=0, padx=18, pady=6, cursor="hand2",
                  command=win.destroy).grid(row=len(rows), column=0, columnspan=3, pady=(6, 10))
        btns = tk.Frame(win, bg=t["bg"])
        btns.grid(row=len(rows) + 1, column=0, columnspan=3, pady=(6, 14))
        btn_items = [("节点管理", lambda: (win.destroy(), self.open_nodes())),
                     ("清除历史", self.clear_history),
                     ("备份收藏", self.backup_fav),
                     ("恢复收藏", self.restore_fav),
                     ("导出链接清单", self.export_fav_txt),
                     ("导出当前结果", self.export_results),
                     ("便携模式", self.toggle_portable),
                     ("开机自启", self.toggle_autostart),
                     ("检查更新", self.check_update)]
        for i, (text, cmd) in enumerate(btn_items):
            tk.Button(btns, text=text, font=("Microsoft YaHei UI", 9),
                      fg=t["accent"], bg=t["card"], activebackground=t["tab"],
                      activeforeground=t["fg"], bd=1, relief="solid", highlightthickness=0,
                      cursor="hand2", command=cmd).grid(row=i // 3, column=i % 3, padx=6, pady=4, sticky="ew")
        win.update_idletasks()
        w = min(max(640, win.winfo_reqwidth()), win.winfo_screenwidth() - 60)
        h = min(win.winfo_reqheight(), win.winfo_screenheight() - 80)
        win.geometry("%dx%d" % (w, h))
        win.resizable(True, True)
        win.minsize(560, 320)
        win.columnconfigure(1, weight=1)
        win.columnconfigure(2, weight=1)

    def clear_history(self):
        import tkinter.messagebox as mb
        if not self.history:
            mb.showinfo("清除历史", "没有历史记录", parent=self.root)
            return
        if mb.askyesno("清除历史", "确定清空全部搜索历史？", parent=self.root):
            self.history = []
            save_json(HIST_FILE, self.history)
            self.entry.configure(values=[])
            self.status.config(text="搜索历史已清空")

    def backup_fav(self):
        import tkinter.messagebox as mb
        import tkinter.filedialog as fd
        p = fd.asksaveasfilename(parent=self.root, title="备份收藏",
                                 defaultextension=".json", initialfile="圆圆搜索-收藏.json")
        if p:
            save_json(p, self.favorites)
            self.status.config(text="收藏已备份: " + p)

    def restore_fav(self):
        import tkinter.messagebox as mb
        import tkinter.filedialog as fd
        p = fd.askopenfilename(parent=self.root, title="恢复收藏", filetypes=[("JSON", "*.json")])
        if not p:
            return
        try:
            data = load_json(p, None)
            if not isinstance(data, list):
                raise ValueError("格式不对")
            self.favorites = data
            save_json(FAV_FILE, self.favorites)
            self.refresh_fav()
            self.status.config(text="收藏已恢复（%d 条）" % len(data))
        except Exception as e:
            mb.showerror("恢复收藏", "文件无效: " + str(e)[:50], parent=self.root)

    def export_fav_txt(self):
        import tkinter.filedialog as fd
        p = fd.asksaveasfilename(parent=self.root, title="导出链接清单",
                                 defaultextension=".txt", initialfile="圆圆搜索-链接清单.txt")
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                for item in self.favorites:
                    f.write(item["title"] + "\n" + item["url"] + "\n\n")
            self.status.config(text="链接清单已导出: " + p)
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("导出", "导出失败: " + str(e)[:50], parent=self.root)

    def _migrate_data(self, src, dst):
        """迁移数据文件到新目录"""
        import shutil
        try:
            os.makedirs(dst, exist_ok=True)
            for name in ("history.json", "favorites.json", "clash"):
                s = os.path.join(src, name)
                if os.path.exists(s):
                    d = os.path.join(dst, name)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
                    else:
                        shutil.copy2(s, d)
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showwarning("便携模式", "数据迁移失败（将沿用原目录）: " + str(e)[:60], parent=self.root)

    def toggle_portable(self):
        import tkinter.messagebox as mb
        cfg = load_json(CONFIG_FILE, {}) or {}
        cur = bool(cfg.get("portable"))
        target = not cur
        frozen = getattr(sys, "frozen", False)
        if not frozen and target:
            mb.showinfo("便携模式", "便携模式仅在安装版（exe）中可用", parent=self.root)
            return
        if mb.askyesno("便携模式",
                       ("开启：数据改存软件目录 data 文件夹，U 盘携带数据跟着走\n\n" if target else
                        "关闭：数据回到 %APPDATA%\\圆圆搜索\\\n\n") +
                       "重启软件后生效，是否继续？", parent=self.root):
            exe_data = os.path.join(os.path.dirname(sys.executable), "data")
            if target:
                self._migrate_data(BASE, exe_data)
            else:
                self._migrate_data(exe_data, BASE)
            cfg["portable"] = target
            save_json(CONFIG_FILE, cfg)
            self.status.config(text="便携模式已" + ("开启" if target else "关闭") + "，重启生效")

    def check_update(self):
        """菜单入口：后台检查更新（不卡界面）"""
        import tkinter.messagebox as mb
        if not UPDATE_URL:
            mb.showinfo("检查更新",
                        "当前版本 %s\n\n未配置更新源（需要一个能放版本号文件的网址，\n"
                        "如 Gitee/GitHub 仓库）。\n如需在线更新功能，提供托管地址后即可启用。" % APP_VERSION,
                        parent=self.root)
            return
        if getattr(self, "_checking", False):
            return
        self._checking = True
        self.status.config(text="正在检查更新…")
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self):
        """后台线程：拉取 version.txt 并弹结果（成功/已最新/失败）"""
        import tkinter.messagebox as mb
        try:
            remote_ver, dl, note = self._fetch_update_info()
            if not remote_ver:
                self.root.after(0, lambda: (self.status.config(text="检查更新失败（网络异常）"), self._checking_done()))
                return
            if self._ver_tuple(remote_ver) <= self._ver_tuple(APP_VERSION):
                self.root.after(0, lambda: (mb.showinfo("检查更新", "当前已是最新版本 %s ✓" % APP_VERSION, parent=self.root), self._checking_done()))
            else:
                self.root.after(0, lambda: (self._prompt_update(remote_ver, dl, note), self._checking_done()))
        except Exception:
            self.root.after(0, lambda: (self.status.config(text="检查更新失败"), self._checking_done()))

    def _checking_done(self):
        self._checking = False
        if self.status.cget("text").startswith("正在检查更新"):
            self.status.config(text="")

    def _fetch_update_info(self):
        """请求 version.txt：返回 (版本号, 下载链接, 更新说明)；失败返回 (None, "", "")"""
        try:
            urls = [UPDATE_URL] + [m + UPDATE_URL for m in UPDATE_MIRRORS]
            raw = None
            for url in urls:
                req = urllib.request.Request(url, headers=HDRS)
                for use_proxy in (True, False):
                    try:
                        h = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}) if (use_proxy and PROXY) else urllib.request.ProxyHandler({})
                        opener = urllib.request.build_opener(h)
                        with opener.open(req, timeout=8) as r:
                            raw = r.read().decode("utf-8", "ignore")
                        break
                    except Exception:
                        continue
                if raw:
                    break
            if not raw:
                return None, "", ""
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            if not lines:
                return None, "", ""
            return lines[0], (lines[1] if len(lines) > 1 else ""), (lines[2] if len(lines) > 2 else "")
        except Exception:
            return None, "", ""

    @staticmethod
    def _mirror_url(dl):
        """GitHub raw 下载链接转加速镜像（国内无代理可下）"""
        if not dl or "raw.githubusercontent.com" not in dl:
            return dl
        return UPDATE_MIRRORS[0] + dl

    @staticmethod
    def _autostart_enabled():
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run")
            try:
                winreg.QueryValueEx(k, "圆圆搜索")
                return True
            finally:
                winreg.CloseKey(k)
        except Exception:
            return False

    def toggle_autostart(self):
        import tkinter.messagebox as mb
        import winreg
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            if self._autostart_enabled():
                winreg.DeleteValue(k, "圆圆搜索")
                self.status.config(text="已关闭开机自启")
            else:
                winreg.SetValueEx(k, "圆圆搜索", 0, winreg.REG_SZ, '"%s"' % sys.executable)
                self.status.config(text="已开启开机自启（登录时自动运行）")
            winreg.CloseKey(k)
        except Exception as e:
            mb.showerror("开机自启", "操作失败: " + str(e)[:60], parent=self.root)

    def export_results(self):
        """导出当前标签页的搜索结果到 txt"""
        import tkinter.filedialog as fd
        import tkinter.messagebox as mb
        label = self.current
        items = self.data.get(label, []) or []
        if not items:
            mb.showinfo("导出", "当前页面没有结果", parent=self.root)
            return
        p = fd.asksaveasfilename(parent=self.root, title="导出当前结果",
                                 defaultextension=".txt", initialfile="圆圆搜索-%s.txt" % label)
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                for line, url in items:
                    f.write(line + "\n" + url + "\n\n")
            self.status.config(text="结果已导出: " + p)
        except Exception as e:
            mb.showerror("导出", "导出失败: " + str(e)[:50], parent=self.root)

    def open_help(self):
        t = THEMES["dark" if self.dark else "light"]
        win = tk.Toplevel(self.root)
        win.title("帮助 · 圆圆搜索")
        win.configure(bg=t["bg"])
        win.transient(self.root)
        win.geometry("600x500")
        win.minsize(440, 320)
        win.resizable(True, True)
        txt = ("圆圆搜索 使用说明\n\n"
               "◆ 搜索：输入关键词回车或点「搜 索」，四个来源并行查找（GitHub / 网页 / Stack Overflow / npm）\n"
               "◆ 打开：双击结果行在浏览器打开；右键复制链接；Ctrl+C 复制选中\n"
               "◆ 收藏：选中结果点「☆ 收藏」，再点一次取消；收藏页同样操作；收藏自动保存\n"
               "◆ 深色模式：Ctrl+D 或点「深色」按钮\n"
               "◆ 内置代理：默认自动开启（含机场订阅），让 GitHub 链接在无代理网络也能打开\n"
               "   - 「○ 内置代理 关」按钮可手动开关\n"
               "   - 「代理」按钮可换订阅链接 / 填 HTTP 代理 / 清除\n"
               "   - 「节点管理」（设置里）可测速和切换节点\n"
               "◆ 快捷键：Ctrl+F 聚焦输入框 · Ctrl+S 搜索 · Ctrl+D 深浅色 · Delete 取消收藏\n"
               "◆ 数据位置：收藏/历史/订阅缓存存于 %APPDATA%\\圆圆搜索\\（设置里可打开）\n"
               "◆ 常见问题：内置代理启动失败 → 看 %APPDATA%\\圆圆搜索\\error.log，或重新安装\n")
        frame = tk.Frame(win, bg=t["bg"])
        frame.pack(fill="both", expand=True, padx=18, pady=14)
        txtw = tk.Text(frame, font=("Microsoft YaHei UI", 10), fg=t["fg"], bg=t["bg"],
                       wrap="word", relief="flat", borderwidth=0, highlightthickness=0,
                       padx=10, pady=8, spacing1=3, spacing3=3, selectbackground=t["tab"])
        sb = tk.Scrollbar(frame, command=txtw.yview)
        sb.pack(side="right", fill="y")
        txtw.pack(side="left", fill="both", expand=True)
        txtw.config(yscrollcommand=sb.set)
        txtw.insert("1.0", txt)
        txtw.config(state="disabled")

    def set_proxy(self):
        import tkinter.simpledialog as sd
        global PROXY
        cur = PROXY or ""
        v = sd.askstring("代理设置",
                         "已内置默认机场订阅，开机自动启用。\n\n1. 换订阅链接 → 直接粘贴新链接（https://...）\n2. 换 HTTP 代理 → 填 http://IP:端口\n3. 清除代理（直连） → 框留空确定\n\n当前：" + (cur or "内置默认订阅"),
                         initialvalue=cur, parent=self.root)
        if v is None:
            return
        v = v.strip()
        if not v:
            stop_builtin_clash()
            PROXY = ""
            cfg = load_json(CONFIG_FILE, {}) or {}
            cfg["proxy"] = ""
            cfg["sub_url"] = ""
            cfg["builtin_off"] = True
            save_json(CONFIG_FILE, cfg)
            self.builtin_off = True
            self.status.config(text="已恢复直连")
            self.update_builtin_btn()
            return
        cfg = load_json(CONFIG_FILE, {}) or {}
        # 订阅链接（http(s) 开头且含 sub 或不是 ip:port 形式）
        looks_sub = v.startswith(("http://", "https://")) and not re.match(r"https?://[\d.]+:\d+", v)
        if looks_sub:
            try:
                self.status.config(text="正在启动内置代理...")
                self.root.update_idletasks()
                start_builtin_clash(v)
                PROXY = "http://127.0.0.1:%d" % CLASH_PORT
                cfg["proxy"] = PROXY
                cfg["sub_url"] = v
                cfg["builtin_off"] = False
                save_json(CONFIG_FILE, cfg)
                self.builtin_off = False
                self.status.config(text="内置代理已启动 (127.0.0.1:%d) ✓" % CLASH_PORT)
                self.update_builtin_btn()
            except Exception as e:
                PROXY = ""
                self.status.config(text="内置代理启动失败: " + str(e)[:70])
            return
        # 手动 HTTP 代理
        if not (v.startswith("http://") or v.startswith("https://")):
            v = "http://" + v
        stop_builtin_clash()
        PROXY = v
        cfg["proxy"] = v
        cfg["sub_url"] = ""
        cfg["builtin_off"] = True
        save_json(CONFIG_FILE, cfg)
        self.builtin_off = True
        self.status.config(text="代理已设置: " + v)
        self.update_builtin_btn()

    def _setup_tray(self):
        """系统托盘（最小化后驻留，托盘菜单可恢复/退出）"""
        try:
            import pystray
            from PIL import Image
            base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
            ico = os.path.join(base, "favicon.ico")
            image = Image.open(ico) if os.path.exists(ico) else Image.new("RGBA", (32, 32), (255, 0, 0))

            def _show(icon, item):
                self.root.after(0, self._show_window)

            def _quit(icon, item):
                self.root.after(0, self._quit_app)

            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", _show, default=True),
                pystray.MenuItem("退出", _quit))
            self._tray = pystray.Icon("圆圆搜索", image, "圆圆搜索", menu)
            threading.Thread(target=self._tray.run, daemon=True).start()
            self._tray_ready = True
        except Exception:
            self._tray = None

    def _show_window(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()

    def _on_unmap(self, e):
        if self._tray_ready and self.root.state() == "iconic":
            self.root.after(100, self.root.withdraw)

    def _quit_app(self):
        self._tray_ready = False
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        self.on_close()

    def on_close(self):
        stop_builtin_clash()
        cfg = load_json(CONFIG_FILE, {}) or {}
        cfg["geometry"] = self.root.geometry()
        cfg["geom_v"] = APP_VERSION
        save_json(CONFIG_FILE, cfg)
        self.root.destroy()

    # ---------- 切换与搜索 ----------
    def switch(self, label):
        self.current = label
        self.frames[label].tkraise()
        for k, b in self.tab_btns.items():
            b.config(style="TabSel.TButton" if k == label else "Tab.TButton")
        self._render_page(label)
        self.update_fav_btn()

    def run(self):
        q = self.entry.get().strip()
        if not q:
            return
        if q in self.history:
            self.history.remove(q)
        self.history.insert(0, q)
        self.history = self.history[:20]
        save_json(HIST_FILE, self.history)
        self.entry.configure(values=self.history[:20])
        self.btn.config(state="normal", text="取 消", command=self._cancel_search)
        self.status.config(text=f"正在搜索: {q} …", style="Busy.TLabel")
        self._cancel = False
        for label in [l for l, _ in SOURCES]:
            self.tab_btns[label].config(text=ICONS.get(label, label))
        self._open_loading(q)
        for label in [l for l, _ in SOURCES]:
            self.trees[label].delete(*self.trees[label].get_children())
            self.data[label] = []
        threading.Thread(target=self._work,
                         args=(q, FETCH_LIMIT,
                               None if self.lang_var.get() == "全部语言" else self.lang_var.get()),
                         daemon=True).start()

    def _check_update(self):
        """启动自动检查：有新版本且未被跳过才弹窗"""
        try:
            remote_ver, dl, note = self._fetch_update_info()
            if not remote_ver:
                return
            if self._ver_tuple(remote_ver) <= self._ver_tuple(APP_VERSION):
                return
            cfg = load_json(CONFIG_FILE, {}) or {}
            if cfg.get("skip_update") == remote_ver:
                return
            self.root.after(0, lambda: self._prompt_update(remote_ver, dl, note))
        except Exception:
            pass

    def _ver_tuple(self, s):
        parts = re.findall(r"\d+", s or "")[:3]
        return tuple(int(p) for p in parts) or (0, 0, 0)

    def _prompt_update(self, ver, dl, note=""):
        """发现新版本弹窗（软件内，自适应可缩放 + 更新说明可滚动）"""
        try:
            t = THEMES["dark" if self.dark else "light"]
            win = tk.Toplevel(self.root)
            win.title("发现新版本")
            win.configure(bg=t["bg"])
            win.transient(self.root)
            win.resizable(True, True)
            win.minsize(400, 240)
            tk.Label(win, text="\u25c6 发现新版本 v%s" % ver, font=("Microsoft YaHei UI", 14, "bold"),
                     fg=t["accent"], bg=t["bg"]).pack(pady=(14, 2))
            tk.Label(win, text="当前版本 v%s" % APP_VERSION, font=("Microsoft YaHei UI", 10),
                     fg=t["sub"], bg=t["bg"]).pack()
            body = tk.Frame(win, bg=t["bg"])
            body.pack(fill="both", expand=True, padx=14, pady=(8, 0))
            body.rowconfigure(0, weight=1)
            body.columnconfigure(0, weight=1)
            if note:
                txtw = tk.Text(body, wrap="word", relief="flat", borderwidth=0,
                               highlightthickness=0, font=("Microsoft YaHei UI", 10),
                               fg=t["fg"], bg=t["tab"], padx=10, pady=8, spacing1=3, spacing3=3,
                               selectbackground=t["tab"], width=52, height=2, cursor="arrow")
                txtw.grid(row=0, column=0, sticky="nsew")
                sb = tk.Scrollbar(body, command=txtw.yview)
                sb.grid(row=0, column=1, sticky="ns")
                txtw.config(yscrollcommand=sb.set)
                txtw.insert("1.0", note)
                win.update_idletasks()
                # 先映射一次让 Text 按真实宽度换行，再按文字实际显示行数定高（打开即显示全部）
                w0 = min(max(420, win.winfo_reqwidth() + 30), win.winfo_screenwidth() - 60)
                h0 = min(max(280, win.winfo_reqheight() + 16), win.winfo_screenheight() - 80)
                win.geometry("%dx%d" % (w0, h0))
                win.update()
                try:
                    lines = int(txtw.count("1.0", "end-1c", "displaylines")[0])
                except Exception:
                    lines = max(3, len(note) // 40 + 1)
                txtw.config(height=min(max(lines + 1, 3), 18))  # 超 18 行才滚动
                txtw.config(state="disabled")
            row = tk.Frame(win, bg=t["bg"])
            row.pack(pady=(10, 12))
            tk.Button(row, text="立即更新", font=("Microsoft YaHei UI", 10, "bold"),
                      fg="white", bg=t["accent"], activebackground=t["accent"],
                      bd=0, padx=18, pady=4, cursor="hand2",
                      command=lambda: self._dl_update(win, dl)).pack(side="left", padx=8)
            tk.Button(row, text="稍后更新", font=("Microsoft YaHei UI", 10),
                      fg=t["fg"], bg=t["tab"], activebackground=t["tab"],
                      bd=0, padx=14, pady=4, cursor="hand2",
                      command=win.destroy).pack(side="left", padx=8)
            win.update_idletasks()
            w = min(max(420, win.winfo_reqwidth() + 30), win.winfo_screenwidth() - 60)
            h = min(win.winfo_reqheight() + 16, win.winfo_screenheight() - 80)
            x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
            y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
            win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except Exception:
            pass

    
    def _dl_update(self, win, dl):
        """软件内下载更新：进度条 + 自动静默安装，装完自动启动新版"""
        try:
            win.destroy()
        except Exception:
            pass
        if not dl:
            return
        import threading as _th, subprocess, tempfile, socket
        try:
            import tkinter.ttk as ttk
        except Exception:
            ttk = None
        t = THEMES["dark" if self.dark else "light"]
        d = tk.Toplevel(self.root)
        d.title("\u6b63\u5728\u4e0b\u8f7d\u66f4\u65b0")
        d.configure(bg=t["bg"])
        d.resizable(False, False)
        try:
            d.transient(self.root)
        except Exception:
            pass
        tk.Label(d, text="\u25c6 \u6b63\u5728\u4e0b\u8f7d\u66f4\u65b0...", font=("Microsoft YaHei UI", 13, "bold"),
                 fg=t["accent"], bg=t["bg"]).pack(pady=(16, 4))
        st_lb = tk.Label(d, text="\u6b63\u5728\u8fde\u63a5\u670d\u52a1\u5668...", font=("Microsoft YaHei UI", 10),
                         fg=t["fg"], bg=t["bg"])
        st_lb.pack(pady=(2, 8))
        bar = ttk.Progressbar(d, length=360, mode="determinate", maximum=100)
        bar.pack(padx=24)
        pct_lb = tk.Label(d, text="0%", font=("Microsoft YaHei UI", 10), fg=t["sub"], bg=t["bg"])
        pct_lb.pack(pady=(6, 2))
        btn_row = tk.Frame(d, bg=t["bg"])
        btn_row.pack(pady=(6, 14))
        cancel_btn = tk.Button(btn_row, text="\u53d6\u6d88", font=("Microsoft YaHei UI", 10),
                               fg=t["fg"], bg=t["tab"], activebackground=t["tab"],
                               bd=0, padx=20, pady=4, cursor="hand2")
        cancel_btn.pack(side="left", padx=8)
        d.update_idletasks()
        w, h = d.winfo_reqwidth() + 30, d.winfo_reqheight() + 10
        x = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        d.geometry("%dx%d+%d+%d" % (w, h, max(x, 0), max(y, 0)))

        dest = os.path.join(tempfile.gettempdir(), "yy-update-%s.exe" % ver_slug(dl))
        urls = [m + dl for m in UPDATE_MIRRORS] + [dl]  # 镜像优先，raw 原地址兜底（内置代理可用）
        flag = {"run": True, "pct": 0, "mb": 0.0, "total": 0.0, "err": "", "done": False, "cancelled": False}

        def worker():
            for url in urls:
                if not flag["run"]:
                    return
                try:
                    handlers = []
                    if PROXY:
                        ph = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
                        handlers.append(ph)
                    op = urllib.request.build_opener(*handlers)
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with op.open(req, timeout=60) as resp, open(dest, "wb") as f:
                        total = int(resp.headers.get("Content-Length") or 0)
                        flag["total"] = total / 1048576.0
                        got = 0
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            if not flag["run"]:
                                flag["cancelled"] = True
                                try:
                                    os.remove(dest)
                                except Exception:
                                    pass
                                return
                            got += len(chunk)
                            f.write(chunk)
                            if total:
                                flag["pct"] = min(99, got * 100 // total)
                                flag["mb"] = got / 1048576.0
                    if os.path.getsize(dest) < 1024 * 1024:  # 太小=镜像错误页
                        raise IOError("bad size")
                    flag["pct"] = 100
                    flag["done"] = True
                    return
                except Exception as e:
                    flag["err"] = str(e)[:80]
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
            flag["err"] = flag["err"] or "\u4e0b\u8f7d\u5931\u8d25"

        def tick():
            if flag["done"]:
                bar["value"] = 100
                pct_lb.config(text="100%")
                self._install_update(d, dest)
                return
            if flag["cancelled"] or not flag["run"]:
                d.destroy()
                return
            if flag["err"]:
                st_lb.config(text="\u4e0b\u8f7d\u5931\u8d25\uff1a" + flag["err"] + "\uff08\u53ef\u91cd\u8bd5\uff09", fg="#dc2626")
                bar["value"] = 0
                pct_lb.config(text="0%")
                cancel_btn.config(text="\u91cd\u8bd5", command=lambda: (flag.update(run=True, err="", pct=0),
                                                                          st_lb.config(text="\u6b63\u5728\u8fde\u63a5\u670d\u52a1\u5668...", fg=t["fg"]),
                                                                          _th.Thread(target=worker, daemon=True).start()))
                return
            bar["value"] = flag["pct"]
            if flag["total"]:
                pct_lb.config(text="%d%%  (%.1f/%.1f MB)" % (flag["pct"], flag["mb"], flag["total"]))
            else:
                pct_lb.config(text="%d%%  (%.1f MB)" % (flag["pct"], flag["mb"]))
            self.root.after(200, tick)

        def on_cancel():
            flag["run"] = False
            cancel_btn.config(state="disabled", text="\u6b63\u5728\u53d6\u6d88...")
        cancel_btn.config(command=on_cancel)
        _th.Thread(target=worker, daemon=True).start()
        self.root.after(200, tick)

    def _install_update(self, d, dest):
        """静默安装下载好的安装包，装完自动启动新版，随后退出自身"""
        import subprocess
        try:
            d.destroy()
        except Exception:
            pass
        try:
            self._tray_ready = False
            if self._tray is not None:
                try:
                    self._tray.stop()
                except Exception:
                    pass
        except Exception:
            pass
        try:  # 先杀掉内置代理，避免安装时文件被占用
            subprocess.Popen(["taskkill", "/IM", "mihomo.exe", "/F"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=0x08000000)
        except Exception:
            pass
        try:
            subprocess.Popen([dest, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                             cwd=os.path.dirname(dest),
                             creationflags=0x08000000 | 0x00000008)
        except Exception:
            pass
        self.root.after(800, self._quit_app)

    def _open_loading(self, q):
        """搜索中提示：只在软件窗口内显示（各标签页中央），不弹独立窗口"""
        for lbl in self.loading_lbls.values():
            try:
                lbl.place(relx=0.5, rely=0.5, anchor="center")
                lbl.lift()
            except Exception:
                pass

    def _loading_anim(self):
        pass

    def _close_loading(self):
        for lbl in self.loading_lbls.values():
            try:
                lbl.place_forget()
            except Exception:
                pass

    def _cancel_search(self):
        self._cancel = True
        self._close_loading()
        self.btn.config(state="normal", text="搜 索", command=self.run)
        self.status.config(text="搜索已取消", style="Status.TLabel")

    def _work(self, q, limit=10, lang=None):
        t0 = time.time()
        try:
            results = search_all(q, limit, lang)
        except Exception as e:
            results = {"__err__": str(e)}
        self.root.after(0, lambda: self._show(q, results, time.time() - t0))

    def _show(self, q, results, elapsed=0):
        self._close_loading()
        self.btn.config(state="normal", text="搜 索", command=self.run)
        if getattr(self, "_cancel", False):
            self.status.config(text="搜索已取消", style="Status.TLabel")
            return
        if "__err__" in results:
            self.status.config(text="搜索失败: " + str(results["__err__"])[:70], style="Status.TLabel")
            return
        total = 0
        for label, _ in SOURCES:
            items = results.get(label, []) or []
            self.data[label] = list(items)
            self.total[label] = len(items)
            self.page[label] = 0
            total += len(items)
            self.tab_btns[label].config(text="%s(%d)" % (ICONS.get(label, label), len(items)))
        self._render_page(self.current)
        self.status.config(text="共 %d 条 · 用时 %.1fs · %s · 双击打开 · 右键菜单 · ★ 收藏"
                           % (total, elapsed, q), style="Status.TLabel")
        self._update_page_state(self.current)

    # ---------- 分页 ----------
    def _data_index(self, label, tree_idx):
        """tree 行号 → data 全量索引（含页偏移）"""
        return self.page.get(label, 0) * self.page_size + tree_idx

    def _update_page_state(self, label):
        n = self.total.get(label, 0)
        pages = max(1, (n + self.page_size - 1) // self.page_size)
        p = self.page.get(label, 0)
        pprev, plbl, pnext = self.page_bars[label]
        plbl.config(text="第 %d/%d 页 · 共 %d 条" % (p + 1, pages, n))
        pprev.config(state="disabled" if p <= 0 else "normal")
        pnext.config(state="disabled" if p >= pages - 1 else "normal")

    def _render_page(self, label):
        tree = self.trees[label]
        tree.delete(*tree.get_children())
        items = self.data.get(label, []) or []
        n = len(items)
        pages = max(1, (n + self.page_size - 1) // self.page_size)
        p = min(self.page.get(label, 0), pages - 1)
        self.page[label] = p
        for line, url in items[p * self.page_size:(p + 1) * self.page_size]:
            tree.insert("", "end", values=(line, url if url else "—"))
        self._update_page_state(label)

    def page_prev(self, label):
        p = self.page.get(label, 0)
        if p > 0:
            self.page[label] = p - 1
            self._render_page(label)

    def page_next(self, label):
        items = self.data.get(label, []) or []
        p = self.page.get(label, 0)
        if p < (len(items) - 1) // self.page_size:
            self.page[label] = p + 1
            self._render_page(label)

    # ---------- 窗口尺寸 -> 每页条数自动调节 ----------
    def _calc_page_size(self):
        h = self.root.winfo_height()
        return max(6, min(50, (h - 220) // 22))  # 扣除搜索区/工具栏/翻页条/状态栏约 220px，行高约 22px

    def _on_resize(self, e):
        if e.widget is not self.root:
            return
        if self._geom == (e.width, e.height):
            return
        self._geom = (e.width, e.height)
        ps = self._calc_page_size()
        if ps != self.page_size:
            self.page_size = ps
            if self._resize_job:
                self.root.after_cancel(self._resize_job)
            self._resize_job = self.root.after(250, self._repaint_all_pages)

    def _repaint_all_pages(self):
        for label in list(self.trees):
            self._render_page(label)

    # ---------- 收藏 ----------
    def fav_current(self):
        label = self.current
        sel = self.trees[label].selection()
        if not sel:
            self.status.config(text="先在列表中选中一条再收藏")
            return
        idx = self.trees[label].index(sel[0])
        line, url = self.data[label][idx]
        if not url:
            return
        if label == FAV_LABEL:
            # 收藏页：点收藏按钮 = 取消收藏
            for i, f in enumerate(self.favorites):
                if f["url"] == url:
                    del self.favorites[i]
                    save_json(FAV_FILE, self.favorites)
                    self.refresh_fav()
                    self.status.config(text="已取消收藏")
                    self.update_fav_btn()
                    return
            return
        # 已收藏 → 取消；未收藏 → 收藏（再次点击切换）
        for i, f in enumerate(self.favorites):
            if f["url"] == url:
                del self.favorites[i]
                save_json(FAV_FILE, self.favorites)
                self.refresh_fav()
                self.status.config(text="已取消收藏")
                self.update_fav_btn()
                return
        self.favorites.append({"title": line, "url": url, "src": label})
        save_json(FAV_FILE, self.favorites)
        self.refresh_fav()
        self.status.config(text="已收藏 ★")
        self.update_fav_btn()

    def update_fav_btn(self):
        label = self.current
        faved = False
        sel = self.trees[label].selection()
        if sel:
            idx = self.trees[label].index(sel[0])
            url = self.data[label][idx][1]
            faved = True if label == FAV_LABEL else any(f["url"] == url for f in self.favorites)
        self.fav_btn.config(text="★ 已收藏" if faved else "☆ 收藏",
                            style="FavOn.TButton" if faved else "Ghost.TButton")

    def fav_remove_current(self):
        """取消收藏：任意页面选中已收藏项即可移除"""
        label = self.current
        sel = self.trees[label].selection()
        if not sel:
            self.status.config(text="先在列表中选中一条")
            return
        idx = self._data_index(label, self.trees[label].index(sel[0]))
        line, url = self.data[label][idx]
        if not url:
            return
        for i, f in enumerate(self.favorites):
            if f["url"] == url:
                del self.favorites[i]
                save_json(FAV_FILE, self.favorites)
                self.refresh_fav()
                self.status.config(text="已取消收藏")
                self.update_fav_btn()
                return
        self.status.config(text="该项尚未收藏")

    def refresh_fav(self):
        self.data[FAV_LABEL] = [(f["title"], f["url"]) for f in self.favorites]
        self.total[FAV_LABEL] = len(self.data[FAV_LABEL])
        if self.current == FAV_LABEL:
            self.page[FAV_LABEL] = 0
            self._render_page(FAV_LABEL)
        self.tab_btns[FAV_LABEL].config(text="%s(%d)" % (ICONS[FAV_LABEL], len(self.favorites)))
        self.update_fav_btn()

    # ---------- 交互 ----------
    def open_url(self, url):
        """打开链接：Chrome 优先 → Edge → 默认浏览器；内置代理开启时附加代理参数"""
        proxy_arg = ["--proxy-server=http://127.0.0.1:%d" % CLASH_PORT] if PROXY else []
        for exe in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe] + proxy_arg + [url])
                    return
                except Exception:
                    pass
        webbrowser.open(url)

    def open_selected(self, label):
        sel = self.trees[label].selection()
        if sel:
            idx = self._data_index(label, self.trees[label].index(sel[0]))
            url = self.data[label][idx][1]
            if url:
                self.open_url(url)

    def show_menu(self, label, e):
        sel = self.trees[label].selection()
        if not sel:
            return
        self._menu_label = label
        self._menu_idx = self._data_index(label, self.trees[label].index(sel[0]))
        if not hasattr(self, "_menu"):
            self._menu = tk.Menu(self.root, tearoff=0)
            self._menu.add_command(label="浏览器打开", command=lambda: self._menu_act("open"))
            self._menu.add_command(label="复制链接", command=lambda: self._menu_act("copy_url"))
            self._menu.add_command(label="复制标题", command=lambda: self._menu_act("copy_title"))
            self._menu.add_command(label="复制 标题+链接", command=lambda: self._menu_act("copy_both"))
            self._menu.add_command(label="复制所选链接", command=lambda: self._menu_act("copy_sel"))
            self._menu.add_command(label="复制本页全部链接", command=lambda: self._menu_act("copy_all"))
            self._menu.add_command(label="收藏 / 取消收藏", command=lambda: self._menu_act("fav"))
        try:
            self._menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu.grab_release()

    def _menu_act(self, act):
        label = self._menu_label
        line, url = self.data[label][self._menu_idx]
        if act == "open" and url:
            self.open_url(url)
        elif act == "copy_url" and url:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.status.config(text="链接已复制: " + url[:60])
        elif act == "copy_title":
            self.root.clipboard_clear()
            self.root.clipboard_append(line)
            self.status.config(text="标题已复制")
        elif act == "copy_both":
            self.root.clipboard_clear()
            self.root.clipboard_append((line + "\n" + url) if url else line)
            self.status.config(text="标题+链接已复制")
        elif act in ("copy_sel", "copy_all"):
            label = self._menu_label
            tree = self.trees[label]
            items = list(tree.selection()) if act == "copy_sel" else list(tree.get_children())
            urls = [self.data[label][self._data_index(label, tree.index(i))][1] for i in items]
            urls = [u for u in urls if u]
            if urls:
                self.root.clipboard_clear()
                self.root.clipboard_append("\n".join(urls))
                self.status.config(text="已复制 %d 条链接" % len(urls))
        elif act == "fav":
            self.fav_current()

    def copy_selected(self, label):
        if label is None:
            return
        sel = self.trees[label].selection()
        if sel:
            idx = self.trees[label].index(sel[0])
            url = self.data[label][idx][1]
            if url:
                self.root.clipboard_clear()
                self.root.clipboard_append(url)
                self.status.config(text="链接已复制: " + url[:60])

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        for label, items in search_all(sys.argv[2], 10).items():
            print("==" + label + "==")
            for line, url in items:
                print(" ", line, "\n    ", url)
    else:
        try:  # 高分屏 DPI 感知
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:  # 单实例：已有实例则提示退出
            import ctypes as _ct
            _ct.windll.kernel32.CreateMutexW(None, False, "圆圆搜索_SingleInstance_Mutex")
            if _ct.windll.kernel32.GetLastError() == 183:
                import tkinter.messagebox as _mb
                _r = tk.Tk()
                _r.withdraw()
                _mb.showinfo("圆圆搜索", "程序已在运行")
                sys.exit(0)
        except Exception:
            pass
        root = tk.Tk()
        try:
            _ico = os.path.join(sys._MEIPASS if getattr(sys, "frozen", False)
                                else os.path.dirname(os.path.abspath(__file__)), "favicon.ico")
            if os.path.exists(_ico):
                root.iconbitmap(_ico)
        except Exception:
            pass
        App(root)
        root.mainloop()
