#!/usr/bin/env python3
"""MSB-first BitReader / BitWriter for Halo: Reach BLF payloads ('mpvr', and presumably 'mvar').

Conventions (all VERIFIED-ON-REAL-FILES, see container-and-bit-conventions.md):
  * Bit 0 of the stream is the MOST significant bit of byte 0.
  * A field of N bits is read MSB-first, i.e. the first bit read is the most significant
    bit of the value (so a 32-bit field is a big-endian u32, even when not byte aligned).
  * Reading past the end yields zero bits and increments `overflow` (like RVT's bitreader).
  * The writer zero-fills; a partial final byte is padded with 0 bits in its low bits.

This mirrors ReachVariantTool helpers/bitreader.h (read_bits) and helpers/bitwriter.cpp (_write).

Run directly (python3 -I bitio_prototype.py) to execute the self test, which proves a
bit-exact round trip of every real file's mpvr payload under seeded random width schedules.
"""
import glob
import hashlib
import os
import random
import struct
import sys


class BitReader:
    """Reads MSB-first from a bytes-like object. Position is in bits."""

    def __init__(self, data, bit_length=None):
        self.data = bytes(data)
        self.bit_length = len(self.data) * 8 if bit_length is None else bit_length
        self.pos = 0          # bit position
        self.overflow = 0     # bits requested beyond the end

    # --- position helpers (names mirror RVT) --------------------------------
    def bitpos(self):
        return self.pos

    def bytepos(self):
        return self.pos // 8

    def bitshift(self):
        return self.pos % 8

    def bytespan(self):
        """Bytes touched so far = ceil(pos/8)  (RVT get_bytespan)."""
        return (self.pos + 7) // 8

    def is_byte_aligned(self):
        return self.pos % 8 == 0

    def set_bitpos(self, bitpos):
        self.pos = bitpos
        self.overflow = max(0, bitpos - self.bit_length)

    def skip(self, nbits):
        self.pos += nbits
        if self.pos > self.bit_length:
            self.overflow = self.pos - self.bit_length

    # --- core ---------------------------------------------------------------
    def read(self, nbits):
        """Unsigned value of the next nbits (0..any), MSB first."""
        if nbits == 0:
            return 0
        start = self.pos
        end = start + nbits
        value = 0
        # Fast path: whole range inside the data.
        if end <= self.bit_length:
            b0 = start // 8
            b1 = (end + 7) // 8
            chunk = int.from_bytes(self.data[b0:b1], "big")
            total_bits = (b1 - b0) * 8
            drop_right = total_bits - ((start - b0 * 8) + nbits)
            value = (chunk >> drop_right) & ((1 << nbits) - 1)
        else:
            # Slow path: bits beyond the end read as 0 (RVT: out = 0, overflow += bitcount).
            for i in range(nbits):
                p = start + i
                bit = 0
                if p < self.bit_length:
                    bit = (self.data[p // 8] >> (7 - (p % 8))) & 1
                else:
                    self.overflow += 1
                value = (value << 1) | bit
        self.pos = end
        return value

    def read_signed(self, nbits):
        """Two's complement sign extension (RVT cobb::apply_sign_bit)."""
        v = self.read(nbits)
        if nbits and (v >> (nbits - 1)) & 1:
            v -= 1 << nbits
        return v

    def read_bool(self):
        return self.read(1) == 1

    def read_offset(self, nbits, offset=1):
        """RVT bitnumber<..., offset=true>: stored value = real value + 1."""
        return self.read(nbits) - offset

    def read_u16string(self, maxlen):
        """RVT read_u16string: 16-bit units read MSB-first (=> UTF-16BE), stops after the NUL unit."""
        out = []
        for _ in range(maxlen):
            c = self.read(16)
            out.append(c)
            if c == 0:
                break
        return out

    def read_cstring(self, maxlen):
        out = bytearray()
        for _ in range(maxlen):
            c = self.read(8)
            out.append(c)
            if c == 0:
                break
        return bytes(out)


class BitWriter:
    """Writes MSB-first into a growable buffer."""

    def __init__(self):
        self.buf = bytearray()
        self.pos = 0  # bit position

    def bitpos(self):
        return self.pos

    def bytespan(self):
        return (self.pos + 7) // 8

    def _ensure(self, nbits):
        need = (self.pos + nbits + 7) // 8
        if len(self.buf) < need:
            self.buf.extend(b"\x00" * (need - len(self.buf)))

    def write(self, value, nbits):
        """Write the low nbits of value (masked, so negative ints become two's complement)."""
        if nbits == 0:
            return
        value &= (1 << nbits) - 1
        self._ensure(nbits)
        start = self.pos
        b0 = start // 8
        end = start + nbits
        b1 = (end + 7) // 8
        total_bits = (b1 - b0) * 8
        lead = start - b0 * 8
        trail = total_bits - lead - nbits
        existing = int.from_bytes(self.buf[b0:b1], "big")
        # clear the target window, then or the value in (overwrite semantics, like RVT's masked write)
        mask = ((1 << nbits) - 1) << trail
        existing = (existing & ~mask) | (value << trail)
        self.buf[b0:b1] = existing.to_bytes(b1 - b0, "big")
        self.pos = end

    def write_bool(self, b):
        self.write(1 if b else 0, 1)

    def write_offset(self, value, nbits, offset=1):
        self.write(value + offset, nbits)

    def write_u16string(self, units, maxlen):
        """units: iterable of ints; stops after writing a NUL unit (RVT write_u16string)."""
        for i, u in enumerate(units):
            if i >= maxlen:
                break
            self.write(u, 16)
            if u == 0:
                break

    def write_to_bitpos(self, bitpos, nbits, value):
        """Overwrite nbits at an absolute bit position without moving the cursor (RVT write_to_bitpos)."""
        save = self.pos
        self.pos = bitpos
        self.write(value, nbits)
        self.pos = save

    def getvalue(self, total_bytes=None):
        """Bytes written so far; optionally zero-padded (never truncated) to total_bytes."""
        out = bytes(self.buf[:self.bytespan()])
        if total_bytes is not None:
            if len(out) > total_bytes:
                raise ValueError("written data longer than requested size")
            out = out + b"\x00" * (total_bytes - len(out))
        return out


# --------------------------------------------------------------------------
# Independent oracle: a line-by-line port of RVT's byte-oriented algorithms so the
# prototype is tied to the C++ semantics, not only to a big-int definition.
# --------------------------------------------------------------------------
class RvtPortReader:
    """Port of cobb::bitreader::_consume_byte / read_bits (bitreader.h:17-95)."""

    def __init__(self, data):
        self.buffer = data
        self.length = len(data)
        self.offset = 0

    def _consume_byte(self, bitcount):
        bytepos = self.offset // 8
        if bytepos >= self.length:
            return 0, bitcount  # out=0, consumed unchanged in RVT (we return bitcount to keep loop finite)
        shift = self.offset % 8
        byte = self.buffer[bytepos] & (0xFF >> shift)
        bits_read = 8 - shift
        if bitcount < bits_read:
            byte >>= (bits_read - bitcount)
            self.offset += bitcount
            consumed = bitcount
        else:
            self.offset += bits_read
            consumed = bits_read
        return byte, consumed

    def read_bits(self, bitcount):
        bits, consumed = self._consume_byte(bitcount)
        result = bits
        remaining = bitcount - consumed
        while remaining:
            bits, consumed = self._consume_byte(remaining)
            result = (result << consumed) | bits
            remaining -= consumed
        return result


class RvtPortWriter:
    """Port of cobb::bitwriter::_write (bitwriter.cpp:77-106). Buffer pre-sized and zeroed."""

    def __init__(self, nbytes):
        self.buf = bytearray(nbytes)
        self.bitpos = 0

    def write(self, value, bits):
        if bits == 0:
            return
        self._write(value, bits, [bits])

    def _write(self, value, bits, remaining_box):
        value &= (1 << bits) - 1  # cobb::bitmax (caps at 64 bits)
        bytepos = self.bitpos // 8
        shift = self.bitpos % 8
        if shift == 0:
            if bits < 8:
                self.buf[bytepos] = (value << (8 - bits)) & 0xFF
                self.bitpos += bits
                return
            self.buf[bytepos] = (value >> (bits - 8)) & 0xFF
            self.bitpos += 8
            remaining_box[0] -= 8
        else:
            extra = 8 - shift
            if bits <= extra:
                self.buf[bytepos] |= (value << (extra - bits)) & 0xFF
                self.bitpos += bits
                return
            self.buf[bytepos] &= ~(0xFF >> shift) & 0xFF
            self.buf[bytepos] |= (value >> (bits - extra)) & 0xFF
            self.bitpos += extra
            remaining_box[0] -= extra
        if remaining_box[0] > 0:
            # RVT: this->write(value, remaining, remaining)  -> recursion keeps masking to `remaining` bits
            rem = remaining_box[0]
            self._write(value, rem, remaining_box)


# --------------------------------------------------------------------------
# Self test against real files
# --------------------------------------------------------------------------
ROOT = os.path.expanduser("~/Local_Documents")
PATTERNS = [
    ROOT + "/rvt-test-samples/*.bin",
    ROOT + "/ReachVariantTool-core-library/macos/Fixtures/*.bin",
]


def load_mpvr_payloads():
    """Return {md5: (name, payload_bytes, hashable_len)} for every distinct real file."""
    found = {}
    for pat in PATTERNS:
        for p in sorted(glob.glob(pat)):
            data = open(p, "rb").read()
            md5 = hashlib.md5(data).hexdigest()
            if md5 in found:
                continue
            pos = 0
            while pos + 12 <= len(data):
                sig, size, ver, flags = struct.unpack_from(">4sIHH", data, pos)
                if sig == b"mpvr":
                    hashable_len = struct.unpack_from("<I", data, pos + 0x24)[0]
                    payload = data[pos + 0x28:pos + size]
                    found[md5] = (os.path.basename(p), payload, hashable_len)
                    break
                pos += size
    return found


def random_schedule(rng, total_bits):
    """Random field widths (1..64, biased toward small like real fields) summing to total_bits."""
    widths = []
    left = total_bits
    while left > 0:
        r = rng.random()
        if r < 0.45:
            w = rng.randint(1, 8)
        elif r < 0.75:
            w = rng.randint(9, 16)
        elif r < 0.92:
            w = rng.randint(17, 32)
        else:
            w = rng.randint(33, 64)
        w = min(w, left)
        widths.append(w)
        left -= w
    return widths


def roundtrip(payload_bits_source, total_bits, start_bit, rng):
    """Read `total_bits` bits starting at start_bit in random widths, write them back, return (written_bytes, widths)."""
    widths = random_schedule(rng, total_bits)
    r = BitReader(payload_bits_source)
    r.set_bitpos(start_bit)
    vals = [r.read(w) for w in widths]
    assert r.pos == start_bit + total_bits
    # oracle 1: RVT port reader must give the same values
    o = RvtPortReader(payload_bits_source)
    o.offset = start_bit
    ovals = [o.read_bits(w) for w in widths]
    assert ovals == vals, "RVT-port reader disagrees with BitReader"
    w = BitWriter()
    for v, n in zip(vals, widths):
        w.write(v, n)
    assert w.pos == total_bits
    # oracle 2: RVT port writer must give the same bytes
    pw = RvtPortWriter((total_bits + 7) // 8 + 1)
    for v, n in zip(vals, widths):
        pw.write(v, n)
    nbytes = (total_bits + 7) // 8
    assert bytes(pw.buf[:nbytes]) == w.getvalue(), "RVT-port writer disagrees with BitWriter"
    return w.getvalue(), widths


def selftest(seeds=40, verbose=True):
    payloads = load_mpvr_payloads()
    assert len(payloads) >= 1, "no real files found"
    checks = 0
    for md5, (name, payload, hlen) in payloads.items():
        full_bits = len(payload) * 8
        for seed in range(seeds):
            rng = random.Random(0xC0BB ^ (seed * 7919) ^ int(md5[:8], 16))
            # (a) whole payload, byte-multiple total
            out, widths = roundtrip(payload, full_bits, 0, rng)
            assert out == payload, "whole-payload round trip FAILED (%s seed %d)" % (name, seed)
            checks += 1
            # (b) whole payload minus 1..7 bits (non-multiple-of-8 total); last byte partial
            trim = rng.randint(1, 7)
            tb = full_bits - trim
            out, widths = roundtrip(payload, tb, 0, rng)
            assert len(out) == len(payload)
            mask = (0xFF << trim) & 0xFF
            assert out[:-1] == payload[:-1] and (out[-1] & mask) == (payload[-1] & mask) and (out[-1] & ~mask & 0xFF) == 0, \
                "non-multiple-of-8 round trip FAILED (%s seed %d trim %d)" % (name, seed, trim)
            checks += 1
            # (c) the hashable region only, with a non-multiple-of-8 bit count and misaligned start (type nibble = 4 bits)
            start = 4
            tb = hlen * 8 - 4 - rng.randint(0, 7)
            out, widths = roundtrip(payload, tb, start, rng)
            # compare through a pure big-int slice (definition of MSB-first)
            big = int.from_bytes(payload, "big")
            sl = (big >> (full_bits - start - tb)) & ((1 << tb) - 1)
            ref_bytes = (sl << ((8 - tb % 8) % 8)).to_bytes((tb + 7) // 8, "big")
            assert out == ref_bytes, "misaligned region round trip FAILED (%s seed %d)" % (name, seed)
            checks += 1
        if verbose:
            print("OK  %-40s payload=%d bytes  hashable_len=0x%X  (%d seeds x 3 schedules)" % (
                name, len(payload), hlen, seeds))
    # signed / offset / write_to_bitpos / u16string unit checks
    w = BitWriter()
    w.write(-1, 3)
    w.write_offset(-1, 3)           # stored 0
    w.write_offset(5, 3)            # stored 6
    w.write_u16string([0x4E, 0x6F, 0], 4)
    r = BitReader(w.getvalue())
    assert r.read_signed(3) == -1
    assert r.read_offset(3) == -1
    assert r.read_offset(3) == 5
    assert r.read_u16string(4) == [0x4E, 0x6F, 0]
    w2 = BitWriter()
    w2.write(0, 40)
    w2.write_to_bitpos(5, 32, 0xDEADBEEF)
    rb = BitReader(w2.getvalue())
    rb.set_bitpos(5)
    assert rb.read(32) == 0xDEADBEEF and w2.pos == 40
    # reading past EOF gives zeros and counts overflow
    rr = BitReader(b"\xff")
    assert rr.read(12) == 0xFF0 and rr.overflow == 4
    checks += 8
    if verbose:
        print("ALL %d CHECKS PASSED" % checks)
    return checks


if __name__ == "__main__":
    selftest()
