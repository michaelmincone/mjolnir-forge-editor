#!/usr/bin/env python3
"""W1 reference walker (SPEC.md appendix C): parses a plain 4-chunk map variant per the SPEC tables using a deliberately
different bit reader (string of '0'/'1') than w1_build.py.  Python 3.9 compatible.
Usage: python3 -I w1_parse.py FILE [--type19 flag8|plain8]"""
import hashlib, math, struct, sys

SALT = bytes.fromhex("EDD43009666D5C4A5C3657FAB40E022F535AC6C9EE471F01F1A44756B7714F1C36EC")


class R:
    def __init__(self, data):
        self.s = "".join(format(b, "08b") for b in data)
        self.p = 0
    def u(self, n):
        v = int(self.s[self.p:self.p + n] or "0", 2) if n else 0
        self.p += n
        return v


def axis_bits(rng):
    step = 0.00833333333 / 32 * 2
    out = []
    for r in rng:
        n = min(0x800000, math.ceil(r / step))
        out.append(min(26, 0 if n <= 1 else (n - 1).bit_length()))
    return out


def main(path, type19="flag8"):
    d = open(path, "rb").read()
    pos, chunks = 0, []
    while pos < len(d):
        sig, size, ver, fl = struct.unpack_from(">4sIHH", d, pos)
        chunks.append((sig.decode(), pos, size, ver, fl)); pos += size
    print("chunks:", [(c[0], hex(c[1]), hex(c[2]), c[3], c[4]) for c in chunks], "total", len(d))
    m = [c for c in chunks if c[0] == "mvar"][0]
    base = m[1]
    stored_hash = d[base + 12:base + 32]
    L = struct.unpack_from(">I", d, base + 32)[0]
    stream = d[base + 36:base + 36 + 0x7000]
    assert d[base + 36 + 0x7000:base + 0x7028] == bytes(4)
    cands = {
        "salted_be32": hashlib.sha1(SALT + struct.pack(">I", L) + stream[:L]).digest(),
        "plain_le32": hashlib.sha1(struct.pack("<I", L) + stream[:L]).digest(),
    }
    print("L =", L, " hash flavour:", [k for k, v in cands.items() if v == stored_hash])
    r = R(stream)
    ct = r.u(4); fl32 = r.u(32); ids = [r.u(64) for _ in range(4)]
    act = r.u(3); gm = r.u(3); eng = r.u(3); mid = r.u(32); cat = r.u(8)
    def author():
        ts, xuid = r.u(64), r.u(64); name = []
        while True:
            c = r.u(8); name.append(c)
            if c == 0 or len(name) == 16: break
        return ts, xuid, bytes(name), r.u(1)
    a1, a2 = author(), author()
    def ustr():
        s = []
        while True:
            c = r.u(16); s.append(c)
            if c == 0 or len(s) == 128: break
        return "".join(chr(c) for c in s if c)
    title, desc = ustr(), ustr()
    if act - 1 == 2: r.u(16)
    if gm == 1: r.u(52)
    elif gm == 2: r.u(34)
    print("header: contentType raw", ct, "fileLength", fl32, "act raw", act, "gm", gm, "eng", eng, "map", mid, "title", repr(title), "desc", repr(desc), "end bit", r.p)
    h_end = r.p
    ver = r.u(8); chk = r.u(32); crc = r.u(32); nq = r.u(9); mid2 = r.u(32); bi = r.u(1); bx = r.u(1)
    b = [struct.unpack(">f", struct.pack(">I", r.u(32)))[0] for _ in range(6)]
    mb, sb = r.u(32), r.u(32)
    print("body: version", ver, "checksum", hex(chk), "crc", hex(crc), "quota_count", nq, "map2", mid2, "bounds", b, "budget", mb, sb, "labels start bit", r.p)
    cnt = r.u(9); offs = []
    for _ in range(cnt):
        offs.append(r.u(12) if r.u(1) else None)
    labels = []
    if cnt:
        dl = r.u(13); comp = r.u(1)
        assert not comp
        buf = bytes(r.u(8) for _ in range(dl))
        for o in offs:
            labels.append(buf[o:buf.index(0, o)].decode("ascii") if o is not None else "")
    print("labels:", labels, " slots start bit", r.p)
    ax = axis_bits([b[1] - b[0], b[3] - b[2], b[5] - b[4]])
    print("axis bits", ax)
    present = []
    for i in range(651):
        if not r.u(1): continue
        o = {"slot": i, "flags2": r.u(2)}
        o["folder"] = None if r.u(1) else r.u(8)
        o["item"] = None if r.u(1) else r.u(5)
        inb = r.u(1); assert inb == 1, "out-of-bounds record"
        o["pos"] = [r.u(ax[k]) for k in range(3)]
        if r.u(1): o["up"] = "global"
        else: o["up"] = r.u(20)
        o["angle"] = r.u(14); o["parent"] = r.u(10)
        o["shape"] = r.u(2); o["dims"] = [r.u(11) for _ in range([0, 1, 3, 4][o["shape"]])]
        o["seq"] = r.u(8); o["resp"] = r.u(8); o["ctype"] = r.u(5)
        o["label"] = None if r.u(1) else r.u(8)
        o["place"] = r.u(8); o["team"] = r.u(4); o["color"] = None if r.u(1) else r.u(3)
        t = o["ctype"]
        if t == 1: o["extra"] = [r.u(8)]
        elif 12 <= t <= 14: o["extra"] = [r.u(5), r.u(5)]
        elif t == 19:
            if type19 == "flag8": o["extra"] = [None if r.u(1) else r.u(8)]
            else: o["extra"] = [r.u(8)]
        present.append(o)
    print("slots end bit", r.p, "present:", len(present))
    for o in present: print("  ", o)
    quotas = [(r.u(8), r.u(8), r.u(8)) for _ in range(nq)]
    end = r.p
    print("quota end bit", end, " ceil(end/8) =", (end + 7) // 8, "== L:", (end + 7) // 8 == L, " non-zero quota rows:", [(i, q) for i, q in enumerate(quotas) if any(q)])
    rest = r.s[end:]
    print("tail all zero:", set(rest) <= {"0"})


if __name__ == "__main__":
    t19 = "flag8"
    if "--type19" in sys.argv: t19 = sys.argv[sys.argv.index("--type19") + 1]
    main(sys.argv[1], t19)
