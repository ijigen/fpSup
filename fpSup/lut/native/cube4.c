/* The .cube files are the user's and are never written (2026-11-06: the list is
 * \fpSup\LUT\'s files; all settings live in LUT.BIN).  Until then a cube prepared
 * on a computer carried a 512-byte managed comment block the camera rewrote; that
 * path is gone with the prepared entries (library4.c library_drop_prepared). */
#define CUBE_MAX 0x4000000u
static u32 cube_fnv(u32 h,const u8 *p,u32 n) {for(u32 i=0;i<n;i++)h=(h^p[i])*16777619u;return h;}
