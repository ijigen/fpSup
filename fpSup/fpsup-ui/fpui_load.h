/* One stock page pack load, the way stock's own wrapper leaves the UI (C05DAA40).
 *
 * The stock NBR load (C05E84D8) unbinds every resource already handed out (C05E0940),
 * the localised texts among them, and the GUI draws their keys at once ("1474" for
 * "Now Connecting..."; camera 2026-11-15: C05E0940 alone turns an open menu into
 * numbers).  So the language is marked stale and translated again right after it --
 * unless the GUI is inside a screen change (C05DCCB8), where stock does not translate
 * either (C05DE718) and the GUI does it itself when it is done.
 *
 * Every sup that loads a pack calls this, whatever thread it loads on: fpsup_ui.c from
 * the boot thread (after waiting for the GUI, fpui_load), Sensor Lab from the GUI's own
 * layout callback. */
#ifndef FPUI_LOAD_H
#define FPUI_LOAD_H
#include <stdint.h>

#define FPUI_NBR_LOAD     0xC05E84D9u     /* Thumb: (app, pack, len, &reader) */
#define FPUI_LANG_STALE   0xC05DE6B1u     /* Thumb: (app) -- texts are translated again on the next GUI pass */
#define FPUI_UI_BUSY      0xC05DCCB9u     /* Thumb: (app) -- 1 while the GUI is inside a screen change */
#define FPUI_LANG_APPLY   0xC05DE5B9u     /* Thumb: (app) -- translate the stale texts now */

typedef uint32_t (*fpui_fn1)(uint32_t);
typedef uint32_t (*fpui_fn4)(uint32_t, uint32_t, uint32_t, uint32_t);
#define FPUI_FW(addr, type) ((type)(uintptr_t)(addr))

static inline uint32_t fpui_load_now(uintptr_t app, const uint8_t *pack, uint32_t len, uintptr_t *reader)
{
    uint32_t bad = FPUI_FW(FPUI_NBR_LOAD, fpui_fn4)((uint32_t)app, (uint32_t)(uintptr_t)pack, len,
                                                    (uint32_t)(uintptr_t)reader);
    FPUI_FW(FPUI_LANG_STALE, fpui_fn1)((uint32_t)app);
    if (!FPUI_FW(FPUI_UI_BUSY, fpui_fn1)((uint32_t)app)) FPUI_FW(FPUI_LANG_APPLY, fpui_fn1)((uint32_t)app);
    return bad;
}
#endif
