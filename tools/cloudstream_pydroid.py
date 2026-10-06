# -*- coding: utf-8 -*-
"""
CloudStream Araci - Pydroid 3 surumu (tarayici gerekmez, ek paket gerekmez)

Kullanim: Pydroid 3'te ac, calistir (sari ok), linki yapistir, Enter.
Zincir: film sayfasi -> iframe -> embed -> bePlayer -> sifre cozme -> master HLS
Cikti: ekranda ozet + Kotlin kodu, ayrica rapor dosyasi (rapor_*.json, kotlin_*.kt)
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

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MAX_BYTES = 3 * 1024 * 1024

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
opener.addheaders = []


# ------------------------------------------------------------------ ag
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


# ------------------------------------------------------------------ html
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


# ------------------------------------------------------------------ AES (saf python, sadece cozme)
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
                t += [M14[a0] ^ M11[a1] ^ M13[a2] ^ M9[a3],
                      M9[a0] ^ M14[a1] ^ M11[a2] ^ M13[a3],
                      M13[a0] ^ M9[a1] ^ M14[a2] ^ M11[a3],
                      M11[a0] ^ M13[a1] ^ M9[a2] ^ M14[a3]]
            s = t
    return s


def aes_cbc_quick(ct, key, iv):
    """Hizli on kontrol: ilk blok yazdirilabilir mi, son blok dolgusu gecerli mi."""
    if len(ct) < 16 or len(ct) % 16:
        return False
    rks = _expand(key)
    first = [a ^ b for a, b in zip(_dec_block(list(ct[:16]), rks), iv)]
    if not all(32 <= b < 127 or b in (9, 10, 13) for b in first):
        return False
    if len(ct) >= 32:
        prev = ct[-32:-16]
        last = [a ^ b for a, b in zip(_dec_block(list(ct[-16:]), rks), prev)]
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
        pt = _dec_block(blk, rks)
        out += bytes(a ^ b for a, b in zip(pt, prev))
        prev = blk
    pad = out[-1]
    if not 1 <= pad <= 16:
        return None
    return bytes(out[:-pad])


# ------------------------------------------------------------------ anahtar turetme
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
    return json.dumps(s).replace("$", "\\$")


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
        bases.append(("base64(base64(ARG1))", b2,
                      "String(Base64.decode(String(Base64.decode(arg1, Base64.DEFAULT)), Base64.DEFAULT))"))
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


# ------------------------------------------------------------------ kotlin uretimi
def kotlin_for(mode, kt):
    head = [
        "import android.util.Base64",
        "import org.json.JSONObject",
        "import javax.crypto.Cipher",
        "import javax.crypto.spec.IvParameterSpec",
        "import javax.crypto.spec.SecretKeySpec",
        "",
        "private fun hexToBytes(s: String) = s.chunked(2).map { it.toInt(16).toByte() }.toByteArray()",
        ""]
    if mode == "evp":
        body = [
            "private fun evpKeyIv(pass: ByteArray, salt: ByteArray): Pair<ByteArray, ByteArray> {",
            "    val md = java.security.MessageDigest.getInstance(\"MD5\")",
            "    var d = ByteArray(0); var prev = ByteArray(0)",
            "    while (d.size < 48) { md.reset(); prev = md.digest(prev + pass + salt); d += prev }",
            "    return d.copyOfRange(0, 32) to d.copyOfRange(32, 48)",
            "}",
            "",
            "// arg1 = bePlayer('ARG1', ...) ilk arguman, json = ikinci arguman",
            "fun decryptBePlayer(arg1: String, json: String): String? = try {",
            "    val o = JSONObject(json)",
            "    val passphrase = " + kt,
            "    val (key, iv) = evpKeyIv(passphrase.toByteArray(), hexToBytes(o.getString(\"s\")))",
            "    val cipher = Cipher.getInstance(\"AES/CBC/PKCS5Padding\")",
            "    cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, \"AES\"), IvParameterSpec(iv))",
            "    String(cipher.doFinal(Base64.decode(o.getString(\"ct\"), Base64.DEFAULT)), Charsets.UTF_8)",
            "} catch (e: Exception) { null }"]
    elif mode == "pbkdf2-sha512":
        body = [
            "fun decryptBePlayer(arg1: String, json: String): String? = try {",
            "    val o = JSONObject(json)",
            "    val passphrase = " + kt,
            "    val spec = javax.crypto.spec.PBEKeySpec(passphrase.toCharArray(), hexToBytes(o.getString(\"s\")), 999, 256)",
            "    val key = javax.crypto.SecretKeyFactory.getInstance(\"PBKDF2WithHmacSHA512\").generateSecret(spec).encoded",
            "    val cipher = Cipher.getInstance(\"AES/CBC/PKCS5Padding\")",
            "    cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, \"AES\"), IvParameterSpec(hexToBytes(o.getString(\"iv\"))))",
            "    String(cipher.doFinal(Base64.decode(o.getString(\"ct\"), Base64.DEFAULT)), Charsets.UTF_8)",
            "} catch (e: Exception) { null }"]
    else:
        digest = "SHA-256" if mode == "sha256" else "MD5"
        key_expr = ("java.security.MessageDigest.getInstance(\"SHA-256\").digest(passphrase.toByteArray())"
                    if mode == "sha256" else
                    "java.security.MessageDigest.getInstance(\"MD5\").digest(passphrase.toByteArray()).let { it + it }")
        body = [
            "fun decryptBePlayer(arg1: String, json: String): String? = try {",
            "    val o = JSONObject(json)",
            "    val passphrase = " + kt,
            "    val key = " + key_expr + "   // " + digest,
            "    val cipher = Cipher.getInstance(\"AES/CBC/PKCS5Padding\")",
            "    cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, \"AES\"), IvParameterSpec(hexToBytes(o.getString(\"iv\"))))",
            "    String(cipher.doFinal(Base64.decode(o.getString(\"ct\"), Base64.DEFAULT)), Charsets.UTF_8)",
            "} catch (e: Exception) { null }"]
    return "\n".join(head + body)


# ------------------------------------------------------------------ cikti yardimcilari
def out_dir():
    for d in ("/storage/emulated/0/Download", os.getcwd(), os.path.expanduser("~")):
        try:
            if os.path.isdir(d) and os.access(d, os.W_OK):
                return d
        except Exception:
            pass
    return "."


def say(tag, msg):
    print("[%s] %s" % (tag, msg))
    sys.stdout.flush()


def short(u, n=110):
    return u if len(u) <= n else u[:n] + "..."


def resolve_variants(master_text, base):
    lines = master_text.splitlines()
    vs = []
    for i, l in enumerate(lines):
        if l.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
            res = re.search(r"RESOLUTION=([\dx]+)", l)
            bw = re.search(r"BANDWIDTH=(\d+)", l)
            vs.append({"res": res.group(1) if res else "", "bw": bw.group(1) if bw else "",
                       "url": absu(lines[i + 1].strip(), base)})
    return vs


# ------------------------------------------------------------------ ana akis
def run(site):
    R = {"site": site, "steps": [], "notes": []}
    jar.clear()
    say("1", "Sayfa cekiliyor: " + short(site))
    p1 = fetch(site)
    R["steps"].append({"n": 1, "url": site, "status": p1["status"], "bytes": p1["bytes"]})
    say("OK" if p1["status"] == 200 else "HATA", "HTTP %s, %s bayt" % (p1["status"], p1["bytes"]))
    if p1["status"] != 200:
        return R, "Sayfa acilmadi"

    if re.search(r"bePlayer\s*\(", p1["body"]):
        embed, eh = site, p1
        say("OK", "Verilen adres zaten embed sayfasi")
    else:
        ifr = find_iframes(p1["body"], site)
        R["iframes"] = ifr
        if not ifr:
            return R, "Sayfada iframe yok (video sonradan JS ile ekleniyor olabilir)"
        embed = ifr[0]
        say("OK", "iframe: " + short(embed) + ("  (+%d iframe daha)" % (len(ifr) - 1) if len(ifr) > 1 else ""))
        say("2", "Embed cekiliyor (Referer = film sayfasi)")
        eh = fetch(embed, ref=site)
        R["steps"].append({"n": 2, "url": embed, "status": eh["status"], "bytes": eh["bytes"],
                           "referer": site, "cookies": eh["cookies"]})
        say("OK" if eh["status"] == 200 else "HATA",
            "HTTP %s, %s bayt, cerez: %s" % (eh["status"], eh["bytes"], ",".join(eh["cookies"]) or "yok"))
        if eh["status"] != 200:
            return R, "Embed acilmadi"
    R["embed"] = embed
    page = eh["body"]
    origin = "%s://%s" % (urllib.parse.urlparse(embed).scheme, host(embed))

    bp = find_beplayer(page)
    if not bp:
        say("DIKKAT", "bePlayer(...) cagrisi bulunamadi, farkli bir oynatici olabilir")
        R["notes"].append("bePlayer cagrisi yok")
    else:
        R["arg1"], R["arg2"] = bp["arg1"], bp["arg2"]
        say("OK", "bePlayer bulundu (ARG1 %d, ARG2 %d karakter)" % (len(bp["arg1"]), len(bp["arg2"])))
        if not bp["json"] or "ct" not in bp["json"]:
            say("DIKKAT", "ARG2 {ct, iv, s} bicininde degil")

    srcs = script_srcs(page, embed)
    own = [u for u in srcs if host(u) == host(embed) and not re.search(r"jquery|humane|polyfill|\.css|cry\.js", u, re.I)]
    all_text = "\n".join(inline_scripts(page))
    R["scripts"] = {}
    for u in own:
        try:
            r = fetch(u, ref=embed)
            R["scripts"][u] = {"status": r["status"], "bytes": r["bytes"], "body": r["body"][:80000]}
            say("OK" if r["status"] == 200 else "DIKKAT",
                "%s -> %s, %s bayt" % (re.sub(r"^https?://[^/]+", "", u), r["status"], r["bytes"]))
            if r["status"] == 200:
                all_text += "\n" + r["body"]
        except Exception as e:
            say("DIKKAT", "%s: %s" % (short(u), e))
    fn = extract_fn(all_text)
    R["bePlayerFn"] = fn
    say("OK" if fn else "DIKKAT", "bePlayer fonksiyonu %s" % ("bulundu (%d karakter)" % len(fn) if fn else "bulunamadi"))

    plain, algo = None, None
    if bp and bp["json"] and "ct" in bp["json"]:
        ctx = [("referer sitesi", host(site)), ("embed sitesi", host(embed)),
               ("embed kimligi", embed.rstrip("/").split("/")[-1]), ("film adresi", site)]
        lits = literals(fn or all_text)
        cl = candidates(bp["arg1"], ctx, lits)
        R["candidateCount"] = len(cl)
        modes = ["evp", "sha256", "md5", "pbkdf2-sha512"]
        say("3", "Parola adaylari deneniyor (%d aday x %d yontem)..." % (len(cl), len(modes)))
        t0 = time.time()
        for mode in modes:
            lim = 10 if mode == "pbkdf2-sha512" else len(cl)
            for i in range(lim):
                s = try_mode(mode, cl[i][1], bp["json"])
                if s:
                    plain, algo = s, {"mode": mode, "label": cl[i][0], "kt": cl[i][2]}
                    break
            if plain:
                break
        if plain:
            say("OK", "COZULDU: yontem=%s, parola=%s (%.1f sn)" % (algo["mode"], algo["label"], time.time() - t0))
        else:
            say("HATA", "Hicbir aday cozmedi (%.1f sn). Raporu bana gonder, fonksiyon kodundan algoritmayi cikaririm." % (time.time() - t0))
    R["algo"] = algo

    info = None
    if plain:
        try:
            info = json.loads(plain)
        except ValueError:
            info = None
    R["decrypted"] = info if info is not None else plain

    master = None
    if isinstance(info, dict) and info.get("video_location"):
        vl = info["video_location"]
        say("4", "Master playlist cekiliyor (Referer=embed, Origin=%s)" % host(embed))
        m = fetch(vl, ref=embed, origin=origin)
        R["steps"].append({"n": 3, "url": vl, "status": m["status"], "bytes": m["bytes"],
                           "referer": embed, "origin": origin})
        say("OK" if m["status"] == 200 else "HATA", "HTTP %s (%s)" % (m["status"], m["ct"]))
        if m["status"] == 200 and "#EXTM3U" in m["body"]:
            vs = resolve_variants(m["body"], vl)
            master = {"url": vl, "variants": vs}
            if vs:
                v = fetch(vs[0]["url"], ref=embed, origin=origin)
                R["steps"].append({"n": 4, "url": vs[0]["url"], "status": v["status"], "bytes": v["bytes"]})
                segs = [l for l in v["body"].splitlines() if l and not l.startswith("#")]
                master.update({"variantStatus": v["status"], "segments": len(segs),
                               "endlist": "#EXT-X-ENDLIST" in v["body"],
                               "segmentUrl": absu(segs[0], vs[0]["url"]) if segs else None})
                say("OK" if v["status"] == 200 else "DIKKAT",
                    "Varyant HTTP %s, %d segment%s" % (v["status"], len(segs), ", ENDLIST var" if master["endlist"] else ""))
    R["master"] = master

    print("\n" + "=" * 40 + " SONUC " + "=" * 40)
    print("Film sayfasi :", site)
    print("Embed        :", embed)
    print("Cozme        :", ("%s / parola: %s" % (algo["mode"], algo["label"])) if algo else "cozulemedi")
    if isinstance(info, dict):
        if info.get("title"):
            print("Baslik       :", info["title"])
        if info.get("video_location"):
            print("Master URL   :", info["video_location"])
        subs = [s for s in (info.get("strSubtitles") or []) if isinstance(s, dict) and s.get("file")]
        for s in subs:
            print("Altyazi      : %s -> %s" % (s.get("label") or s.get("language"), absu(s["file"], embed)))
        if not subs:
            print("Altyazi      : yok")
    if master:
        for v in master["variants"]:
            print("Varyant      : %s %s bps" % (v["res"], v["bw"]))
        if master.get("segmentUrl"):
            print("Ilk segment  :", master["segmentUrl"])
    if algo:
        kt = kotlin_for(algo["mode"], algo["kt"])
        R["kotlin"] = kt
        print("\n" + "=" * 36 + " KOTLIN (cozme) " + "=" * 36)
        print(kt)
    return R, None


def save(R, err):
    d = out_dir()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    paths = []
    p = os.path.join(d, "rapor_%s.json" % stamp)
    try:
        R2 = dict(R)
        if err:
            R2["error"] = err
        with open(p, "w", encoding="utf-8") as f:
            json.dump(R2, f, ensure_ascii=False, indent=1)
        paths.append(p)
        if R.get("kotlin"):
            pk = os.path.join(d, "kotlin_%s.kt" % stamp)
            with open(pk, "w", encoding="utf-8") as f:
                f.write(R["kotlin"])
            paths.append(pk)
    except Exception as e:
        print("Dosya yazilamadi:", e)
    return paths


def main():
    print("CloudStream Araci (Pydroid 3)")
    print("Film sayfasi linkini yapistir, Enter. Bos birakirsan cikar.\n")
    first = sys.argv[1] if len(sys.argv) > 1 else None
    while True:
        try:
            site = first or input("Link: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        first = None
        if not site:
            break
        if not re.match(r"https?://", site):
            print("Link http:// veya https:// ile baslamali.\n")
            continue
        err = None
        try:
            R, err = run(site)
        except Exception as e:  # beklenmeyen hata da rapora girsin
            R, err = {"site": site, "steps": []}, "%s: %s" % (type(e).__name__, e)
        if err:
            say("HATA", err)
        paths = save(R, err)
        if paths:
            print("\nKaydedildi:")
            for p in paths:
                print("  ", p)
            print("Sorun varsa rapor_*.json dosyasini Pydroid'de acip icerigini bana gonder.")
        print("\n" + "-" * 80 + "\n")


if __name__ == "__main__":
    main()
