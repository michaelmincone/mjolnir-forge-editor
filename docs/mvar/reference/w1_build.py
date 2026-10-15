#!/usr/bin/env python3
"""W1 reference fixture builder (SPEC.md appendix C). Written from the SPEC tables only; shares nothing with mvarlib.
Builds a plain 4-chunk synthetic Reach map variant (NOT game data) in two hash flavours and prints the golden numbers.
Python 3.9 compatible.  Usage: python3 -I w1_build.py [outdir]
"""
import hashlib, struct, sys, os

SALT = bytes.fromhex("EDD43009666D5C4A5C3657FAB40E022F535AC6C9EE471F01F1A44756B7714F1C36EC")


class W:                      # MSB-first bit accumulator (big-int based)
    def __init__(self):
        self.v = 0
        self.n = 0
        self.marks = []
    def u(self, value, bits):
        assert 0 <= value < (1 << bits), (value, bits)
        self.v = (self.v << bits) | value
        self.n += bits
    def mark(self, name):
        self.marks.append((name, self.n))
    def tobytes(self, total):
        assert self.n <= total * 8
        return (self.v << (total * 8 - self.n)).to_bytes(total, "big")


def f32be(x):
    return struct.unpack(">I", struct.pack(">f", x))[0]


def axis_bits(rng):
    import math
    step = 0.00833333333 / 32 * 2
    out = []
    for r in rng:
        n = min(0x800000, math.ceil(r / step))
        out.append(min(26, 0 if n <= 1 else (n - 1).bit_length()))
    return out


BOUNDS = (-240.0, 240.0, -345.0, 345.0, -70.0, 70.0)
RANGES = (BOUNDS[1] - BOUNDS[0], BOUNDS[3] - BOUNDS[2], BOUNDS[5] - BOUNDS[4])
AX = axis_bits(RANGES)                      # expect [20, 21, 19]
QUOTA_COUNT = 80
LABELS = ["SCALE", "Kill Boundary", "Spawn"]


def slot_absent(w):
    w.u(0, 1)


def slot(w, *, flags2=1, folder=None, item=None, inb=1, pos=(0, 0, 0), up_global=1, up=0, angle=8192, parent=0,
         shape=0, dims=(), seq=0, resp=0, ctype=0, label=None, place=0xCC, team=9, color=None, extra=()):
    w.u(1, 1)
    w.u(flags2, 2)
    if folder is None: w.u(1, 1)
    else: w.u(0, 1); w.u(folder, 8)
    if item is None: w.u(1, 1)
    else: w.u(0, 1); w.u(item, 5)
    w.u(inb, 1)
    for k in range(3): w.u(pos[k], AX[k])
    if up_global: w.u(1, 1)
    else: w.u(0, 1); w.u(up, 20)
    w.u(angle, 14)
    w.u(parent, 10)
    w.u(shape, 2)
    for d in dims: w.u(d, 11)
    w.u(seq & 0xFF, 8)
    w.u(resp, 8)
    w.u(ctype, 5)
    if label is None: w.u(1, 1)
    else: w.u(0, 1); w.u(label, 8)
    w.u(place, 8)
    w.u(team, 4)
    if color is None: w.u(1, 1)
    else: w.u(0, 1); w.u(color, 3)
    if ctype == 1: w.u(extra[0], 8)
    elif 12 <= ctype <= 14: w.u(extra[0], 5); w.u(extra[1], 5)
    # type 19 deliberately not used in W1


BASE_SLOTS = {
    1: dict(folder=70, item=0, pos=(1 << 19, 1 << 20, 1 << 18)),                      # Block, 1x1 (0x4600) at the box centre cell
    5: dict(folder=61, item=0, pos=(123456, 654321, 98765), shape=3, dims=(0x7FF, 1024, 0, 2046), seq=-5, label=1,
            ctype=26, place=0x0C, team=0, color=None),                                  # kill boundary box
    650: dict(folder=70, item=0, pos=(0, 0, 0), up_global=0, up=436468, angle=16383, parent=2, label=2, color=7),
}
BASE_ROWS = {61: (0, 1, 1), 70: (0, 16, 2)}      # all other quota rows are (0, 0, 0)


def build_stream(SLOTS=None, ROWS=None):
    SLOTS = BASE_SLOTS if SLOTS is None else SLOTS
    ROWS = BASE_ROWS if ROWS is None else ROWS
    w = W()
    w.mark("header")
    w.u(6, 4)                       # contentType stored = map_variant(5) + 1
    w.u(0x7329, 32)                 # fileLength 29481
    for i in (0x0123456789ABCDEF, 0x0F1E2D3C4B5A6978, 0x1122334455667788, 0):
        w.u(i, 64)
    w.u(1, 3); w.u(4, 3); w.u(1, 3)  # activity stored 1 (=0), gameMode 4 (forge), engine 1
    w.u(3006, 32)                   # mapID Forge World
    w.u(0, 8)                       # engineCategory
    for ts in (1700000000, 1700000001):
        w.u(ts, 64); w.u(0, 64); w.u(0x41, 8); w.u(0, 8); w.u(0, 1)
    for text in ("W1 minimal", "synthetic reference fixture"):
        for ch in text: w.u(ord(ch), 16)
        w.u(0, 16)
    w.mark("body_fixed")
    w.u(31, 8)                      # version
    w.u(0xFFFFFFFF, 32)             # checksum
    w.u(0xDEADBEEF, 32)             # palette CRC
    w.u(QUOTA_COUNT, 9)
    w.u(3006, 32)                   # map id copy
    w.u(0, 1); w.u(0, 1)
    for b in BOUNDS: w.u(f32be(b), 32)
    w.u(30000, 32); w.u(123, 32)    # max budget, spent budget
    w.mark("labels")
    buf = b""; offs = []
    for s in LABELS:
        offs.append(len(buf)); buf += s.encode("ascii") + b"\0"
    w.u(len(LABELS), 9)
    for o in offs: w.u(1, 1); w.u(o, 12)
    w.u(len(buf), 13); w.u(0, 1)
    for b in buf: w.u(b, 8)
    w.mark("slots")
    for i in range(651):
        w.mark("slot%d" % i) if i in SLOTS or i in (0, 2, 649) else None
        if i in SLOTS: slot(w, **SLOTS[i])
        else: slot_absent(w)
    w.mark("quotas")
    rows = [ROWS.get(i, (0, 0, 0)) for i in range(QUOTA_COUNT)]
    for r in rows:
        for b in r: w.u(b, 8)
    w.mark("end")
    return w


def build_file(flavour, SLOTS=None, ROWS=None):
    w = build_stream(SLOTS, ROWS)
    end_bits = w.n
    L = (end_bits + 7) // 8
    stream = w.tobytes(0x7000)
    if flavour == "salted_be32": digest = hashlib.sha1(SALT + struct.pack(">I", L) + stream[:L]).digest()
    elif flavour == "plain_le32": digest = hashlib.sha1(struct.pack("<I", L) + stream[:L]).digest()
    else: raise ValueError(flavour)
    mvar = struct.pack(">4sIHH", b"mvar", 0x7028, 31, 1) + digest + struct.pack(">I", L) + stream + bytes(4)
    assert len(mvar) == 0x7028
    blf = struct.pack(">4sIHH", b"_blf", 0x30, 1, 2) + struct.pack(">H", 0xFFFE) + bytes(0x20) + struct.pack(">H", 0)
    assert len(blf) == 0x30
    chdr = bytearray(struct.pack(">4sIHH", b"chdr", 0x2C0, 10, 2))
    chdr += struct.pack("<HH", 0, 0xFFFF) + struct.pack("<b", 5) + bytes(3) + struct.pack("<I", 0x7329)
    for i in (0x0123456789ABCDEF, 0x0F1E2D3C4B5A6978, 0x1122334455667788, 0): chdr += struct.pack("<Q", i)
    chdr += struct.pack("<bBB", 0, 4, 1) + bytes(1) + struct.pack("<I", 3006) + struct.pack("<I", 0) + bytes(4)
    for ts in (1700000000, 1700000001):
        chdr += struct.pack("<QQ", ts, 0) + b"A".ljust(16, b"\0") + bytes([0]) + bytes(3)
    for text in ("W1 minimal", "synthetic reference fixture"):
        chdr += (text.encode("utf-16-le") + b"\0\0").ljust(256, b"\0")
    chdr += struct.pack("<I", 0) + bytes(0x1C) + bytes(4) + struct.pack("<I", 0) + bytes(8)
    # campaign block: id u8, difficulty u8, metagame u8, rally u8, unk u32 -> 8 bytes ; then unk2A8 8 bytes
    assert len(chdr) == 0x2C0, hex(len(chdr))
    eof = struct.pack(">4sIHH", b"_eof", 0x11, 1, 1) + struct.pack(">I", 0x30 + 0x2C0 + 0x7028) + b"\0"
    data = bytes(blf) + bytes(chdr) + mvar + eof
    assert len(data) == 29481
    return data, w, L, digest


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    print("axis bits:", AX, "ranges:", RANGES)
    for fl in ("salted_be32", "plain_le32"):
        data, w, L, digest = build_file(fl)
        print("== flavour", fl)
        print("  file bytes:", len(data), " sha256:", hashlib.sha256(data).hexdigest())
        print("  stream end bit:", w.n, " L = ceil(end/8):", L, " stored hash:", digest.hex())
        if fl == "salted_be32":
            marks = dict()
            for name, pos in w.marks: marks[name] = pos
            print("  section start bits:", {k: v for k, v in marks.items() if k in ("header", "body_fixed", "labels", "slots", "quotas", "end")})
            print("  slot starts:", {k: v for k, v in marks.items() if k.startswith("slot")})
        if fl == "salted_be32":
            import copy
            E1 = copy.deepcopy(BASE_SLOTS); E1[1]["pos"] = (526473, 1 << 20, 1 << 18)             # move slot 1 by +1.0 wu in x
            E2 = copy.deepcopy(BASE_SLOTS); E2[0] = dict(folder=70, item=0, pos=(1, 2, 3))         # add a block into the lowest free slot (0)
            R2 = dict(BASE_ROWS); R2[70] = (0, 16, 3)
            E3 = copy.deepcopy(BASE_SLOTS); del E3[5]                                              # delete slot 5 (the kill boundary)
            R3 = dict(BASE_ROWS); R3[61] = (0, 1, 0)
            for name, s, r in (("E1_move_slot1_dx+1.0", E1, None), ("E2_add_block_in_slot0", E2, R2), ("E3_delete_slot5", E3, R3)):
                d2, w2, L2, dg2 = build_file(fl, s, r)
                print("  edit", name, ": end bit", w2.n, " L", L2, " hash", dg2.hex(), " file sha256", hashlib.sha256(d2).hexdigest())
                if out:
                    open(os.path.join(out, "w1_%s_%s.bin_mvar" % (fl, name.split("_")[0])), "wb").write(d2)
        if out:
            os.makedirs(out, exist_ok=True)
            open(os.path.join(out, "w1_%s.bin_mvar" % fl), "wb").write(data)
