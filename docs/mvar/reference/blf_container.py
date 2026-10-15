#!/usr/bin/env python3
"""Reach BLF container: parser, writer (mirrors ReachVariantTool), and a read-only verifier.

stdlib only. Spec + evidence levels: container-and-bit-conventions.md (same directory).

  python3 -I blf_container.py --selftest            # rebuild every real game-variant file byte-exactly
  python3 -I blf_container.py verify FILE [FILE...] # read-only integrity report for a .bin / .mvar

Everything here that is tagged V is VERIFIED-ON-REAL-FILES (5 distinct Reach game variants).
Everything tagged I is INFERRED (no real map variant was available): see the report.
"""
import glob
import hashlib
import importlib.util
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bitio_prototype", os.path.join(HERE, "bitio_prototype.py"))
bitio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bitio)

# ---------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------
# V: 34-byte salt, RVT formats/sha1.h:4-14; recomputed hashes match all 5 real files.
SALT = bytes([
    0xED, 0xD4, 0x30, 0x09, 0x66, 0x6D, 0x5C, 0x4A, 0x5C, 0x36, 0x57, 0xFA,
    0xB4, 0x0E, 0x02, 0x2F, 0x53, 0x5A, 0xC6, 0xC9, 0xEE, 0x47, 0x1F, 0x01,
    0xF1, 0xA4, 0x47, 0x56, 0xB7, 0x71, 0x4F, 0x1C, 0x36, 0xEC,
])
BLF_SIZE = 0x30      # V
CHDR_SIZE = 0x2C0    # V
EOF_SIZE = 0x11      # V
PREFIX = 0x28        # V (mpvr): block header 0xC + sha1 0x14 + unused 4 + hashable_len 4
MPVR_SIZE = 0x5028   # V
MVAR_SIZE = 0x7028   # I: UPSTREAM-CODE (RVT html/src/raw/map_variant_mvar.js:693), not verified on a real file
FILE_TYPES = {-1: "none", 0: "dlc", 1: "campaign_save", 2: "screenshot", 3: "film", 4: "film_clip",
              5: "map_variant", 6: "game_variant", 7: "playlist"}


def pack_header(sig, size, version, flags):
    return struct.pack(">4sIHH", sig.encode("latin-1"), size, version, flags)


def sha1_reach(hashable, salt=SALT):
    """V: SHA-1( salt34 || BE32(len) || hashable )  -- RVT base.cpp:260-274."""
    return hashlib.sha1(salt + struct.pack(">I", len(hashable)) + bytes(hashable)).digest()


def set_bits(buf, bitpos, nbits, value):
    """Masked MSB-first overwrite inside a bytearray (does NOT clobber neighbouring bits)."""
    for i in range(nbits):
        bit = (value >> (nbits - 1 - i)) & 1
        p = bitpos + i
        mask = 0x80 >> (p % 8)
        if bit:
            buf[p // 8] |= mask
        else:
            buf[p // 8] &= ~mask & 0xFF


def get_bits(buf, bitpos, nbits):
    r = bitio.BitReader(buf)
    r.set_bitpos(bitpos)
    return r.read(nbits)


# ---------------------------------------------------------------------------------------------
# Block walk (V)
# ---------------------------------------------------------------------------------------------
def walk_blocks(data):
    out, pos = [], 0
    while pos + 12 <= len(data):
        sig, size, ver, flags = struct.unpack_from(">4sIHH", data, pos)
        out.append(dict(sig=sig.decode("latin-1"), pos=pos, size=size, version=ver, flags=flags))
        if size < 12:  # RVT block.cpp:148 treats size < 0xC as a bad block
            break
        pos += size
    return out


# ---------------------------------------------------------------------------------------------
# chdr (V): byte-aligned, numeric fields LITTLE-endian, strings UTF-16LE fixed 128 units
# ---------------------------------------------------------------------------------------------
AUTHOR_OFFS = {"created": 0x48, "modified": 0x6C}


def parse_chdr(blk):
    """blk = the 0x2C0 bytes of the chdr block (header included)."""
    u = lambda f, o: struct.unpack_from(f, blk, o)[0]
    d = dict(
        build_major=u("<H", 0x0C), build_minor=u("<H", 0x0E),
        content_type=u("<b", 0x10), file_length=u("<I", 0x14),
        unk08=u("<Q", 0x18), unk10=u("<Q", 0x20), unk18=u("<Q", 0x28), unk20=u("<Q", 0x30),
        activity=u("<b", 0x38), game_mode=u("<B", 0x39), engine=u("<B", 0x3A),
        map_id=u("<I", 0x3C), engine_category=u("<I", 0x40),
        title_raw=bytes(blk[0x90:0x190]), description_raw=bytes(blk[0x190:0x290]),
        engine_icon=u("<I", 0x290), unk284=bytes(blk[0x294:0x2B0]),
        campaign_id=u("<B", 0x2B0), campaign_difficulty=u("<B", 0x2B1),
        campaign_metagame=u("<B", 0x2B2), campaign_rally=u("<B", 0x2B3), unk2a4=u("<I", 0x2B4),
        unk2a8=bytes(blk[0x2B8:0x2C0]),
        pads=bytes(blk[0x11:0x14]) + bytes(blk[0x3B:0x3C]) + bytes(blk[0x44:0x48]),
    )
    for who, o in AUTHOR_OFFS.items():
        d[who] = dict(timestamp=u("<Q", o), xuid=u("<Q", o + 8), author=bytes(blk[o + 16:o + 32]),
                      is_online_id=u("<B", o + 32), pad=bytes(blk[o + 33:o + 36]))
    d["title"] = d["title_raw"].decode("utf-16-le").split("\x00")[0]
    d["description"] = d["description_raw"].decode("utf-16-le").split("\x00")[0]
    return d


def build_chdr(d, version=0x000A, flags=0x0002):
    """V: byte-exact inverse of parse_chdr (RVT ReachUGCHeader::write(bytewriter&), ugc_header.cpp:122-152)."""
    b = bytearray(CHDR_SIZE)
    b[0:12] = pack_header("chdr", CHDR_SIZE, version, flags)
    pk = lambda f, o, v: struct.pack_into(f, b, o, v)
    pk("<H", 0x0C, d["build_major"]); pk("<H", 0x0E, d["build_minor"])
    pk("<b", 0x10, d["content_type"]); pk("<I", 0x14, d["file_length"])
    for n, o in (("unk08", 0x18), ("unk10", 0x20), ("unk18", 0x28), ("unk20", 0x30)):
        pk("<Q", o, d[n])
    pk("<b", 0x38, d["activity"]); pk("<B", 0x39, d["game_mode"]); pk("<B", 0x3A, d["engine"])
    pk("<I", 0x3C, d["map_id"]); pk("<I", 0x40, d["engine_category"])
    for who, o in AUTHOR_OFFS.items():
        a = d[who]
        pk("<Q", o, a["timestamp"]); pk("<Q", o + 8, a["xuid"])
        b[o + 16:o + 32] = a["author"].ljust(16, b"\x00")[:16]
        pk("<B", o + 32, a["is_online_id"])
    b[0x90:0x190] = d["title_raw"]; b[0x190:0x290] = d["description_raw"]
    pk("<I", 0x290, d["engine_icon"]); b[0x294:0x2B0] = d["unk284"]
    pk("<B", 0x2B0, d["campaign_id"]); pk("<B", 0x2B1, d["campaign_difficulty"])
    pk("<B", 0x2B2, d["campaign_metagame"]); pk("<B", 0x2B3, d["campaign_rally"]); pk("<I", 0x2B4, d["unk2a4"])
    b[0x2B8:0x2C0] = d["unk2a8"]
    return bytes(b)


def utf16le_fixed(s, units=128):
    raw = s.encode("utf-16-le")[: (units - 1) * 2]
    return raw.ljust(units * 2, b"\x00")


# ---------------------------------------------------------------------------------------------
# Writer (mirrors RVT GameVariant::write, base.cpp:438-465, plus the fixups at 153-157 and 243-278)
# ---------------------------------------------------------------------------------------------
def build_blf_block(version=1, flags=2):
    """V. _blf = header + BE16 0xFFFE + 0x20 zero bytes + BE16 0 (0x30 bytes)."""
    return pack_header("_blf", BLF_SIZE, version, flags) + struct.pack(">H", 0xFFFE) + bytes(0x20) + struct.pack(">H", 0)


def build_file(chdr_dict, hashable, payload_sig="mpvr", payload_size=MPVR_SIZE, payload_version=0x36,
               payload_flags=0x0001, embedded_filelength_bitoff=72, length_field_endian="<", prefix=PREFIX):
    """Assemble a complete file.

    hashable   : the bit-stream bytes exactly as a BitWriter produced them (ceil(bits/8) bytes), with ANY placeholder in
                 the embedded fileLength (it is overwritten here).
    embedded_filelength_bitoff : bit offset of the 32-bit fileLength copy inside the payload
                 (mpvr: 4 + 32 + 32 + 4 = 72; mvar: INFERRED 4 -- the UGC header is the first thing in the stream).
    length_field_endian : '<' for multiplayer/forge mpvr (V), '>' for firefight (UPSTREAM-CODE firefight.h:51).
    prefix     : 0x28 = header 0xC + sha1 0x14 + 4 unused + 4 length (V for mpvr);
                 0x24 = header + sha1 + 4 length (what RVT's mvar JS prototype implies; UNVERIFIED hypothesis H-B).
    """
    d = dict(chdr_dict)
    d["file_length"] = 0
    blf = build_blf_block()
    chdr = bytearray(build_chdr(d))
    body = bytearray(payload_size - prefix)
    if len(hashable) > len(body):
        raise ValueError("payload %d bytes does not fit in the fixed %d-byte block body" % (len(hashable), len(body)))
    body[:len(hashable)] = hashable
    pblock = bytearray(pack_header(payload_sig, payload_size, payload_version, payload_flags))
    pblock += bytes(0x14) + (bytes(4) if prefix == 0x28 else b"") + bytes(4) + body
    eof_pos = len(blf) + len(chdr) + len(pblock)
    eof = pack_header("_eof", EOF_SIZE, 1, 1) + struct.pack(">I", eof_pos) + b"\x00"   # V: BE32 = offset of the _eof block
    f = bytearray(blf + chdr + pblock + eof)
    file_len = len(f)                                                                    # V: includes the _eof block
    struct.pack_into("<I", f, BLF_SIZE + 0x14, file_len)                                 # V: chdr.fileLength, little-endian
    p0 = BLF_SIZE + CHDR_SIZE                                                            # start of payload block
    payload_start = p0 + prefix
    set_bits(f, payload_start * 8 + embedded_filelength_bitoff, 32, file_len)            # V: embedded copy, big-endian bits
    hashable_len = len(hashable)
    struct.pack_into(length_field_endian + "I", f, p0 + prefix - 4, hashable_len)        # V: hashable length field (mpvr: +0x24)
    digest = sha1_reach(f[payload_start:payload_start + hashable_len])                   # V
    f[p0 + 0x0C:p0 + 0x20] = digest
    return bytes(f)


# ---------------------------------------------------------------------------------------------
# Verify (read only)
# ---------------------------------------------------------------------------------------------
def hash_candidates(data, p0):
    """Try several recipes for the payload block at p0 and report which reproduces the stored hash."""
    stored = bytes(data[p0 + 0x0C:p0 + 0x20])
    size = struct.unpack_from(">I", data, p0 + 4)[0]
    end = p0 + size
    hits = []
    len_sources = {
        "u32le@+0x24": struct.unpack_from("<I", data, p0 + 0x24)[0],
        "u32be@+0x24": struct.unpack_from(">I", data, p0 + 0x24)[0],
        "u32le@+0x20": struct.unpack_from("<I", data, p0 + 0x20)[0],
        "u32be@+0x20": struct.unpack_from(">I", data, p0 + 0x20)[0],
    }
    for start in (0x24, 0x28):
        body_max = end - (p0 + start)
        lasts = [i for i in range(body_max) if data[p0 + start + i]]
        if lasts:
            len_sources["last-nonzero+1 (start=0x%X)" % start] = lasts[-1] + 1
        for lname, ln in len_sources.items():
            if not (0 < ln <= body_max):
                continue
            hashable = data[p0 + start:p0 + start + ln]
            for rname, buf in (
                ("salt|BE32(len)|data", SALT + struct.pack(">I", ln) + hashable),
                ("salt|LE32(len)|data", SALT + struct.pack("<I", ln) + hashable),
                ("salt|data", SALT + hashable),
                ("BE32(len)|data", struct.pack(">I", ln) + hashable),
                ("data", bytes(hashable)),
            ):
                if hashlib.sha1(buf).digest() == stored:
                    hits.append((start, lname, ln, rname))
    return stored, hits


def verify(path, out=print):
    data = open(path, "rb").read()
    out("FILE %s  (%d bytes)" % (path, len(data)))
    blocks = walk_blocks(data)
    for b in blocks:
        out("  block %-4s pos=0x%X size=0x%X version=0x%X flags=0x%X" % (b["sig"], b["pos"], b["size"], b["version"], b["flags"]))
    tiled = sum(b["size"] for b in blocks) == len(data)
    out("  blocks tile the file exactly: %s" % tiled)
    sigs = [b["sig"] for b in blocks]
    ok = True
    if not sigs or sigs[0] != "_blf":
        out("  !! first block is not _blf"); return False
    by = {b["sig"]: b for b in blocks}
    blf = by["_blf"]
    out("  _blf: BOM(be16@0x0C)=0x%04X size=0x%X" % (struct.unpack_from(">H", data, blf["pos"] + 0x0C)[0], blf["size"]))
    if "chdr" in by:
        c = by["chdr"]
        d = parse_chdr(data[c["pos"]:c["pos"] + c["size"]]) if c["size"] == CHDR_SIZE else None
        if d:
            out("  chdr: contentType=%d (%s) fileLength=%d (actual %d, match=%s) title=%r" % (
                d["content_type"], FILE_TYPES.get(d["content_type"], "?"), d["file_length"], len(data),
                d["file_length"] == len(data), d["title"]))
            out("        build=%d.%d activity=%d gameMode=%d engine=%d mapID=0x%08X engineCategory=%d" % (
                d["build_major"], d["build_minor"], d["activity"], d["game_mode"], d["engine"], d["map_id"], d["engine_category"]))
        else:
            out("  chdr: unexpected size 0x%X" % c["size"])
    else:
        out("  (no chdr block)")
    for sig in ("mpvr", "mvar", "gvar"):
        if sig in by:
            p = by[sig]
            out("  payload block %s: size=0x%X version=0x%X flags=0x%X" % (sig, p["size"], p["version"], p["flags"]))
            if sig != "gvar":
                stored, hits = hash_candidates(data, p["pos"])
                out("    stored sha1 = %s" % stored.hex())
                if hits:
                    for h in hits:
                        out("    HASH MATCH: header_start=+0x%X length_from=%s len=0x%X recipe=%s" % h)
                else:
                    out("    no hash recipe matched (salt/endianness/start unknown for this block type)")
                # embedded UGC header probe: with and without the mpvr type/encoding/engine prefix, at +0x24 and +0x28
                for start in (0x28, 0x24):
                    base = (p["pos"] + start) * 8
                    for prefix, label in ((0, "no engine prefix (mvar style)"), (68, "type+encVer+engVer prefix (mpvr style)")):
                        ct = get_bits(data, base + prefix, 4)
                        fl = get_bits(data, base + prefix + 4, 32)
                        if ct - 1 in FILE_TYPES and fl == len(data):
                            out("    embedded header probe: start=+0x%X, %s -> contentType stored=%d (%s), fileLength=%d == actual" % (
                                start, label, ct, FILE_TYPES.get(ct - 1), fl))
    if "_eof" in by:
        e = by["_eof"]
        be = struct.unpack_from(">I", data, e["pos"] + 0xC)[0]
        le = struct.unpack_from("<I", data, e["pos"] + 0xC)[0]
        out("  _eof: size=0x%X u32be=0x%X u32le=0x%X ; eof block starts at 0x%X ; file length 0x%X ; trailing byte=0x%02X" % (
            e["size"], be, le, e["pos"], len(data), data[e["pos"] + 0x10] if e["pos"] + 0x10 < len(data) else -1))
        out("        be32 == eof block start: %s ; be32 == file length: %s" % (be == e["pos"], be == len(data)))
    else:
        out("  (no _eof block)")
    return ok


# ---------------------------------------------------------------------------------------------
# Self test: regenerate every real game variant byte-exactly from its parsed parts
# ---------------------------------------------------------------------------------------------
ROOT = os.path.expanduser("~/Local_Documents")


def selftest():
    seen, n = set(), 0
    for pat in (ROOT + "/rvt-test-samples/*.bin", ROOT + "/ReachVariantTool-core-library/macos/Fixtures/*.bin"):
        for p in sorted(glob.glob(pat)):
            data = open(p, "rb").read()
            md5 = hashlib.md5(data).hexdigest()
            if md5 in seen:
                continue
            seen.add(md5)
            blocks = {b["sig"]: b for b in walk_blocks(data)}
            c, m = blocks["chdr"], blocks["mpvr"]
            chdr = parse_chdr(data[c["pos"]:c["pos"] + c["size"]])
            # chdr builder must be byte-exact on its own
            assert build_chdr(chdr, c["version"], c["flags"]) == data[c["pos"]:c["pos"] + c["size"]], "chdr rebuild differs"
            hlen = struct.unpack_from("<I", data, m["pos"] + 0x24)[0]
            hashable = bytearray(data[m["pos"] + PREFIX:m["pos"] + PREFIX + hlen])
            set_bits(hashable, 72, 32, 0xDEADBEEF)          # scribble a placeholder: the writer must overwrite it
            rebuilt = build_file(chdr, bytes(hashable), "mpvr", m["size"], m["version"], m["flags"], 72, "<")
            assert rebuilt == data, "rebuilt file differs from original: %s" % p
            n += 1
            print("OK byte-exact rebuild: %-40s (%d bytes, hashable 0x%X)" % (os.path.basename(p), len(data), hlen))
    # tamper detection: flipping one payload bit must break the stored hash; fixing it must restore it
    p = sorted(glob.glob(ROOT + "/rvt-test-samples/*.bin"))[0]
    data = bytearray(open(p, "rb").read())
    m = {b["sig"]: b for b in walk_blocks(data)}["mpvr"]
    stored, hits = hash_candidates(bytes(data), m["pos"])
    assert any(h[1] == "u32le@+0x24" and h[3] == "salt|BE32(len)|data" and h[0] == 0x28 for h in hits)
    data[m["pos"] + 0x40] ^= 1
    stored2, hits2 = hash_candidates(bytes(data), m["pos"])
    assert not any(h[1] == "u32le@+0x24" for h in hits2), "tampered file should not match any recipe"
    print("OK tamper test: 1-bit change makes every hash recipe fail (so the hash really covers the payload)")
    print("ALL %d FILES REBUILT BYTE-EXACTLY" % n)
    # Synthetic (NOT game data) mvar-shaped files: proves the verifier can discover which layout a real .mvar uses.
    w = bitio.BitWriter()
    w.write(6 + 1, 4); w.write(0, 32)                       # contentType stored = map_variant(5)+1, fileLength placeholder
    for _ in range(4):
        w.write(0x1122334455667788, 64)
    w.write(4 + 1, 3); w.write(4, 3); w.write(1, 3); w.write(0xFFFFFFFF, 32); w.write(1, 8)
    for _ in range(2):
        w.write(0, 64); w.write(0, 64)
        w.write(0xA6, 8); w.write(0, 8); w.write(1, 1)
    w.write_u16string([ord(c) for c in "Synthetic"] + [0], 128); w.write_u16string([0], 128)
    synth = dict(chdr)
    synth.update(content_type=5)
    for label, pre, bitoff in (("H-A prefix 0x28", 0x28, 4), ("H-B prefix 0x24", 0x24, 4)):
        fbytes = build_file(synth, w.getvalue(), "mvar", MVAR_SIZE, 0x36, 1, bitoff, "<", pre)
        tmp = os.path.join(HERE, "_synthetic_tmp.mvar")
        open(tmp, "wb").write(fbytes)
        lines = []
        verify(tmp, out=lines.append)
        os.remove(tmp)
        joined = "\n".join(lines)
        assert "HASH MATCH: header_start=+0x%X" % pre in joined, label
        assert "embedded header probe: start=+0x%X, no engine prefix" % pre in joined, label
        print("OK synthetic mvar-shaped file (%s): verifier locates header start and hash" % label)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--selftest"]:
        selftest()
    elif args[:1] == ["verify"] and len(args) > 1:
        for a in args[1:]:
            verify(a)
            print()
    else:
        print(__doc__)
