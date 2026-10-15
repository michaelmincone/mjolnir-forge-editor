"""UGC header codec: the bit form inside the payload stream and the byte form in ``chdr`` (SPEC 2.4, 3.2).

The *bit form* is the same structure for the ``mpvr`` game variant (after a 68-bit prefix: 4-bit
engine type, u32 encodingVersion, u32 engineVersion) and for the ``mvar`` map variant (the stream
starts with it). :func:`read_header` / :func:`write_header` work at whatever bit position the reader
or writer is at, so one codec serves both (tier T1 proves it on the real ``mpvr`` files at bit 68 and
again with the same bits moved to bit 0).

Layout (SPEC 3.2; bit offsets from the start of the header)::

     0   4  contentType     stored value + 1 (map variant 5 -> 6, game variant 6 -> 7)
     4  32  fileLength      total file length through _eof (inside the hashed region)
    36 4x64 unk08 unk10 unk18 unk20 (content ids, opaque)
   292   3  activity        stored value + 1; hopperID follows iff the DECODED value is 2 (stored 3)
   295   3  gameMode        1 campaign, 2 firefight, 3 matchmaking, 4 forge, 5 theater
   298   3  engine
   301  32  mapID
   333   8  engineCategory
   341   A  createdBy       author record: u64 timestamp, u64 xuid, name (8-bit chars, stops after the
                            first NUL, 1..16 chars), u1 isOnlineID  (129 + 8 n bits)
   ...  A'  modifiedBy
   ... 16t  title          UTF-16BE units, stops after the first NUL, t <= 128 (t counts the NUL)
   ... 16d  description    same
   ...   8  engineIcon     only if contentType is a game variant (decoded 6)
   ...  16  hopperID       only if the decoded activity is 2
   ...  52  campaign tail  id u8, difficulty u2, metagameScoring u2, rallyPoint u8, unk u32; iff gameMode 1
   ...  34  firefight tail difficulty u2, unk u32; iff gameMode 2

The width of every field is fixed except the author names and the two strings, so the header end is
``341 + (129 + 8 n_c) + (129 + 8 n_m) + 16 t + 16 d`` plus the conditional parts. Any fixed skip
constant is wrong in general.

The header is parsed into fields *and* its raw bit range is kept (``UgcHeader.raw``). Header fields
are not editable in v1 (DEC-3.1); the model re-emits ``raw``. ``write_header`` re-encodes from the
fields and is what the tests use to prove the field codec is bit-exact.

The *byte form* ``chdr`` (0x2C0 bytes) is byte aligned: little-endian numbers, UTF-16LE strings.
:func:`parse_chdr` keeps every byte (pads and unknown regions included), so :func:`build_chdr` is
byte-exact on any 0x2C0-byte block, not only on the real files.

Pure Python 3.9 to 3.13, standard library only, relative imports only.
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

from .bitio import BitReader, BitString, BitWriter
from .errors import BlfFormatError, EncodeError, InternalError

__all__ = ["AuthorRecord", "CampaignTail", "FirefightTail", "UgcHeader", "read_header", "write_header",
           "parse_chdr", "build_chdr", "compare_chdr_header", "decode_u16", "encode_u16", "CONTENT_TYPE_MAP_VARIANT",
           "CONTENT_TYPE_GAME_VARIANT", "CONTENT_TYPE_NAMES", "GAME_MODE_NAMES", "FIXED_HEADER_BITS",
           "AUTHOR_NAME_MAX", "TEXT_UNITS_MAX", "CHDR_SIZE"]

CONTENT_TYPE_MAP_VARIANT = 5
CONTENT_TYPE_GAME_VARIANT = 6
CONTENT_TYPE_NAMES = {-1: "none", 0: "dlc", 1: "campaign_save", 2: "screenshot", 3: "film", 4: "film_clip",
                      5: "map_variant", 6: "game_variant", 7: "playlist"}
GAME_MODE_NAMES = {1: "campaign", 2: "firefight", 3: "matchmaking", 4: "forge", 5: "theater"}
FIXED_HEADER_BITS = 341                  # bits before the first author record
AUTHOR_NAME_MAX = 16
TEXT_UNITS_MAX = 128
CHDR_SIZE = 0x2C0
ACTIVITY_HOPPER = 2                      # decoded activity value that adds the hopper id


def decode_u16(units):
    """UTF-16 text of a unit list, up to the first NUL (lone surrogates become U+FFFD)."""
    out = []
    for unit in units:
        if unit == 0:
            break
        out.append(unit)
    raw = b"".join(struct.pack("<H", unit) for unit in out)
    return raw.decode("utf-16-le", errors="replace")


def encode_u16(text, maxlen=TEXT_UNITS_MAX):
    """Unit list for ``text`` ending in a NUL (cut to ``maxlen - 1`` characters so the NUL fits)."""
    raw = text.encode("utf-16-le")
    units = list(struct.unpack("<%dH" % (len(raw) // 2), raw))[:maxlen - 1]
    return units + [0]


@dataclass
class AuthorRecord:
    timestamp: int                       # u64, Unix seconds
    xuid: int                            # u64
    name: bytes                          # 1..16 bytes; ends with a NUL unless it is 16 bytes long
    is_online_id: int                    # 1 bit

    @property
    def bit_length(self):
        return 129 + 8 * len(self.name)

    @property
    def name_text(self):
        return self.name.split(b"\x00")[0].decode("latin-1")


@dataclass
class CampaignTail:
    id: int                              # u8
    difficulty: int                      # u2
    metagame_scoring: int                # u2
    rally_point: int                     # u8
    unk: int                             # u32

    BITS = 52


@dataclass
class FirefightTail:
    difficulty: int                      # u2
    unk: int                             # u32

    BITS = 34


@dataclass
class UgcHeader:
    content_type_raw: int                # stored value (decoded + 1)
    file_length: int
    unk08: int
    unk10: int
    unk18: int
    unk20: int
    activity_raw: int                    # stored value (decoded + 1)
    game_mode: int
    engine: int
    map_id: int
    engine_category: int
    created_by: AuthorRecord
    modified_by: AuthorRecord
    title: List[int]                     # UTF-16 units including the NUL when present
    description: List[int]
    engine_icon: Optional[int] = None    # present only for a game variant
    hopper_id: Optional[int] = None      # present only for decoded activity 2
    campaign: Optional[CampaignTail] = None       # present only for gameMode 1
    firefight: Optional[FirefightTail] = None     # present only for gameMode 2
    raw: Optional[BitString] = field(default=None, compare=False, repr=False)   # exact bit range as read
    start_bit: int = field(default=0, compare=False)                            # where the header started in the stream
    end_bit: int = field(default=0, compare=False)                              # where it ended (E_h for an mvar)

    @property
    def content_type(self):
        return self.content_type_raw - 1

    @property
    def activity(self):
        return self.activity_raw - 1

    @property
    def title_text(self):
        return decode_u16(self.title)

    @property
    def description_text(self):
        return decode_u16(self.description)

    @property
    def has_engine_icon(self):
        return self.content_type == CONTENT_TYPE_GAME_VARIANT

    @property
    def has_hopper(self):
        return self.activity == ACTIVITY_HOPPER

    def bit_length(self):
        """Width of the header in bits, computed from the fields (the formula of SPEC 3.2)."""
        bits = (FIXED_HEADER_BITS + self.created_by.bit_length + self.modified_by.bit_length
                + 16 * len(self.title) + 16 * len(self.description))
        if self.has_engine_icon:
            bits += 8
        if self.has_hopper:
            bits += 16
        if self.game_mode == 1:
            bits += CampaignTail.BITS
        if self.game_mode == 2:
            bits += FirefightTail.BITS
        return bits


def _read_author(r):
    timestamp = r.read(64)
    xuid = r.read(64)
    name = r.read_cstring(AUTHOR_NAME_MAX)
    return AuthorRecord(timestamp, xuid, name, r.read(1))


def _write_author(w, a):
    w.write(a.timestamp, 64)
    w.write(a.xuid, 64)
    w.write_cstring(a.name, AUTHOR_NAME_MAX)
    w.write(a.is_online_id, 1)


def read_header(r: BitReader) -> UgcHeader:
    """Decode the UGC header at the reader's current position; the reader ends just after it."""
    if not isinstance(r, BitReader):
        raise InternalError("read_header needs a BitReader.")
    start = r.pos
    content_type_raw = r.read(4)
    file_length = r.read(32)
    unk08, unk10, unk18, unk20 = r.read(64), r.read(64), r.read(64), r.read(64)
    activity_raw = r.read(3)
    game_mode = r.read(3)
    engine = r.read(3)
    map_id = r.read(32)
    engine_category = r.read(8)
    created_by = _read_author(r)
    modified_by = _read_author(r)
    title = r.read_u16string(TEXT_UNITS_MAX)
    description = r.read_u16string(TEXT_UNITS_MAX)
    header = UgcHeader(content_type_raw, file_length, unk08, unk10, unk18, unk20, activity_raw, game_mode, engine,
                       map_id, engine_category, created_by, modified_by, title, description)
    if header.has_engine_icon:
        header.engine_icon = r.read(8)
    if header.has_hopper:
        header.hopper_id = r.read(16)
    if game_mode == 1:
        header.campaign = CampaignTail(r.read(8), r.read(2), r.read(2), r.read(8), r.read(32))
    elif game_mode == 2:
        header.firefight = FirefightTail(r.read(2), r.read(32))
    header.start_bit = start
    header.end_bit = r.pos
    header.raw = r.slice(start, r.pos)
    return header


def write_header(w: BitWriter, h: UgcHeader) -> None:
    """Encode the header fields at the writer's current position (``EncodeError`` on an inconsistent header)."""
    if not isinstance(w, BitWriter):
        raise InternalError("write_header needs a BitWriter.")
    if h.has_engine_icon != (h.engine_icon is not None):
        raise EncodeError("The engine icon is stored only for a game variant (content type 6).")
    if h.has_hopper != (h.hopper_id is not None):
        raise EncodeError("The hopper id is stored if and only if the decoded activity is %d." % ACTIVITY_HOPPER)
    if (h.game_mode == 1) != (h.campaign is not None):
        raise EncodeError("The campaign tail is stored if and only if the game mode is 1.")
    if (h.game_mode == 2) != (h.firefight is not None):
        raise EncodeError("The firefight tail is stored if and only if the game mode is 2.")
    w.write(h.content_type_raw, 4)
    w.write(h.file_length, 32)
    for value in (h.unk08, h.unk10, h.unk18, h.unk20):
        w.write(value, 64)
    w.write(h.activity_raw, 3)
    w.write(h.game_mode, 3)
    w.write(h.engine, 3)
    w.write(h.map_id, 32)
    w.write(h.engine_category, 8)
    _write_author(w, h.created_by)
    _write_author(w, h.modified_by)
    w.write_u16string(h.title, TEXT_UNITS_MAX)
    w.write_u16string(h.description, TEXT_UNITS_MAX)
    if h.engine_icon is not None:
        w.write(h.engine_icon, 8)
    if h.hopper_id is not None:
        w.write(h.hopper_id, 16)
    if h.campaign is not None:
        c = h.campaign
        w.write(c.id, 8)
        w.write(c.difficulty, 2)
        w.write(c.metagame_scoring, 2)
        w.write(c.rally_point, 8)
        w.write(c.unk, 32)
    if h.firefight is not None:
        f = h.firefight
        w.write(f.difficulty, 2)
        w.write(f.unk, 32)


# ---------------------------------------------------------------------------------------------
# chdr: byte form (SPEC 2.4)
# ---------------------------------------------------------------------------------------------
_AUTHOR_OFFSETS = (("created_by", 0x48), ("modified_by", 0x6C))


def parse_chdr(block: bytes) -> dict:
    """Parse the 0x2C0-byte ``chdr`` block (header included) into a dict that keeps every byte."""
    block = bytes(block)
    if len(block) != CHDR_SIZE:
        raise BlfFormatError("The 'chdr' block has %d bytes; %d are expected." % (len(block), CHDR_SIZE))
    sig, size, version, flags = struct.unpack_from(">4sIHH", block, 0)
    if sig != b"chdr" or size != CHDR_SIZE:
        raise BlfFormatError("The block at the start of the content header is '%s' of size 0x%X, "
                             "not 'chdr' of size 0x%X." % (sig.decode("latin-1", errors="replace"), size, CHDR_SIZE))

    def u(fmt, off):
        return struct.unpack_from(fmt, block, off)[0]

    d = {
        "version": version, "flags": flags,
        "build_major": u("<H", 0x0C), "build_minor": u("<H", 0x0E),
        "content_type": u("<b", 0x10), "pad_11": block[0x11:0x14],
        "file_length": u("<I", 0x14),
        "unk08": u("<Q", 0x18), "unk10": u("<Q", 0x20), "unk18": u("<Q", 0x28), "unk20": u("<Q", 0x30),
        "activity": u("<b", 0x38), "game_mode": u("<B", 0x39), "engine": u("<B", 0x3A), "pad_3b": block[0x3B:0x3C],
        "map_id": u("<I", 0x3C), "engine_category": u("<I", 0x40), "pad_44": block[0x44:0x48],
        "title_raw": block[0x90:0x190], "description_raw": block[0x190:0x290],
        "engine_icon": u("<I", 0x290), "unk294": block[0x294:0x2B0],
        "campaign_id": u("<B", 0x2B0), "campaign_difficulty": u("<B", 0x2B1),
        "campaign_metagame": u("<B", 0x2B2), "campaign_rally": u("<B", 0x2B3), "campaign_unk": u("<I", 0x2B4),
        "unk2b8": block[0x2B8:0x2C0],
    }
    for who, off in _AUTHOR_OFFSETS:
        d[who] = {"timestamp": u("<Q", off), "xuid": u("<Q", off + 8), "name": block[off + 16:off + 32],
                  "is_online_id": u("<B", off + 32), "pad": block[off + 33:off + 36]}
    d["title"] = d["title_raw"].decode("utf-16-le", errors="replace").split("\x00")[0]
    d["description"] = d["description_raw"].decode("utf-16-le", errors="replace").split("\x00")[0]
    return d


def _fixed(value, size, what):
    """A byte field of exactly ``size`` bytes (a slice assignment of another length would resize the block)."""
    value = bytes(value)
    if len(value) != size:
        raise EncodeError("The chdr field %s must be %d bytes, got %d." % (what, size, len(value)))
    return value


def build_chdr(d: dict) -> bytes:
    """Byte-exact inverse of :func:`parse_chdr` (the derived ``title`` / ``description`` strings are ignored)."""
    b = bytearray(CHDR_SIZE)
    b[0:12] = struct.pack(">4sIHH", b"chdr", CHDR_SIZE, d["version"], d["flags"])

    def put(fmt, off, value):
        struct.pack_into(fmt, b, off, value)

    put("<H", 0x0C, d["build_major"])
    put("<H", 0x0E, d["build_minor"])
    put("<b", 0x10, d["content_type"])
    b[0x11:0x14] = _fixed(d["pad_11"], 3, "pad_11")
    put("<I", 0x14, d["file_length"])
    for name, off in (("unk08", 0x18), ("unk10", 0x20), ("unk18", 0x28), ("unk20", 0x30)):
        put("<Q", off, d[name])
    put("<b", 0x38, d["activity"])
    put("<B", 0x39, d["game_mode"])
    put("<B", 0x3A, d["engine"])
    b[0x3B:0x3C] = _fixed(d["pad_3b"], 1, "pad_3b")
    put("<I", 0x3C, d["map_id"])
    put("<I", 0x40, d["engine_category"])
    b[0x44:0x48] = _fixed(d["pad_44"], 4, "pad_44")
    for who, off in _AUTHOR_OFFSETS:
        a = d[who]
        put("<Q", off, a["timestamp"])
        put("<Q", off + 8, a["xuid"])
        b[off + 16:off + 32] = _fixed(a["name"], 16, who + ".name")
        put("<B", off + 32, a["is_online_id"])
        b[off + 33:off + 36] = _fixed(a["pad"], 3, who + ".pad")
    b[0x90:0x190] = _fixed(d["title_raw"], 0x100, "title_raw")
    b[0x190:0x290] = _fixed(d["description_raw"], 0x100, "description_raw")
    put("<I", 0x290, d["engine_icon"])
    b[0x294:0x2B0] = _fixed(d["unk294"], 0x1C, "unk294")
    put("<B", 0x2B0, d["campaign_id"])
    put("<B", 0x2B1, d["campaign_difficulty"])
    put("<B", 0x2B2, d["campaign_metagame"])
    put("<B", 0x2B3, d["campaign_rally"])
    put("<I", 0x2B4, d["campaign_unk"])
    b[0x2B8:0x2C0] = _fixed(d["unk2b8"], 8, "unk2b8")
    return bytes(b)


def compare_chdr_header(chdr, header, extended=False):
    """Differences between the ``chdr`` fields and the bit-form header as a list of sentences (empty = agree).

    The five fields ``verify_mvar`` cross-checks (SPEC 2.4): content type, file length, map id,
    title, description. ``extended=True`` also compares the content ids, activity, game mode, engine,
    engine category, both author records and (for a game variant) the engine icon; every one of
    them is equal in the real game-variant files.
    """
    out = []

    def check(name, in_chdr, in_header):
        if in_chdr != in_header:
            out.append("%s differs: chdr has %r, the stream header has %r." % (name, in_chdr, in_header))

    check("content type", chdr["content_type"], header.content_type)
    check("file length", chdr["file_length"], header.file_length)
    check("map id", chdr["map_id"], header.map_id)
    check("title", chdr["title"], header.title_text)
    check("description", chdr["description"], header.description_text)
    if extended:
        for name in ("unk08", "unk10", "unk18", "unk20"):
            check(name, chdr[name], getattr(header, name))
        check("activity", chdr["activity"], header.activity)
        check("game mode", chdr["game_mode"], header.game_mode)
        check("engine", chdr["engine"], header.engine)
        check("engine category", chdr["engine_category"], header.engine_category)
        for who in ("created_by", "modified_by"):
            record = getattr(header, who)
            check(who + " timestamp", chdr[who]["timestamp"], record.timestamp)
            check(who + " xuid", chdr[who]["xuid"], record.xuid)
            check(who + " name", chdr[who]["name"].split(b"\x00")[0], record.name.split(b"\x00")[0])
            check(who + " online id flag", chdr[who]["is_online_id"], record.is_online_id)
        if header.engine_icon is not None:
            check("engine icon", chdr["engine_icon"], header.engine_icon)
    return out
