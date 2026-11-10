/* Freestanding browser adapter. host_bridge.c and the extracted camera QR
 * encoder remain the same sources used by the native preview backend. */
#include <stddef.h>
#include <stdint.h>
#include "core.h"
#include "camera_qr_constants.h"

void *memcpy(void *dest, const void *src, size_t n)
{
    unsigned char *d = dest;
    const unsigned char *s = src;
    for (size_t i = 0; i < n; i++) d[i] = s[i];
    return dest;
}
void *memset(void *dest, int value, size_t n)
{
    unsigned char *d = dest;
    for (size_t i = 0; i < n; i++) d[i] = (unsigned char)value;
    return dest;
}
size_t strlen(const char *s)
{
    size_t n = 0;
    while (s[n]) n++;
    return n;
}

static core_quality rows[CORE_MAX_QUAL];
static char qr_url[QR_DATA_CW + 1u];
static uint8_t qr_output[QR_N * QR_N];
extern int preview_qr(const char *url, uint8_t *out);
extern int preview_readout(const core_quality *q, int32_t out[10]);

core_quality *wasm_rows(void) { return rows; }
char *wasm_url(void) { return qr_url; }
uint8_t *wasm_qr_output(void) { return qr_output; }
int wasm_url_capacity(void) { return sizeof qr_url; }
int wasm_qualities(int dcw, int dch, int rw, int rh, int tol_num, int tol_den)
{
    return core_qualities_tol(dcw, dch, rw, rh, 0, 1, tol_num, tol_den, rows, CORE_MAX_QUAL);
}
int wasm_qr(void) { return preview_qr(qr_url, qr_output); }
static int32_t readout[10];
int32_t *wasm_readout(int i)                     /* row i of the last wasm_qualities: its readout (host_bridge.c) */
{
    if (i < 0 || i >= CORE_MAX_QUAL) { readout[0] = -1; return readout; }
    preview_readout(&rows[i], readout);
    return readout;
}
