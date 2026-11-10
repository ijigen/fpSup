/* Dial Fix as a loader v4 sup (DialFix_v0.2.0.BIN, sup_id "DIAL").
 *
 * Carries Andy_hal9000's rear-wheel decoder v6 (reference/v6/: his release,
 * frozen copy of his commit 45b7796; verified on the camera by its author as
 * an AutoRun card on 2026-11-07).  His card writes the decoder over the stock
 * code at C02E1CE8 and points vtable +0x10 at it; the stock edge handlers'
 * `bl C02E1D78` then land in its ARM stub.  Here the same 107 words live in
 * the sup's block (cached alias) and the class's vtable is pointed at them,
 * so no firmware code is overwritten:
 *
 *   vtable C0B4E778 +0x10  poll    C02E1D08 -> dial_v6 + 1     (Thumb, called by blx)
 *                   +0x14  edge A  C02E20D8 -> dial_edge_a     (IRQ, via C02E21E0)
 *                   +0x18  edge B  C02E20F0 -> dial_edge_b     (IRQ, via C02E2208)
 *
 * dial_edge_a/b do what stock C02E20D8/C02E20F0 do (r1 = channel, then the
 * edge routine), but into the decoder's ARM stub at +0x90.
 *
 * The decoder (his dial2_fast.S, NOTES 21-22): the 12.5 ms poll decides when
 * a click starts and ends, the edge interrupts decide its direction and count
 * fast spins; one click per detent, clockwise = +1.  ADC 0x301502C0 (A low
 * half, B high half), comparator +0x30.  Position independent: no absolute
 * address but the ADC, no relocation (test_dialfix.py assembles his .S and
 * compares).
 *
 * As his card does: obj+8..+0x18 reset to {3,0,0,4,0}, and 0x301502E4 bits
 * 0-3 set.  All of it with IRQs off.  The vtable slots are claimed, so the
 * core restores them at power-off; the object and the register are not (the
 * firmware builds the object again at boot).
 *
 * Built -fropi like the core: one .text, no globals, no string literals. */
#include "sloader4.h"

typedef uint32_t u32;

#define DIAL_OBJ    0xC3425A78u   /* C02E2334: ctor(r4 + 0x14), r4 = C3425A64; the only instance */
#define DIAL_VT     0xC0B4E778u   /* obj+4 after C02E1EF0 */
#define VT_SLOTS    0xC0B4E788u   /* vtable +0x10, +0x14, +0x18 */
/* His installer (reference/v6/AutoRun.txt lines 11-18): movw r2, #0x02E4; movt r2, #0x3015 -- 0x301502E4,
 * in the ADC block beside 0x301502C0.  Until 2026-11-10 this read 0x321522E4 (the two immediates decoded
 * wrong since v1, and the test mapped the same wrong address): an access there froze the camera as the sup
 * loaded (user 2026-11-10). */
#define EDGE_CFG    0x301502E4u

/* reference/v6/dial2_fast.S assembled (= the words his AutoRun.txt writes at
 * C02E1CE8..C02E1E90; test_dialfix.py checks both). */
__asm__(
"    .text\n"
"    .arm\n"
"    .p2align 2\n"
"dial_v6:\n"                            /* +0x00: Thumb poll (obj, int *out) -> 1 */
"    .word 0xF3EFB5F0, 0xB6728600, 0xF2406882, 0xF2C323C0\n"   /* +0x000 */
"    .word 0x681B0315, 0x2501B29C, 0xF8BEF000, 0x25020C1C\n"   /* +0x010 */
"    .word 0xF8BAF000, 0xF85EF000, 0x68836942, 0xD0042B03\n"   /* +0x020 */
"    .word 0x0210F042, 0x23006142, 0x6983E01F, 0x0F10F012\n"   /* +0x030 */
"    .word 0xF3C2D014, 0xF3C21441, 0x270015C1, 0x42ACB11C\n"   /* +0x040 */
"    .word 0x2C02D007, 0xB125E001, 0xBF0C2D01, 0xF04F2701\n"   /* +0x050 */
"    .word 0xFB0337FF, 0x2C02F407, 0x463BBFB8, 0x61842400\n"   /* +0x060 */
"    .word 0x020FF002, 0x0204F042, 0xF3866142, 0x600B8100\n"   /* +0x070 */
"    .word 0xBDF02001, 0x00000000, 0x00000000, 0x00000000\n"   /* +0x080 */
"dial_v6_irq:\n"                        /* +0x90: ARM stub -> Thumb irq */
"    .word 0xE28FC001, 0xE12FFF1C, 0xF3EFB5F0, 0xB6728600\n"   /* +0x090 */
"    .word 0xF2406882, 0xF2C323C0, 0x6B1F0315, 0xB951681B\n"   /* +0x0A0 */
"    .word 0x25020C1C, 0xF870F000, 0x0201F022, 0x0701F007\n"   /* +0x0B0 */
"    .word 0x0207EA42, 0xB29CE009, 0xF0002501, 0xF022F865\n"   /* +0x0C0 */
"    .word 0xF3C70202, 0xEA424700, 0xF0000247, 0xF386F803\n"   /* +0x0D0 */
"    .word 0xBDF08100, 0x429A6883, 0x4770BF08, 0x69476082\n"   /* +0x0E0 */
"    .word 0x0403EA32, 0x2C03D00A, 0x2400BF08, 0x2A036104\n"   /* +0x0F0 */
"    .word 0xB11CD104, 0x77C0F427, 0x17C4EA47, 0xD1172B03\n"   /* +0x100 */
"    .word 0x0402EA23, 0xBF082C03, 0x60C42400, 0x0F60F017\n"   /* +0x110 */
"    .word 0xEA47BF08, 0xF0071744, 0xF0270404, 0xEA47070F\n"   /* +0x120 */
"    .word 0xF0470744, 0x2A000701, 0xF047BF08, 0xE0290702\n"   /* +0x130 */
"    .word 0x0F01F017, 0xEA83D026, 0x2A000402, 0x2C03BF18\n"   /* +0x140 */
"    .word 0xF047BF08, 0x2A030702, 0x46BCD11C, 0x070FF027\n"   /* +0x150 */
"    .word 0xF01C6147, 0xBF080F02, 0x68C44770, 0xB9346903\n"   /* +0x160 */
"    .word 0xF01CB17B, 0xD00C0F08, 0x0403F1C3, 0x429CE001\n"   /* +0x170 */
"    .word 0x2C02D007, 0x2501BF0C, 0x35FFF04F, 0x442C6984\n"   /* +0x180 */
"    .word 0x47706184, 0x47706147, 0x6F96F5B4, 0x43AABF38\n"   /* +0x190 */
"    .word 0x6F35F5B4, 0x432ABF88, 0xBF004770\n"   /* +0x1A0 */
/* stock C02E20D8 / C02E20F0: r1 = channel, then the edge routine */
"    .type dial_edge_a, %function\n"
"dial_edge_a:\n"
"    mov     r1, #0\n"
"    b       dial_v6_irq\n"
"    .size dial_edge_a, . - dial_edge_a\n"
"    .type dial_edge_b, %function\n"
"dial_edge_b:\n"
"    mov     r1, #1\n"
"    b       dial_v6_irq\n"
"    .size dial_edge_b, . - dial_edge_b\n"
"    .thumb\n"
);

static u32 irq_off(void)
{
    u32 s;
    __asm__ volatile("mrs %0, cpsr\n\tcpsid i" : "=r"(s) :: "memory");
    return s;
}

static void irq_restore(u32 s)
{
    __asm__ volatile("msr cpsr_c, %0" :: "r"(s) : "memory");
}

int sup_entry(void *block, const struct sl_svc *svc, const char *path)
{
    (void)block; (void)path;
    volatile u32 *obj = (volatile u32 *)DIAL_OBJ;
    volatile u32 *vt = (volatile u32 *)VT_SLOTS;
    if (obj[1] != DIAL_VT) return SL_RELEASE;           /* not the object this was written for */

    u32 stock[3], neww[3];
    stock[0] = 0xC02E1D08u; stock[1] = 0xC02E20D8u; stock[2] = 0xC02E20F0u;
    /* adr, not C symbols: the labels stay local, so .text needs no relocation */
    __asm__("adr %0, dial_v6" : "=r"(neww[0]));
    __asm__("adr %0, dial_edge_a" : "=r"(neww[1]));
    __asm__("adr %0, dial_edge_b" : "=r"(neww[2]));
    neww[0] |= 1u;                                      /* the poll is Thumb */
    if (svc->claim(svc, VT_SLOTS, sizeof stock, stock, SL_EXCL) != SL_OK) return SL_RELEASE;

    u32 s = irq_off();
    obj[2] = 3; obj[3] = 0; obj[4] = 0; obj[5] = 4; obj[6] = 0;
    vt[0] = neww[0]; vt[1] = neww[1]; vt[2] = neww[2];
    volatile u32 *cfg = (volatile u32 *)EDGE_CFG;
    *cfg = *cfg | 0xFu;
    irq_restore(s);
    svc->publish(svc);
    return SL_KEEP;
}
