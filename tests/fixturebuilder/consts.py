"""Literal tables for the independent fixture builder, copied by hand from the spec (SPEC sections 2, 3, 4).

This module is data only.  Every number is typed here from the document, not taken from any code under
test (DEC-9.2).  Section references ("SPEC 3.6") are to ``docs/mvar/SPEC-mvar.md``.
"""

SCHEMA_SPEC = "mjolnir.fixture_spec/1"

# ---- container (SPEC 2.1 to 2.9) ---------------------------------------------------------------------
BLOCK_HEADER_SIZE = 12

BLF = {"sig": "_blf", "size": 0x30, "version": 1, "flags": 2}
BLF_BOM = b"\xff\xfe"                      # at +0x0C, then 0x20 zero bytes, then 2 zero bytes

CHDR = {"sig": "chdr", "size": 0x2C0, "version": 10, "flags": 2}

MVAR = {"sig": "mvar", "size": 0x7028, "version": 31, "flags": 1}
MVAR_HASH_OFFSET = 12                      # 20 bytes
MVAR_HASH_LENGTH = 20
MVAR_LENGTH_OFFSET = 32                    # 4 bytes, the stored stream length L
MVAR_STREAM_OFFSET = 36
MVAR_STREAM_CAPACITY = 0x7000              # bytes; 229,376 bits
MVAR_TRAILING_PAD = 4
STREAM_CAPACITY_BITS = 8 * MVAR_STREAM_CAPACITY

EOF = {"sig": "_eof", "size": 0x11, "version": 1, "flags": 1}

FSM = {"sig": "_fsm", "size": 0x1C4, "version": 1, "flags": 1}          # SPEC 2.9 "fixed fields of 0x1C4 bytes"

CMP = {"sig": "_cmp", "version": 1, "flags": 1}                          # wrapper version/flags are not specified (assumed)
CMP_TYPE_ZLIB = 0
CMP_PREFIX = 12 + 1 + 4                                                  # header, type byte, u32 BE uncompressed size

# Known file sizes (SPEC 2.2, G-SZ)
PLAIN_FILE_LENGTH = 0x30 + 0x2C0 + 0x7028 + 0x11                         # 29,481 = 0x7329
EOF_OFFSET = 0x30 + 0x2C0 + 0x7028                                       # 0x7318

# ---- chdr (SPEC 2.4): offsets of the interpreted fields, numbers little-endian --------------------------
CHDR_SCALARS = (
    # (name, offset, struct format)
    ("build_major", 0x0C, "<H"),
    ("build_minor", 0x0E, "<H"),
    ("content_type", 0x10, "<b"),
    ("file_length", 0x14, "<I"),
    ("id0", 0x18, "<Q"),
    ("id1", 0x20, "<Q"),
    ("id2", 0x28, "<Q"),
    ("id3", 0x30, "<Q"),
    ("activity", 0x38, "<b"),
    ("game_mode", 0x39, "<B"),
    ("engine", 0x3A, "<B"),
    ("map_id", 0x3C, "<I"),
    ("engine_category", 0x40, "<I"),
    ("engine_icon", 0x290, "<I"),
    ("campaign_id", 0x2B0, "<B"),
    ("campaign_difficulty", 0x2B1, "<B"),
    ("campaign_metagame", 0x2B2, "<B"),
    ("campaign_rally", 0x2B3, "<B"),
    ("campaign_unk", 0x2B4, "<I"),
)
CHDR_AUTHOR_OFFSETS = {"created_by": 0x48, "modified_by": 0x6C}          # each 0x24 bytes
CHDR_AUTHOR_SIZE = 0x24                                                  # u64 ts, u64 xuid, char[16], u8 online, 3 pad
CHDR_TITLE_OFFSET = 0x90                                                 # 128 UTF-16LE units
CHDR_DESCRIPTION_OFFSET = 0x190
CHDR_TEXT_UNITS = 128

# ---- UGC header in bit form (SPEC 3.2) -------------------------------------------------------------------
UGC_HEADER_FIXED = (
    # (name, width, stored adjustment)  stored = decoded + adjustment
    ("content_type", 4, 1),
    ("file_length", 32, 0),
    ("id0", 64, 0),
    ("id1", 64, 0),
    ("id2", 64, 0),
    ("id3", 64, 0),
    ("activity", 3, 1),
    ("game_mode", 3, 0),
    ("engine", 3, 0),
    ("map_id", 32, 0),
    ("category", 8, 0),
)
AUTHOR_FIELDS = (("timestamp", 64), ("xuid", 64))                        # then name chars (8 bits each, max 16), then online (1)
AUTHOR_NAME_MAX = 16
TEXT_UNITS_MAX = 128                                                     # title and description, 16-bit units
CONTENT_TYPE_MAP_VARIANT = 5
CONTENT_TYPE_GAME_VARIANT = 6
ENGINE_ICON_BITS = 8                                                     # only for a game variant content type
HOPPER_ACTIVITY = 2                                                      # decoded activity that carries the hopper id
HOPPER_BITS = 16
GAME_MODE_CAMPAIGN = 1
GAME_MODE_FIREFIGHT = 2
CAMPAIGN_TAIL = (("id", 8), ("difficulty", 2), ("metagame", 2), ("rally", 8), ("unk", 32))     # 52 bits
FIREFIGHT_TAIL = (("difficulty", 2), ("unk", 32))                                              # 34 bits

# ---- body, fixed fields (SPEC 3.3), 371 bits ------------------------------------------------------------
BODY_FIELDS = (
    ("version", 8),
    ("checksum", 32),
    ("palette_crc", 32),
    ("quota_count", 9),
    ("map_id_2", 32),
    ("built_in", 1),
    ("built_from_xml", 1),
    # six float32 bounds follow: xmin, xmax, ymin, ymax, zmin, zmax
)
BOUNDS_COUNT = 6
BOUNDS_BITS = 32
BODY_TAIL_FIELDS = (("max_budget", 32), ("spent_budget", 32))
BODY_FIXED_BITS = 371

# ---- label table (SPEC 3.4) ------------------------------------------------------------------------------
LABEL_COUNT_BITS = 9
LABEL_PRESENT_BITS = 1
LABEL_OFFSET_BITS = 12
LABEL_DATA_LENGTH_BITS = 13
LABEL_COMPRESSED_BITS = 1
LABEL_COMP_SIZE_BITS = 13
LABEL_MAX_COUNT = 256
LABEL_COMPRESS_MIN_BYTES = 0x80                                          # RVT compresses from this size on (informative)

# ---- version 32 extra bits (SPEC 3.5) ------------------------------------------------------------------
GUID_BITS = 128

# ---- slots (SPEC 3.6) -------------------------------------------------------------------------------------
SLOT_COUNT = 651
SLOT_FIELDS = (
    # (name, kind, width)
    # kinds: "u" unsigned; "s" two's complement; "opt" = absent bit (1 = none) then value;
    #        "axes" = three position fields with the axis widths; "up" = up_global bit (1 = no code) then 20-bit code;
    #        "dims" = shape-dependent count of 11-bit values; "extras" = by cached type (SPEC 3.8)
    ("present", "u", 1),
    ("flags2", "u", 2),
    ("folder", "opt", 8),
    ("item", "opt", 5),
    ("in_bounds", "u", 1),
    ("pos", "axes", 3),
    ("up", "up", 20),
    ("angle", "u", 14),
    ("parent_raw", "u", 10),
    ("shape", "u", 2),
    ("dims", "dims", 11),
    ("spawn_seq", "s", 8),
    ("respawn", "u", 8),
    ("cached_type", "u", 5),
    ("label", "opt", 8),
    ("placement", "u", 8),
    ("team_raw", "u", 4),
    ("color", "opt", 3),
    ("extra", "extras", 0),
)
SHAPE_DIM_COUNT = {0: 0, 1: 1, 2: 3, 3: 4}
EXTRA_WIDTHS = {1: (8,), 12: (5, 5), 13: (5, 5), 14: (5, 5)}
TYPE19 = 19
TYPE19_RULES = ("flag8", "plain8")                                       # SPEC 3.8
UP_CODE_MAX_VALID = 1048571                                              # face <= 5 (codes 1,048,572 and up are invalid)
PARENT_RAW_MAX = 651

# ---- quota table (SPEC 3.7) ------------------------------------------------------------------------------
QUOTA_ROW = (("minimum", 8), ("maximum", 8), ("placed", 8))
QUOTA_COUNT_MAX = 256

# ---- axis bit counts (SPEC 4.1) ----------------------------------------------------------------------------
MIN_UNIT_16 = 0.00833333333
STEP_FLOOR = 0.0001
ENGINE_UNIT_16 = 0.008333333767950535            # float32 0x3C088889
AXIS_BASE_BITS = 21
AXIS_MAX_BITS = 26
AXIS_MAX_CELLS = 0x800000
TRUNC_FUDGE = 0.9999
AXIS_VARIANTS = ("ceil", "trunc9999", "ceil_f32")

# ---- hashing (SPEC 2.7) ------------------------------------------------------------------------------------
SALT34 = bytes.fromhex("EDD43009666D5C4A5C3657FAB40E022F535AC6C9EE471F01F1A44756B7714F1C36EC")
assert len(SALT34) == 34
# recipe -> (salt used, byte order of the 32-bit length in the digest input or None)
HASH_RECIPES = {
    "plain_le32": (False, "<"),
    "salted_be32": (True, ">"),
    "salted_le32": (True, "<"),
    "plain_be32": (False, ">"),
    "data_only": (False, None),
    "zero": (False, None),                      # no digest: 20 zero bytes
}
HASH_TEST_VECTOR_DATA = bytes(range(10))
HASH_TEST_VECTOR_L = 10

# ---- codecs (SPEC 4.2 to 4.5) -----------------------------------------------------------------------------
DIM_BITS = 11
DIM_MAX_VALUE = 200.0
DIM_STEP = 0.0977517142892
DIM_FIRST = 0.0488758571446
ANGLE_BITS = 14
UP_STRIDE = 174762
UP_N = 417

# ---- stock map ids used by fixtures (SPEC 7.1) ----------------------------------------------------------
FORGE_WORLD_MAP_ID = 3006
UNKNOWN_MAP_ID = 0xFFFFFFFF
