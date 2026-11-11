/* camera timing entry for jfit.c (projects/lut-sup/probes/bench/jfit_bench_run.py): the host fills every
 * pointer (work in the pool), this runs jf_fit once and stores the elapsed microseconds. */
#include "../jfit.c"
struct jfit_bench { struct jfit J; uint32_t us, pad[3]; };
__attribute__((used)) uint32_t jfit_bench(struct jfit_bench *b) {
    typedef uint32_t (*tick_fn)(void);
    tick_fn tick = (tick_fn)0xC002B6E0u;
    uint32_t t0 = tick();
    jf_fit(&b->J);
    b->us = tick() - t0;
    return b->us;
}
