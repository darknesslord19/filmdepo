# -*- coding: utf-8 -*-
"""
CloudStream Araci TAM - Pydroid 3 (ek paket gerekmez)

Anasayfa linkini yaz (ya da herhangi bir film linki). Arac su parcalari kendisi bulur:
  - ana sayfa kartlari (secici, baslik, afis, link), sayfalama, kategoriler
  - arama adresi ve arama sonucu kartlari
  - film detayi (baslik, afis, ozet, yil, turler, oyuncular, sure)
  - video zinciri (iframe -> embed -> bePlayer -> sifre cozme -> master HLS)
Sonunda eksiksiz bir <Site>.kt eklenti dosyasi ve rapor_*.json yazar.
"""
import base64
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, OrderedDict
from html.parser import HTMLParser

sys.setrecursionlimit(6000)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MAX_BYTES = 3 * 1024 * 1024

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.addheaders = []


# ============================================================ ag
def fetch(url, ref="", origin="", extra=None):
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "identity"}
    if ref:
        headers["Referer"] = ref
    if origin:
        headers["Origin"] = origin
    if extra:
        headers.update(extra)
    req = urllib.request.Request(url, headers=headers)
    status, ctype, body = 0, "", b""
    try:
        with opener.open(req, timeout=25) as r:
            status = r.status
            ctype = r.headers.get("Content-Type", "")
            body = r.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        status = e.code
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
        try:
            body = e.read(MAX_BYTES)
        except Exception:
            body = b""
    except Exception as e:
        return {"status": 0, "ct": "", "bytes": 0, "body": "", "cookies": [], "error": "%s: %s" % (type(e).__name__, e)}
    cs = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    if m:
        cs = m.group(1)
    try:
        text = body.decode(cs, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    return {"status": status, "ct": ctype, "bytes": len(body), "body": text,
            "cookies": sorted({c.name for c in jar})}


def host(u):
    return urllib.parse.urlparse(u).netloc


def absu(u, base):
    try:
        return urllib.parse.urljoin(base, u)
    except Exception:
        return None


def say(tag, msg):
    print("[%s] %s" % (tag, msg))
    sys.stdout.flush()


def short(u, n=110):
    return u if len(u) <= n else u[:n] + "..."


# ============================================================ mini DOM
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Node(object):
    __slots__ = ("tag", "attrs", "children", "parent", "data")

    def __init__(self, tag, attrs=None, parent=None, data=""):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent
        self.data = data

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()


class Builder(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, dict((k, v or "") for k, v in attrs), self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        n = Node(tag, dict((k, v or "") for k, v in attrs), self.cur)
        self.cur.children.append(n)

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, d):
        if d:
            self.cur.children.append(Node("#text", None, self.cur, d))


def parse_html(html):
    b = Builder()
    try:
        b.feed(html)
        b.close()
    except Exception:
        pass
    return b.root


def iter_nodes(root):
    stack = [root]
    while stack:
        n = stack.pop()
        if n.tag != "#text":
            yield n
        stack.extend(reversed(n.children))


def text_of(n):
    out = []
    stack = [n]
    while stack:
        x = stack.pop()
        if x.tag == "#text":
            out.append(x.data)
        elif x.tag not in ("script", "style", "noscript"):
            stack.extend(reversed(x.children))
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def ancestors(n):
    p = n.parent
    while p is not None:
        yield p
        p = p.parent


def outer(n, limit=1800):
    parts = []

    def rec(x, depth):
        if sum(len(p) for p in parts) > limit or depth > 12:
            return
        if x.tag == "#text":
            t = x.data.strip()
            if t:
                parts.append(t[:120])
            return
        at = "".join(' %s="%s"' % (k, v[:140]) for k, v in x.attrs.items())
        parts.append("<%s%s>" % (x.tag, at))
        for c in x.children:
            rec(c, depth + 1)
        if x.tag not in VOID:
            parts.append("</%s>" % x.tag)

    rec(n, 0)
    return "".join(parts)[:limit]


# ---- secici motoru (tag.class[attr*=x], bosluk ve > baglaci)
def _compound(t):
    m = re.match(r"^([A-Za-z0-9*]*)((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$", t)
    if not m:
        return None
    attrs = []
    for a in re.findall(r"\[[^\]]+\]", m.group(3)):
        mm = re.match(r"\[([\w:-]+)(?:([*^$]?=)[\"']?(.*?)[\"']?)?\]$", a)
        if mm:
            attrs.append(mm.groups())
    return (m.group(1), [c for c in m.group(2).split(".") if c], attrs)


def parse_sel(sel):
    steps, comb = [], " "
    for t in re.findall(r">|[^\s>]+", sel):
        if t == ">":
            comb = ">"
            continue
        c = _compound(t)
        if c is None:
            return None
        steps.append((comb, c))
        comb = " "
    return steps


def _match_c(n, c):
    tag, classes, attrs = c
    if tag and tag != "*" and n.tag != tag:
        return False
    if classes and not set(classes) <= set(n.classes):
        return False
    for name, op, val in attrs:
        v = n.attrs.get(name)
        if v is None:
            return False
        if op == "*=" and val not in v:
            return False
        if op == "^=" and not v.startswith(val):
            return False
        if op == "$=" and not v.endswith(val):
            return False
        if op == "=" and v != val:
            return False
    return True


def _m(n, steps, i):
    comb, c = steps[i]
    if not _match_c(n, c):
        return False
    if i == 0:
        return True
    if comb == ">":
        return n.parent is not None and _m(n.parent, steps, i - 1)
    p = n.parent
    while p is not None:
        if _m(p, steps, i - 1):
            return True
        p = p.parent
    return False


def select(root, sel):
    steps = parse_sel(sel)
    if not steps:
        return []
    return [n for n in iter_nodes(root) if n.tag != "#root" and _m(n, steps, len(steps) - 1)]


def select_first(root, sel):
    r = select(root, sel)
    return r[0] if r else None


NOISE = {"first", "last", "odd", "even", "active", "current", "clearfix", "col", "row", "lazyloaded", "lazyload",
         "lazy", "loaded", "entered", "hentry", "type-post", "status-publish", "format-standard", "category-uncategorized"}


def good_class(c):
    return not (re.search(r"\d", c) or c in NOISE or c.startswith(("post-", "menu-item", "wp-image", "size-", "attachment-", "align")))


def sel_for(n, classes=None):
    cl = classes if classes is not None else [c for c in n.classes if good_class(c)][:3]
    return n.tag + "".join("." + c for c in cl)


# ============================================================ kart tespiti
BAD_PATH = re.compile(r"^/(category|kategori|tag|etiket|page|author|wp-|feed|tur|turler|genre|yil|oyuncu|oyuncular|"
                      r"yonetmen|search|arama|ayarlar|login|register|iletisim|hakkimizda|comments)(/|$)", re.I)


def norm_href(h, base):
    if not h or h.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    u = absu(h, base)
    if not u:
        return None
    u = u.split("#")[0]
    p = urllib.parse.urlparse(u)
    if p.netloc.replace("www.", "") != host(base).replace("www.", ""):
        return None
    if p.path in ("", "/") or BAD_PATH.match(p.path):
        return None
    if re.search(r"\.(js|css|png|jpe?g|gif|webp|svg|ico|xml|json|php)$", p.path, re.I):
        return None
    return u


def film_links(node, base):
    s = set()
    for n in iter_nodes(node):
        if n.tag == "a":
            u = norm_href(n.attrs.get("href", ""), base)
            if u:
                s.add(u)
    return s


def has_img(n):
    for x in iter_nodes(n):
        if x.tag == "img":
            return True
    return False


def detect_cards(root, base, min_units=2):
    units, seen = [], set()
    for a in [n for n in iter_nodes(root) if n.tag == "a"]:
        if not norm_href(a.attrs.get("href", ""), base):
            continue
        if any(x.tag in ("nav", "footer", "header") for x in ancestors(a)):
            continue
        u = a
        while u.parent is not None and u.parent.tag not in ("body", "html", "#root"):
            if len(film_links(u.parent, base)) > 1:
                break
            u = u.parent
        if not has_img(u) or id(u) in seen:
            continue
        seen.add(id(u))
        units.append(u)
    if len(units) < min_units:
        return None
    groups = OrderedDict()
    for u in units:
        sig = (u.tag, tuple(sorted(c for c in u.classes if good_class(c))))
        groups.setdefault(sig, []).append(u)
    sig, g = max(groups.items(), key=lambda kv: len(kv[1]))
    if len(g) < min_units:
        return None
    common = set(g[0].classes)
    for u in g[1:]:
        common &= set(u.classes)
    common = [c for c in g[0].classes if c in common and good_class(c)][:3]
    sel = sel_for(g[0], common)
    cnt = len(select(root, sel))
    if cnt > len(g) * 1.5:
        par = g[0].parent
        for _ in range(3):
            if par is None or par.tag in ("body", "html", "#root"):
                break
            psel = sel_for(par)
            cand = psel + " " + sel
            if len(select(root, cand)) <= len(g) * 1.5 and len(select(root, cand)) >= len(g):
                sel = cand
                break
            par = par.parent
    return {"units": g, "selector": sel, "count": len(select(root, sel)), "hrefs": film_links_list(g, base)}


def film_links_list(units, base):
    out = []
    for u in units:
        for n in iter_nodes(u):
            if n.tag == "a":
                h = norm_href(n.attrs.get("href", ""), base)
                if h:
                    out.append(h)
                    break
    return out


def film_prefix(hrefs):
    segs = Counter()
    for h in hrefs:
        parts = [p for p in urllib.parse.urlparse(h).path.split("/") if p]
        if len(parts) >= 2:
            segs[parts[0]] += 1
    if segs:
        seg, n = segs.most_common(1)[0]
        if n >= max(1, int(len(hrefs) * 0.8)):
            return "/" + seg + "/"
    return ""


IMG_EXT = re.compile(r"\.(jpe?g|png|webp|gif|avif)(\?|$)|wp-content/uploads", re.I)


def card_spec(det, base, label):
    units = det["units"]
    prefix = film_prefix(det["hrefs"])
    link_sel = ('a[href*=%s]' % prefix) if prefix else "a[href]"
    spec = {"label": label, "selector": det["selector"], "units": len(units), "matches": det["count"],
            "filmPrefix": prefix, "linkSel": link_sel}

    def first_link(u):
        r = select(u, link_sel)
        return r[0] if r else None

    def img_of(u):
        r = select(u, "img")
        return r[0] if r else None

    def uniq_ok(vals):
        vals = [v for v in vals if v]
        if len(vals) < max(1, int(len(units) * 0.9)):
            return False
        return len(units) <= 2 or len(set(vals)) >= len(vals) * 0.8

    cands = [
        ('a.attr("title")', lambda u: (first_link(u).attrs.get("title", "") if first_link(u) else "")),
        ('selectFirst("img")?.attr("alt")', lambda u: (img_of(u).attrs.get("alt", "") if img_of(u) else "")),
    ]
    for h in ("h1", "h2", "h3", "h4", "h5", "h6"):
        cands.append(('selectFirst("%s")?.text()' % h,
                      (lambda hh: lambda u: (text_of(select(u, hh)[0]) if select(u, hh) else ""))(h)))
    tokens = Counter()
    for u in units:
        seen = set()
        for n in iter_nodes(u):
            for c in n.classes:
                if re.search(r"title|name|baslik|isim", c, re.I) and c not in seen:
                    seen.add(c)
                    tokens[c] += 1
    for c, k in tokens.most_common(2):
        if k >= len(units) * 0.9:
            cands.append(('selectFirst(".%s")?.text()' % c,
                          (lambda cc: lambda u: (text_of(select(u, "." + cc)[0]) if select(u, "." + cc) else ""))(c)))
    cands.append(('a.text()', lambda u: (text_of(first_link(u)) if first_link(u) else "")))
    spec["titleExpr"], spec["titleSample"] = None, ""
    for expr, getter in cands:
        try:
            vals = [getter(u).strip() for u in units]
        except Exception:
            continue
        if uniq_ok(vals) and not all(re.fullmatch(r"(?i)izle|film izle|devami", v) for v in vals if v):
            spec["titleExpr"], spec["titleSample"] = expr, vals[0]
            break
    spec["posterAttr"], spec["posterSample"] = None, ""
    for attr in ("data-src", "data-lazy-src", "data-litespeed-src", "data-original", "data-lazy", "src"):
        vals = [(img_of(u).attrs.get(attr, "") if img_of(u) else "") for u in units]
        good = [v for v in vals if v and not v.startswith("data:") and IMG_EXT.search(v)]
        if len(good) >= len(units) * 0.8:
            spec["posterAttr"], spec["posterSample"] = attr, absu(good[0], base)
            break
    fl = first_link(units[0])
    spec["linkSample"] = absu(fl.attrs.get("href", ""), base) if fl else ""
    spec["sampleHtml"] = outer(units[0], 1500)
    spec["ok"] = bool(spec["titleExpr"] and spec["posterAttr"] and spec["linkSample"])
    return spec


# ============================================================ site yapisi
def find_categories(root, base, prefix):
    links = OrderedDict()
    for n in iter_nodes(root):
        if n.tag != "a":
            continue
        inmenu = any(x.tag == "nav" or re.search(r"menu|nav", " ".join(x.classes) + " " + x.attrs.get("id", ""), re.I)
                     for x in ancestors(n))
        if not inmenu:
            continue
        u = absu(n.attrs.get("href", ""), base)
        if not u or host(u).replace("www.", "") != host(base).replace("www.", ""):
            continue
        p = urllib.parse.urlparse(u).path
        parts = [x for x in p.split("/") if x]
        t = text_of(n)
        if len(parts) >= 2 and t and not re.match(r"^/(wp-|page|tag|author|feed)", p) and ("/" + parts[0] + "/") != prefix:
            links.setdefault(u.split("#")[0], (parts[0], t))
    if not links:
        return []
    cnt = Counter(v[0] for v in links.values())
    seg = cnt.most_common(1)[0][0]
    out = [(u, v[1]) for u, v in links.items() if v[0] == seg]
    seen, res = set(), []
    for u, t in out:
        if u not in seen:
            seen.add(u)
            res.append((u, t))
    return res[:16]


def find_page_pattern(html, base):
    if re.search(r"/page/\d+/?", html):
        return "path"
    if re.search(r"[?&]paged=\d+", html):
        return "paged"
    if re.search(r"[?&]page=\d+", html):
        return "page"
    if re.search(r"/sayfa/\d+/?", html):
        return "sayfa"
    return None


def page_url(base_url, page, style):
    if page <= 1:
        return base_url
    if style == "path":
        return base_url.rstrip("/") + "/page/%d/" % page
    if style == "sayfa":
        return base_url.rstrip("/") + "/sayfa/%d/" % page
    key = "paged" if style == "paged" else "page"
    return base_url + ("&" if "?" in base_url else "?") + "%s=%d" % (key, page)


SEARCH_NAMES = ("s", "q", "query", "search", "keyword", "ara", "arama", "kelime")


def find_search(root, base):
    for f in [n for n in iter_nodes(root) if n.tag == "form"]:
        for i in iter_nodes(f):
            if i.tag == "input" and i.attrs.get("name", "") in SEARCH_NAMES and i.attrs.get("type", "text") in ("text", "search", ""):
                action = absu(f.attrs.get("action", "") or base, base)
                if (f.attrs.get("method", "get") or "get").lower() == "get":
                    return {"kind": "query", "action": action, "name": i.attrs["name"]}
    return None


def search_templates(origin, found):
    out = []
    if found:
        out.append(found)
    for nm in ("s", "q", "search"):
        out.append({"kind": "query", "action": origin + "/", "name": nm})
    out.append({"kind": "path", "action": origin + "/arama/"})
    out.append({"kind": "path", "action": origin + "/search/"})
    seen, res = set(), []
    for t in out:
        key = (t["kind"], t["action"], t.get("name"))
        if key not in seen:
            seen.add(key)
            res.append(t)
    return res


def search_url(t, q):
    qq = urllib.parse.quote_plus(q)
    if t["kind"] == "query":
        a = t["action"]
        return a + ("&" if "?" in a else "?") + "%s=%s" % (t["name"], qq)
    return t["action"].rstrip("/") + "/" + qq + "/"


def kt_search_expr(t, origin):
    a = t["action"]
    rel = a[len(origin):] if a.startswith(origin) else None
    base = ("$mainUrl" + rel) if rel is not None else a
    if t["kind"] == "query":
        return '"%s%s%s=$q"' % (base, "&" if "?" in base else "?", t["name"])
    return '"%s/$q/"' % base.rstrip("/")


# ============================================================ detay sayfasi
def detail_spec(root, html, url, base):
    d = {"url": url}
    h1 = select_first(root, "h1")
    d["h1"] = text_of(h1) if h1 else ""

    def meta(prop):
        for n in iter_nodes(root):
            if n.tag == "meta" and (n.attrs.get("property") == prop or n.attrs.get("name") == prop):
                return n.attrs.get("content", "")
        return ""

    d["ogTitle"], d["ogImage"], d["ogDesc"] = meta("og:title"), meta("og:image"), meta("og:description") or meta("description")
    title = d["h1"] or d["ogTitle"]
    d["title"] = title
    # ozet
    d["plotSel"], d["plot"] = None, ""
    best = None
    for n in iter_nodes(root):
        if n.tag not in ("div", "p", "section", "article"):
            continue
        cls = " ".join(n.classes)
        if re.search(r"ozet|aciklama|description|plot|konu|summary|synopsis", cls, re.I) and not any(
                x.tag in ("nav", "header", "footer") for x in ancestors(n)):
            t = text_of(n)
            if 60 <= len(t) <= 3000:
                best = (n, t)
                break
    if best:
        cl = [c for c in best[0].classes if good_class(c)][:2]
        if cl:
            d["plotSel"] = best[0].tag + "".join("." + c for c in cl)
            d["plot"] = best[1]
    # yil
    m = re.search(r"\b(19|20)\d{2}\b", title or "")
    d["year"] = int(m.group(0)) if m else None
    d["yearSource"] = "baslik" if m else ""

    def outside_nav(n):
        return not any(x.tag in ("nav", "header", "footer", "aside") or re.search(r"menu|sidebar|widget", " ".join(x.classes), re.I)
                       for x in ancestors(n))

    def link_group(pattern):
        links = [n for n in iter_nodes(root) if n.tag == "a" and re.search(pattern, n.attrs.get("href", ""), re.I) and outside_nav(n)
                 and text_of(n)]
        if not links:
            return None, []
        par = links[0].parent
        csel = None
        for _ in range(3):
            if par is None or par.tag in ("body", "html", "#root"):
                break
            if [c for c in par.classes if good_class(c)]:
                csel = sel_for(par)
                break
            par = par.parent
        frag = re.search(pattern, links[0].attrs.get("href", ""), re.I)
        attr = "a[href*=%s]" % (frag.group(0) if frag else "/")
        sel = (csel + " " + attr) if csel else attr
        vals = [text_of(x) for x in select(root, sel)]
        return sel, [v for v in vals if v]

    d["tagsSel"], d["tags"] = link_group(r"/(category|kategori|tur|genre|turler)/")
    d["actorsSel"], d["actors"] = link_group(r"/(oyuncu|oyuncular|cast|actor)/")
    dm = re.search(r"(\d{2,3})\s*(?:dk|dakika|min)\b", text_of(root), re.I)
    d["duration"] = int(dm.group(1)) if dm else None
    imgs = [n for n in iter_nodes(root) if n.tag == "img" and re.search(r"poster|cover|thumb|wp-post-image|featured", " ".join(n.classes), re.I)]
    d["posterImgSel"] = (sel_for(imgs[0]) if imgs else None)
    return d


# ============================================================ AES (saf python, sadece cozme)
def _build():
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ (((q << 1) | (q >> 7)) & 0xFF) ^ (((q << 2) | (q >> 6)) & 0xFF) \
            ^ (((q << 3) | (q >> 5)) & 0xFF) ^ (((q << 4) | (q >> 4)) & 0xFF)
        sbox[p] = x ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    return sbox, inv


SBOX, INV = _build()


def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


M9 = [_mul(i, 9) for i in range(256)]
M11 = [_mul(i, 11) for i in range(256)]
M13 = [_mul(i, 13) for i in range(256)]
M14 = [_mul(i, 14) for i in range(256)]


def _expand(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = w[i - 1][:]
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        elif nk > 6 and i % nk == 4:
            t = [SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(nr + 1)]


def _dec_block(block, rks):
    nr = len(rks) - 1
    s = [a ^ b for a, b in zip(block, rks[nr])]
    for rnd in range(nr - 1, -1, -1):
        t = s[:]
        for r in range(1, 4):
            for c in range(4):
                t[((c + r) % 4) * 4 + r] = s[c * 4 + r]
        s = [INV[b] for b in t]
        s = [a ^ b for a, b in zip(s, rks[rnd])]
        if rnd:
            t = []
            for c in range(4):
                a0, a1, a2, a3 = s[c * 4:c * 4 + 4]
                t += [M14[a0] ^ M11[a1] ^ M13[a2] ^ M9[a3], M9[a0] ^ M14[a1] ^ M11[a2] ^ M13[a3],
                      M13[a0] ^ M9[a1] ^ M14[a2] ^ M11[a3], M11[a0] ^ M13[a1] ^ M9[a2] ^ M14[a3]]
            s = t
    return s


def aes_cbc_quick(ct, key, iv):
    if len(ct) < 16 or len(ct) % 16:
        return False
    rks = _expand(key)
    first = [a ^ b for a, b in zip(_dec_block(list(ct[:16]), rks), iv)]
    if not all(32 <= b < 127 or b in (9, 10, 13) for b in first):
        return False
    if len(ct) >= 32:
        last = [a ^ b for a, b in zip(_dec_block(list(ct[-16:]), rks), ct[-32:-16])]
    else:
        last = first
    pad = last[-1]
    return 1 <= pad <= 16 and all(x == pad for x in last[-pad:])


def aes_cbc_decrypt(ct, key, iv):
    rks = _expand(key)
    out = bytearray()
    prev = list(iv)
    for i in range(0, len(ct), 16):
        blk = list(ct[i:i + 16])
        out += bytes(a ^ b for a, b in zip(_dec_block(blk, rks), prev))
        prev = blk
    pad = out[-1]
    return bytes(out[:-pad]) if 1 <= pad <= 16 else None


def evp_key_iv(pw, salt, klen=32, ilen=16):
    d, prev = b"", b""
    while len(d) < klen + ilen:
        prev = hashlib.md5(prev + pw + salt).digest()
        d += prev
    return d[:klen], d[klen:klen + ilen]


def try_mode(mode, pw_str, j):
    try:
        ct = base64.b64decode(j["ct"])
        salt = bytes.fromhex(j["s"])
        iv_json = bytes.fromhex(j["iv"])
    except Exception:
        return None
    pw = pw_str.encode("utf-8")
    if mode == "evp":
        key, iv = evp_key_iv(pw, salt)
    elif mode == "pbkdf2-sha512":
        key, iv = hashlib.pbkdf2_hmac("sha512", pw, salt, 999, 32), iv_json
    elif mode == "sha256":
        key, iv = hashlib.sha256(pw).digest(), iv_json
    elif mode == "md5":
        key, iv = hashlib.md5(pw).digest() * 2, iv_json
    else:
        return None
    if len(iv) != 16 or not aes_cbc_quick(ct, key, iv):
        return None
    pt = aes_cbc_decrypt(ct, key, iv)
    if not pt:
        return None
    try:
        s = pt.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        o = json.loads(s)
        return s if isinstance(o, (dict, list)) else None
    except ValueError:
        return s if re.search(r"video_location|https?:", s) else None


def b64d(s):
    try:
        s2 = s.replace("-", "+").replace("_", "/")
        s2 += "=" * (-len(s2) % 4)
        r = base64.b64decode(s2).decode("latin-1")
        return r if r and re.fullmatch(r"[\x20-\x7e]+", r) else None
    except Exception:
        return None


def kt_str(s):
    return json.dumps(s, ensure_ascii=False).replace("$", "\\$")


def candidates(arg1, ctx, lits):
    out, seen = [], set()

    def add(label, val, kt):
        if val and val not in seen:
            seen.add(val)
            out.append((label, val, kt))

    b1 = b64d(arg1)
    b2 = b64d(b1) if b1 else None
    bases = [("ARG1", arg1, "arg1")]
    if b1:
        bases.append(("base64(ARG1)", b1, "String(Base64.decode(arg1, Base64.DEFAULT))"))
    if b2:
        bases.append(("base64(base64(ARG1))", b2, "String(Base64.decode(String(Base64.decode(arg1, Base64.DEFAULT)), Base64.DEFAULT))"))
    for b in bases:
        add(*b)
    consts = [(c[0], c[1], kt_str(c[1])) for c in ctx] + [('"%s"' % s, s, kt_str(s)) for s in lits]
    for c in consts:
        add(*c)
    for b in bases:
        for c in consts:
            add(b[0] + " + " + c[0], b[1] + c[1], b[2] + " + " + c[2])
            add(c[0] + " + " + b[0], c[1] + b[1], c[2] + " + " + b[2])
    return out


def literals(text):
    out, seen = [], set()
    for m in re.finditer(r"([\"'])([A-Za-z0-9+/=_\-.:]{8,64})\1", text):
        s = m.group(2)
        if s in seen or s.startswith("http") or s in ("function", "undefined", "object", "string", "number"):
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= 120:
            break
    return out


# ============================================================ embed / video zinciri
def find_iframes(html, base):
    out = []
    for tag in re.finditer(r"<iframe\b[^>]*>", html, re.I):
        for a in ("data-litespeed-src", "data-src", "data-lazy-src", "src"):
            m = re.search(r"(?<![\w-])" + a + r"\s*=\s*[\"']([^\"']+)[\"']", tag.group(0), re.I)
            if m and not re.match(r"(about:|data:|javascript:)", m.group(1), re.I):
                u = absu(m.group(1).replace("&amp;", "&"), base)
                if u and u not in out:
                    out.append(u)
    if not out:
        for m in re.finditer(r"https?://[^\"'\s<>]+/embed/[A-Za-z0-9_-]+", html):
            if m.group(0) not in out:
                out.append(m.group(0))
    out.sort(key=lambda u: 0 if re.search(r"embed|player", u, re.I) else 1)
    return out


def find_beplayer(html):
    m = re.search(r"bePlayer\(\s*(['\"])(.*?)\1\s*,\s*(['\"])(\{.*?\})\3\s*\)", html, re.S)
    if not m:
        return None
    a2 = m.group(4)
    cleaned = a2.replace("\\\\/", "/").replace("\\/", "/")
    j = None
    for cand in (cleaned, a2):
        try:
            j = json.loads(cand)
            break
        except ValueError:
            continue
    return {"arg1": m.group(2), "arg2": a2, "json": j}


def script_srcs(html, base):
    out = []
    for m in re.finditer(r"<script\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", html, re.I):
        u = absu(m.group(1), base)
        if u and u not in out:
            out.append(u)
    return out


def inline_scripts(html):
    return [m.group(1) for m in re.finditer(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.I | re.S)]


def extract_fn(text):
    m = re.search(r"(function\s+bePlayer\s*\(|bePlayer\s*=\s*function|bePlayer\s*=\s*\(?[\w,\s]*\)?\s*=>|window\.bePlayer\s*=)", text)
    if not m:
        return None
    s = m.start()
    i = text.find("{", s)
    if i < 0:
        return text[s:s + 4000]
    d = 0
    while i < len(text) and i < s + 30000:
        c = text[i]
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
            if d == 0:
                return text[s:i + 1]
        i += 1
    return text[s:s + 6000]


def resolve_variants(master_text, base):
    lines = master_text.splitlines()
    vs = []
    for i, l in enumerate(lines):
        if l.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
            res = re.search(r"RESOLUTION=([\dx]+)", l)
            bw = re.search(r"BANDWIDTH=(\d+)", l)
            vs.append({"res": res.group(1) if res else "", "bw": bw.group(1) if bw else "", "url": absu(lines[i + 1].strip(), base)})
    return vs


def analyze_video(film_url, film_html):
    V = {"film": film_url, "algo": None, "notes": []}
    ifr = find_iframes(film_html, film_url)
    V["iframes"] = ifr
    if not ifr:
        V["error"] = "Film sayfasinda iframe yok (video sonradan JS ile ekleniyor olabilir)"
        return V
    embed = ifr[0]
    say("OK", "iframe: %s%s" % (short(embed), " (+%d daha)" % (len(ifr) - 1) if len(ifr) > 1 else ""))
    eh = fetch(embed, ref=film_url)
    V["embed"] = embed
    say("OK" if eh["status"] == 200 else "HATA", "Embed HTTP %s, cerez: %s" % (eh["status"], ",".join(eh["cookies"]) or "yok"))
    if eh["status"] != 200:
        V["error"] = "Embed acilmadi"
        return V
    page = eh["body"]
    origin = "%s://%s" % (urllib.parse.urlparse(embed).scheme, host(embed))
    bp = find_beplayer(page)
    V["hasBePlayer"] = bool(bp)
    if not bp:
        V["notes"].append("bePlayer yok: eklenti loadExtractor ile calisir")
        say("DIKKAT", "bePlayer(...) yok, farkli bir oynatici. Kotlin'de loadExtractor kullanilacak.")
        return V
    V["arg1"], V["arg2"] = bp["arg1"], bp["arg2"]
    srcs = script_srcs(page, embed)
    own = [u for u in srcs if host(u) == host(embed) and not re.search(r"jquery|humane|polyfill|\.css|cry\.js", u, re.I)]
    all_text = "\n".join(inline_scripts(page))
    V["scripts"] = {}
    for u in own:
        r = fetch(u, ref=embed)
        V["scripts"][u] = {"status": r["status"], "bytes": r["bytes"], "body": r["body"][:80000]}
        if r["status"] == 200:
            all_text += "\n" + r["body"]
    fn = extract_fn(all_text)
    V["bePlayerFn"] = fn
    plain = None
    if bp["json"] and "ct" in bp["json"]:
        ctx = [("referer sitesi", host(film_url)), ("embed sitesi", host(embed)),
               ("embed kimligi", embed.rstrip("/").split("/")[-1]), ("film adresi", film_url)]
        cl = candidates(bp["arg1"], ctx, literals(fn or all_text))
        for mode in ("evp", "sha256", "md5", "pbkdf2-sha512"):
            for i in range(10 if mode == "pbkdf2-sha512" else len(cl)):
                s = try_mode(mode, cl[i][1], bp["json"])
                if s:
                    plain = s
                    V["algo"] = {"mode": mode, "label": cl[i][0], "kt": cl[i][2]}
                    break
            if plain:
                break
    if V["algo"]:
        say("OK", "Sifre COZULDU: %s, parola=%s" % (V["algo"]["mode"], V["algo"]["label"]))
    else:
        say("HATA", "Sifre cozulemedi, rapor yine de yazilir")
    try:
        info = json.loads(plain) if plain else None
    except ValueError:
        info = None
    V["decrypted"] = info
    if isinstance(info, dict) and info.get("video_location"):
        vl = info["video_location"]
        m = fetch(vl, ref=embed, origin=origin)
        V["masterStatus"] = m["status"]
        say("OK" if m["status"] == 200 else "HATA", "Master HTTP %s" % m["status"])
        if m["status"] == 200 and "#EXTM3U" in m["body"]:
            vs = resolve_variants(m["body"], vl)
            V["variants"] = vs
            if vs:
                v = fetch(vs[0]["url"], ref=embed, origin=origin)
                segs = [l for l in v["body"].splitlines() if l and not l.startswith("#")]
                V["segments"] = len(segs)
                V["segmentUrl"] = absu(segs[0], vs[0]["url"]) if segs else None
                say("OK" if v["status"] == 200 else "DIKKAT", "Varyant HTTP %s, %d segment" % (v["status"], len(segs)))
    return V


# ============================================================ kotlin uretimi
def decrypt_members(mode, kt):
    L = ["    private fun hexToBytes(s: String) = s.chunked(2).map { it.toInt(16).toByte() }.toByteArray()", ""]
    if mode == "evp":
        L += [
            "    private fun evpKeyIv(pass: ByteArray, salt: ByteArray): Pair<ByteArray, ByteArray> {",
            "        val md = MessageDigest.getInstance(\"MD5\")",
            "        var d = ByteArray(0)",
            "        var prev = ByteArray(0)",
            "        while (d.size < 48) {",
            "            md.reset()",
            "            prev = md.digest(prev + pass + salt)",
            "            d += prev",
            "        }",
            "        return d.copyOfRange(0, 32) to d.copyOfRange(32, 48)",
            "    }",
            "",
            "    private fun decryptBePlayer(arg1: String, json: String): String? = try {",
            "        val o = JSONObject(json)",
            "        val passphrase = " + kt,
            "        val (key, iv) = evpKeyIv(passphrase.toByteArray(Charsets.UTF_8), hexToBytes(o.getString(\"s\")))",
            "        val cipher = Cipher.getInstance(\"AES/CBC/PKCS5Padding\")",
            "        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, \"AES\"), IvParameterSpec(iv))",
            "        String(cipher.doFinal(Base64.decode(o.getString(\"ct\"), Base64.DEFAULT)), Charsets.UTF_8)",
            "    } catch (e: Exception) {",
            "        null",
            "    }"]
    else:
        if mode == "pbkdf2-sha512":
            keyline = ["        val spec = javax.crypto.spec.PBEKeySpec(passphrase.toCharArray(), hexToBytes(o.getString(\"s\")), 999, 256)",
                       "        val key = javax.crypto.SecretKeyFactory.getInstance(\"PBKDF2WithHmacSHA512\").generateSecret(spec).encoded"]
        elif mode == "sha256":
            keyline = ["        val key = MessageDigest.getInstance(\"SHA-256\").digest(passphrase.toByteArray())"]
        else:
            keyline = ["        val key = MessageDigest.getInstance(\"MD5\").digest(passphrase.toByteArray()).let { it + it }"]
        L += (["    private fun decryptBePlayer(arg1: String, json: String): String? = try {",
               "        val o = JSONObject(json)",
               "        val passphrase = " + kt] + keyline + [
                  "        val cipher = Cipher.getInstance(\"AES/CBC/PKCS5Padding\")",
                  "        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, \"AES\"), IvParameterSpec(hexToBytes(o.getString(\"iv\"))))",
                  "        String(cipher.doFinal(Base64.decode(o.getString(\"ct\"), Base64.DEFAULT)), Charsets.UTF_8)",
                  "    } catch (e: Exception) {",
                  "        null",
                  "    }"])
    return "\n".join(L)


CARD_FN = r'''
    private fun Element.@@FN@@(): SearchResponse? {
        val a = selectFirst(@@LINK@@) ?: return null
        val href = fixUrlNull(a.attr("href")) ?: return null
        val title = ((@@TITLE@@) ?: "").replace(Regex("""\s*(film(i)?\s+)?izle\s*$""", RegexOption.IGNORE_CASE), "").trim()
        if (title.isBlank()) return null
        val poster = fixUrlNull(selectFirst("img")?.attr(@@POSTER@@))
        return newMovieSearchResponse(title, href, TvType.Movie) { this.posterUrl = poster }
    }
'''

KT_TEMPLATE = r'''package @@PKG@@

import android.util.Base64
import com.lagradost.cloudstream3.*
import com.lagradost.cloudstream3.utils.*
import org.json.JSONObject
import org.jsoup.nodes.Element
import java.net.URI
import java.net.URLEncoder
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

// Bu dosya cloudstream_pydroid_tam.py tarafindan otomatik uretildi.
// @@NOTES@@
class @@CLS@@ : MainAPI() {
    override var mainUrl = "@@ORIGIN@@"
    override var name = "@@NAME@@"
    override var lang = "tr"
    override val hasMainPage = true
    override val supportedTypes = setOf(TvType.Movie)

    private val ua =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    private val baseHeaders = mapOf("User-Agent" to ua, "Accept" to "*/*")

    // ---------------------------------------------------------------- ANA SAYFA
    override val mainPage = mainPageOf(
@@MAINPAGE@@
    )

    private fun pageUrl(base: String, page: Int): String =
        if (page <= 1) base else @@PAGEEXPR@@

    override suspend fun getMainPage(page: Int, request: MainPageRequest): HomePageResponse {
        val doc = app.get(pageUrl(request.data, page), headers = baseHeaders).document
        val items = doc.select(@@HOMECARD@@).mapNotNull { it.toSearchResult() }.distinctBy { it.url }
        return newHomePageResponse(request.name, items, hasNext = items.isNotEmpty())
    }
@@CARDFN@@
    // ---------------------------------------------------------------- ARAMA
    override suspend fun search(query: String): List<SearchResponse> {
        val q = URLEncoder.encode(query, "UTF-8")
        val doc = app.get(@@SEARCHURL@@, headers = baseHeaders).document
        return doc.select(@@SEARCHCARD@@).mapNotNull { it.@@SEARCHFN@@() }.distinctBy { it.url }
    }

    // ---------------------------------------------------------------- DETAY
    override suspend fun load(url: String): LoadResponse? {
        val doc = app.get(url, headers = baseHeaders).document
@@LOADBODY@@
    }

    // ---------------------------------------------------------------- VIDEO
    override suspend fun loadLinks(
        data: String,
        isCasting: Boolean,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit
    ): Boolean {
        val page = app.get(data, headers = baseHeaders).document
        val embeds = page.select("iframe").mapNotNull { f ->
            listOf("data-litespeed-src", "data-src", "data-lazy-src", "src")
                .map { f.attr(it) }
                .firstOrNull { it.startsWith("http") || it.startsWith("//") }
        }.map { fixUrl(it) }.distinct()
        var found = false
        for (embed in embeds) {
            if (loadBePlayer(embed, data, subtitleCallback, callback)) found = true
            else if (loadExtractor(embed, data, subtitleCallback, callback)) found = true
        }
        return found
    }

    // iframe -> embed (Referer: film sayfasi) -> bePlayer(ARG1, JSON) -> AES coz -> video_location (master HLS)
    private suspend fun loadBePlayer(
        embed: String,
        referer: String,
        subtitleCallback: (SubtitleFile) -> Unit,
        callback: (ExtractorLink) -> Unit
    ): Boolean {
        val html = app.get(embed, referer = referer, headers = baseHeaders).text
        val m = Regex("""bePlayer\(\s*(['"])(.*?)\1\s*,\s*(['"])(\{.*?\})\3""", RegexOption.DOT_MATCHES_ALL)
            .find(html) ?: return false
        val arg1 = m.groupValues[2]
        val json = m.groupValues[4].replace("\\/", "/")
@@DECRYPTCALL@@
        val o = JSONObject(plain)
        val master = o.optString("video_location").takeIf { it.isNotBlank() } ?: return false
        val origin = "https://" + URI(embed).host

        o.optJSONArray("strSubtitles")?.let { arr ->
            for (i in 0 until arr.length()) {
                val s = arr.optJSONObject(i) ?: continue
                if (s.isNull("file")) continue
                val f = s.optString("file")
                if (f.isBlank()) continue
                val sub = if (f.startsWith("http")) f else origin + f
                subtitleCallback.invoke(newSubtitleFile(s.optString("label", "Türkçe"), sub))
            }
        }

        // Master istegi Referer(embed)+Origin ister, segmentler User-Agent ister. URL oturuma bagli: her oynatmada bastan coz.
        val streamHeaders = mapOf(
            "User-Agent" to ua,
            "Accept" to "*/*",
            "Referer" to embed,
            "Origin" to origin
        )
        callback.invoke(
            newExtractorLink(
                source = name,
                name = "$name HLS",
                url = master,
                type = ExtractorLinkType.M3U8
            ) {
                this.referer = embed
                this.quality = Qualities.Unknown.value
                this.headers = streamHeaders
            }
        )
        return true
    }

@@MEMBERS@@
}
'''


def build_load_body(d, film_spec):
    L = []
    t_h1 = 'doc.selectFirst("h1")?.text()' if d.get("h1") else "null"
    L.append('        val title = (%s ?: doc.selectFirst("meta[property=og:title]")?.attr("content"))?.trim()' % t_h1)
    L.append('            ?.replace(Regex("""\\s*(film(i)?\\s+)?izle\\s*(\\|.*)?$""", RegexOption.IGNORE_CASE), "")?.trim()')
    L.append("            ?.takeIf { it.isNotBlank() } ?: return null")
    poster = 'doc.selectFirst("meta[property=og:image]")?.attr("content")'
    if not d.get("ogImage") and d.get("posterImgSel"):
        poster = 'doc.selectFirst(%s)?.attr("src")' % kt_str(d["posterImgSel"])
    L.append("        val poster = fixUrlNull(%s)" % poster)
    if d.get("plotSel"):
        L.append('        val plot = (doc.selectFirst(%s)?.text() ?: doc.selectFirst("meta[property=og:description]")?.attr("content"))?.trim()' % kt_str(d["plotSel"]))
    else:
        L.append('        val plot = doc.selectFirst("meta[property=og:description]")?.attr("content")?.trim()')
    L.append('        val year = Regex("""\\b(19|20)\\d{2}\\b""").find(title)?.value?.toIntOrNull()')
    if d.get("tagsSel") and d.get("tags"):
        L.append('        val tags = doc.select(%s).map { it.text().trim() }.filter { it.isNotBlank() }.distinct()' % kt_str(d["tagsSel"]))
    else:
        L.append("        val tags = emptyList<String>()")
    if d.get("actorsSel") and d.get("actors"):
        L.append('        val actors = doc.select(%s).map { it.text().trim() }.filter { it.isNotBlank() }.distinct()' % kt_str(d["actorsSel"]))
    else:
        L.append("        val actors = emptyList<String>()")
    L.append('        val duration = Regex("""(\\d{2,3})\\s*(?:dk|dakika|min)\\b""", RegexOption.IGNORE_CASE)'
             '.find(doc.text())?.groupValues?.get(1)?.toIntOrNull()')
    L += ["        return newMovieLoadResponse(title, url, TvType.Movie, url) {",
          "            this.posterUrl = poster",
          "            this.plot = plot",
          "            this.year = year",
          "            this.tags = tags",
          "            this.duration = duration",
          "            addActors(actors)",
          "        }"]
    return "\n".join(L)


def generate_kotlin(S):
    origin = S["origin"]
    nm = host(origin).replace("www.", "").split(".")[0]
    cls = re.sub(r"[^A-Za-z0-9]", "", nm.title()) or "Site"
    if cls[0].isdigit():
        cls = "Site" + cls
    home, srch = S["homeSpec"], S["searchSpec"] or S["homeSpec"]

    def card_fn(spec, fname):
        t = spec["titleExpr"] or 'a.attr("title")'
        return (CARD_FN.replace("@@FN@@", fname).replace("@@LINK@@", kt_str(spec["linkSel"]))
                .replace("@@TITLE@@", t).replace("@@POSTER@@", kt_str(spec["posterAttr"] or "src")))

    cardfn = card_fn(home, "toSearchResult")
    same = (srch["selector"] == home["selector"] and srch["titleExpr"] == home["titleExpr"]
            and srch["posterAttr"] == home["posterAttr"] and srch["linkSel"] == home["linkSel"])
    searchfn = "toSearchResult"
    if not same:
        cardfn += "\n" + card_fn(srch, "toSearchResultSearch")
        searchfn = "toSearchResultSearch"

    mp = ['        "$mainUrl/" to "Son Eklenenler"']
    for u, t in S["categories"]:
        rel = u[len(origin):] if u.startswith(origin) else u
        base = ("$mainUrl" + rel) if u.startswith(origin) else u
        mp.append("        %s to %s" % (kt_str(base).replace('\\$mainUrl', '$mainUrl'), kt_str(t)))
    style = S["pageStyle"] or "path"
    if style == "path":
        pageexpr = 'base.trimEnd(\'/\') + "/page/$page/"'
    elif style == "sayfa":
        pageexpr = 'base.trimEnd(\'/\') + "/sayfa/$page/"'
    else:
        pageexpr = 'base + (if (base.contains("?")) "&" else "?") + "%s=$page"' % ("paged" if style == "paged" else "page")
    tpl = S["searchTemplate"] or {"kind": "query", "action": origin + "/", "name": "s"}
    V = S["video"]
    if V.get("algo"):
        members = decrypt_members(V["algo"]["mode"], V["algo"]["kt"])
        decryptcall = "        val plain = decryptBePlayer(arg1, json) ?: return false"
    else:
        members = "    // Sifre cozme algoritmasi bulunamadi: bePlayer varsa loadExtractor denenir"
        decryptcall = "        return false // TODO: sifre cozme algoritmasi bulunamadi"
    notes = ", ".join(S["notes"]) or "dogrulanmamis kisim yok"
    code = (KT_TEMPLATE
            .replace("@@PKG@@", "com." + cls.lower()).replace("@@CLS@@", cls).replace("@@NAME@@", cls)
            .replace("@@ORIGIN@@", origin).replace("@@MAINPAGE@@", ",\n".join(mp))
            .replace("@@PAGEEXPR@@", pageexpr).replace("@@HOMECARD@@", kt_str(home["selector"]))
            .replace("@@CARDFN@@", cardfn).replace("@@SEARCHURL@@", kt_search_expr(tpl, origin))
            .replace("@@SEARCHCARD@@", kt_str(srch["selector"])).replace("@@SEARCHFN@@", searchfn)
            .replace("@@LOADBODY@@", build_load_body(S["detail"], home))
            .replace("@@DECRYPTCALL@@", decryptcall).replace("@@MEMBERS@@", members)
            .replace("@@NOTES@@", "Notlar: " + notes))
    return cls, code


# ============================================================ ana akis
def run(url_in):
    jar.clear()
    S = {"input": url_in, "notes": []}
    p = urllib.parse.urlparse(url_in)
    origin = "%s://%s" % (p.scheme, p.netloc)
    S["origin"] = origin
    home_url = origin + "/"
    say("1", "Ana sayfa cekiliyor: " + home_url)
    hp = fetch(home_url)
    say("OK" if hp["status"] == 200 else "HATA", "HTTP %s, %s bayt" % (hp["status"], hp["bytes"]))
    if hp["status"] != 200:
        S["error"] = "Ana sayfa acilmadi: %s %s" % (hp["status"], hp.get("error", ""))
        return S
    hroot = parse_html(hp["body"])

    det = detect_cards(hroot, origin, 3)
    if not det:
        S["error"] = "Ana sayfada film kartlari bulunamadi"
        S["homeHtmlHead"] = hp["body"][:3000]
        return S
    hs = card_spec(det, origin, "ana sayfa")
    S["homeSpec"] = hs
    say("OK" if hs["ok"] else "DIKKAT", "Kart secici: %s  (%d kart)" % (hs["selector"], hs["units"]))
    say("OK" if hs["titleExpr"] else "DIKKAT", "Baslik: %s -> %s" % (hs["titleExpr"], short(hs["titleSample"], 50)))
    say("OK" if hs["posterAttr"] else "DIKKAT", "Afis: attr=%s -> %s" % (hs["posterAttr"], short(hs["posterSample"] or "", 70)))
    say("OK", "Film link secici: %s (ornek: %s)" % (hs["linkSel"], short(hs["linkSample"], 70)))

    S["categories"] = find_categories(hroot, origin, hs["filmPrefix"])
    say("OK" if S["categories"] else "DIKKAT", "Kategori: %d adet %s" % (len(S["categories"]), ", ".join(t for _, t in S["categories"][:6])))
    style = find_page_pattern(hp["body"], origin) or "path"
    S["pageStyle"] = style
    p2 = fetch(page_url(home_url, 2, style))
    d2 = detect_cards(parse_html(p2["body"]), origin, 2) if p2["status"] == 200 else None
    ok2 = bool(d2 and d2["hrefs"] and d2["hrefs"][0] != det["hrefs"][0])
    S["pageVerified"] = ok2
    say("OK" if ok2 else "DIKKAT", "Sayfalama (%s): 2. sayfa %s" % (style, "dogrulandi" if ok2 else "dogrulanamadi"))
    if not ok2:
        S["notes"].append("sayfalama dogrulanamadi")

    # film sayfasi
    film = None
    pu = p.path
    if pu not in ("", "/") and norm_href(url_in, origin) and (not hs["filmPrefix"] or hs["filmPrefix"] in pu):
        film = url_in
    elif hs["linkSample"]:
        film = hs["linkSample"]
    S["filmUrl"] = film
    if not film:
        S["error"] = "Film linki bulunamadi"
        return S
    say("2", "Film sayfasi: " + short(film))
    fp = fetch(film, ref=home_url)
    say("OK" if fp["status"] == 200 else "HATA", "HTTP %s, %s bayt" % (fp["status"], fp["bytes"]))
    if fp["status"] != 200:
        S["error"] = "Film sayfasi acilmadi"
        return S
    froot = parse_html(fp["body"])
    dt = detail_spec(froot, fp["body"], film, origin)
    S["detail"] = dt
    say("OK" if dt["title"] else "DIKKAT", "Baslik: %s" % short(dt["title"], 70))
    say("OK" if dt["ogImage"] else "DIKKAT", "Afis (og:image): %s" % short(dt["ogImage"] or "yok", 70))
    say("OK" if dt["plot"] or dt["ogDesc"] else "DIKKAT", "Ozet: %s %s" % (("[%s]" % dt["plotSel"]) if dt["plotSel"] else "[og:description]", short(dt["plot"] or dt["ogDesc"], 60)))
    say("OK" if dt["year"] else "DIKKAT", "Yil: %s" % dt["year"])
    say("OK" if dt["tags"] else "DIKKAT", "Turler: %s [%s]" % (", ".join(dt["tags"][:5]), dt["tagsSel"]))
    say("OK" if dt["actors"] else "DIKKAT", "Oyuncular: %s" % (", ".join(dt["actors"][:5]) or "bulunamadi"))
    say("OK" if dt["duration"] else "DIKKAT", "Sure: %s dk" % dt["duration"])

    # video zinciri
    say("3", "Video zinciri")
    S["video"] = analyze_video(film, fp["body"])
    if S["video"].get("error"):
        S["notes"].append(S["video"]["error"])

    # arama
    word = ""
    for w in re.findall(r"[^\W\d_]{4,}", (hs["titleSample"] or dt["title"] or ""), re.U):
        word = w
        break
    S["searchWord"] = word or "film"
    say("4", "Arama deneniyor: '%s'" % S["searchWord"])
    found = find_search(hroot, origin)
    S["searchSpec"], S["searchTemplate"] = None, None
    for t in search_templates(origin, found):
        su = search_url(t, S["searchWord"])
        r = fetch(su, ref=home_url)
        if r["status"] != 200:
            continue
        sroot = parse_html(r["body"])
        cards = select(sroot, hs["selector"])
        dsrch = detect_cards(sroot, origin, 1)
        if cards:
            S["searchTemplate"] = t
            S["searchSpec"] = None
            S["searchUrlSample"] = su
            say("OK", "Arama adresi: %s (ana sayfa seciclisiyle %d sonuc)" % (short(su, 80), len(cards)))
            break
        if dsrch:
            S["searchTemplate"] = t
            sp = card_spec(dsrch, origin, "arama")
            S["searchSpec"] = sp
            S["searchUrlSample"] = su
            say("OK", "Arama adresi: %s, ayri secici: %s (%d sonuc)" % (short(su, 70), sp["selector"], sp["units"]))
            break
    if not S["searchTemplate"]:
        S["notes"].append("arama adresi dogrulanamadi")
        say("DIKKAT", "Arama adresi dogrulanamadi, /?s= varsayildi")

    cls, code = generate_kotlin(S)
    S["kotlinClass"], S["kotlin"] = cls, code
    return S


def out_dir():
    for d in ("/storage/emulated/0/Download", os.getcwd(), os.path.expanduser("~")):
        try:
            if os.path.isdir(d) and os.access(d, os.W_OK):
                return d
        except Exception:
            pass
    return "."


def slim(S):
    """Raporu kucult: DOM nesneleri zaten yok, buyuk govdeleri kes."""
    R = json.loads(json.dumps(S, default=str))
    v = R.get("video") or {}
    for k, s in (v.get("scripts") or {}).items():
        s["body"] = s["body"][:30000]
    return R


def save(S):
    d = out_dir()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    paths = []
    try:
        pj = os.path.join(d, "rapor_%s.json" % stamp)
        with open(pj, "w", encoding="utf-8") as f:
            json.dump(slim(S), f, ensure_ascii=False, indent=1)
        paths.append(pj)
        if S.get("kotlin"):
            pk = os.path.join(d, "%s.kt" % S["kotlinClass"])
            with open(pk, "w", encoding="utf-8") as f:
                f.write(S["kotlin"])
            paths.append(pk)
    except Exception as e:
        print("Dosya yazilamadi:", e)
    return paths


def main():
    print("CloudStream Araci TAM (Pydroid 3)")
    print("Sitenin ana sayfa linkini yaz (ya da bir film linki), Enter. Bos = cikis.\n")
    first = sys.argv[1] if len(sys.argv) > 1 else None
    while True:
        try:
            u = first or input("Link: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        first = None
        if not u:
            break
        if not re.match(r"https?://", u):
            u = "https://" + u
        try:
            S = run(u)
        except Exception as e:
            import traceback
            S = {"input": u, "error": "%s: %s" % (type(e).__name__, e), "trace": traceback.format_exc()}
        if S.get("error"):
            say("HATA", S["error"])
        paths = save(S)
        if paths:
            print("\nKaydedildi:")
            for p in paths:
                print("  ", p)
            if len(paths) > 1:
                print("Eklenti dosyasi hazir: %s" % paths[1])
            print("Sorun varsa rapor_*.json dosyasinin icerigini bana gonder.")
        print("\n" + "-" * 70 + "\n")


if __name__ == "__main__":
    main()
