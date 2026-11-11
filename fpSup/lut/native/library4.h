/* library.py: one mutable per-cube record inside our own LUT.BIN. */
#define LIB_MAGIC 0x31424C43u
#define LIB_NONE 0xFFFFFFFFu
#define LIB_MAX 32u
#define LIB_ENABLED 1u
#define LIB_SPACE 2u
#define LIB_GAMMA 4u
#define LIB_MATRIX 8u                  /* the color matrix resolves (a bad custom one does not) */
#define LIB_READY (LIB_SPACE|LIB_GAMMA|LIB_MATRIX)
#define LIB_ALL (LIB_ENABLED|LIB_READY)
#define AUTH_CUSTOM 16u                /* author_flags: the author's custom matrices parsed */
enum { MAT_STANDARD, MAT_OFF, MAT_CUSTOM, MAT_N };   /* the DNG profile the LUT was made on */
#define G_NONE 0xFFu
#define ORIGIN_CAMERA 1u               /* import.c: a .cube copied to the folder */
#define ORIGIN_GONE   2u               /* ... whose file is no longer there */
enum { VIEW_LEGACY, VIEW_COLOR, VIEW_MANAGER, VIEW_PICKER, VIEW_SETTINGS };
/* v3 (user 2026-11-03): the author's values and the user's are kept apart.
 * flags/color/gamma/matrix are the effective values, always lib_resolve() of
 * the two layers: the user's where user_flags has the bit, else the author's.
 * Gammas in the layers are the global index (6, 7 = Blackmagic); the effective
 * gamma is the index within its family, as before.  cm: the author's custom
 * ColorMatrix1 (A) / 2 (D65), XYZ -> camera before the body's calibration, Q20. */
struct lib_entry {
    u8 sha[32]; char name[64];
    u32 flags, color, gamma, amount;
    u32 source_len, source_hash, source_options, origin;   /* import.c ORIGIN_*: 0 = prepared on a computer */
    u32 matrix, author_flags, author_color, author_gamma, author_matrix, user_flags, user_color, user_gamma;
    u32 user_matrix, reserved0[3];
    i32 cm[2][9];
    u32 reserved1[2];
};
struct lib_header {
    u32 magic, version, header_len, record_len, count, active, checksum, reserved;
    u8 identity[32];
};
struct lib_catalog { struct lib_header h; struct lib_entry entries[LIB_MAX]; };
_Static_assert(sizeof(struct lib_header)==64,"library header");
_Static_assert(sizeof(struct lib_entry)==256,"library record");
struct lut4_state;
static int imp_scan(struct lut4_state *);
static void imp_icons(struct lut4_state *);
static int imp_asset(struct lut4_state *,unsigned);
static int library_save(struct lut4_state *);
