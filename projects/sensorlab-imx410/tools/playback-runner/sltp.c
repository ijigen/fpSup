/* Fixed, autonomous playback trial. Loader v4 owns this entire resident block.
 * No hooks, DMA, recorder controls, arbitrary commands or external pointers.
 * Arm only from externally confirmed CINE live-view idle, then leave USB quiet.
 * The CINE/record flags below are an additional gate, not a GUI idle oracle. */
#include "sloader4.h"
typedef uint32_t u32;
#define W(a) (*(volatile u32 *)(uintptr_t)(a))
#define B(a) (*(volatile uint8_t *)(uintptr_t)(a))
#define USED __attribute__((used,noinline))
#define ID 0x50544C53u
#define MAGIC 0x31505453u
#define TASK_CREATE 0xC0016A58u
#define TASK_START 0xC0016BC0u
#define SLEEP_MS 0xC03705D8u
#define TICK_US 0xC002B6E0u
#define SHELL_EXEC 0xC03D9C20u
#define SHELL_CTX 0xC3756904u
#define SETTINGS_GET 0xC0057AE8u
#define IS_CINE 0xC0058340u
#define GAP_US 800000u
#define ARM_US 2000000u
#define SETTLE_US 2000000u
#define OBSERVE_US 3000000u
#define EXIT_US 10000000u

enum { IDLE=0, ARM_WAIT, PLAY_HELD, PLAY_SETTLE, OK_HELD, OBSERVE,
       S1_HELD, EXIT_WAIT, DONE, REJECTED, INIT_FAILED };
enum { E_NONE=0, E_MODE, E_NOT_CINE, E_BUSY, E_ACTIVE, E_CREATE, E_START };
enum { K_PLAY_ON=1, K_PLAY_OFF, K_OK_ON, K_OK_OFF, K_S1_ON, K_S1_OFF };
struct event { u32 key, entered_us, returned_us, rc; };
struct state {
    u32 magic, version;
    volatile u32 req_mode, req_seq;             /* only host inputs; write seq last */
    u32 seen_seq, active_seq, done_seq, phase;
    u32 mode, error, reject_seq, reject_error;
    u32 task_id, task_rc, accepted_us, phase_us, done_us;
    u32 n_events, cine_at_arm, busy_at_arm;
    struct event event[6];
};

static u32 now(void) { return ((u32 (*)(void))TICK_US)(); }
__attribute__((noinline)) static u32 context_word(void)
{
    u32 at;
    __asm__ volatile("adr %0, 1f\n\tb 2f\n\t.balign 4\n1:\t.word 0\n2:" : "=r"(at));
    return at;
}
static struct state *context(void) { return (struct state *)(uintptr_t)W(context_word()); }
static u32 is_cine(void)
{
    return ((u32 (*)(u32))IS_CINE)(((u32 (*)(void))SETTINGS_GET)()) == 1u;
}
static u32 busy(void)
{
    u32 sel = W(0xC347D1D4u) == 0x21u ? 0xC3476609u : 0xC347E08Fu;
    return B(sel) || W(0xC358E140u) || B(0xC35A952Cu);
}
static u32 gate(struct state *s)
{
    s->cine_at_arm = is_cine(); s->busy_at_arm = busy();
    return !s->cine_at_arm ? E_NOT_CINE : s->busy_at_arm ? E_BUSY : E_NONE;
}
static void phase(struct state *s, u32 p) { s->phase_us = now(); s->phase = p; }
static void key(struct state *s, u32 k)
{
    /* Mutable, bounded string on this task's stack: stock executor tokenises it. */
    volatile u32 line[4];
    line[0] = 0x2079656Bu; line[1] = line[2] = line[3] = 0;
    switch (k) {
    case K_PLAY_ON: line[1]=0x59414C50u; line[2]=0x00004E4Fu; break;
    case K_PLAY_OFF: line[1]=0x59414C50u; line[2]=0x0046464Fu; break;
    case K_OK_ON: line[1]=0x4E4F4B4Fu; break;
    case K_OK_OFF: line[1]=0x464F4B4Fu; line[2]=0x46u; break;
    case K_S1_ON: line[1]=0x4E4F3153u; break;
    case K_S1_OFF: line[1]=0x464F3153u; line[2]=0x46u; break;
    default: return;
    }
    if (s->n_events >= 6u) return;
    struct event *e = &s->event[s->n_events++];
    e->key=k; e->entered_us=now(); e->returned_us=0;
    e->rc=((u32 (*)(u32,char *))SHELL_EXEC)(SHELL_CTX,(char *)line);
    e->returned_us=now();
}

/* One bounded iteration; only the task calls this on-camera. Exported symbol
 * permits real ARM execution in the offline harness without an infinite loop. */
static USED void sltp_step(void)
{
    struct state *s=context();
    u32 q=s->req_seq, m=s->req_mode, active=s->phase>=ARM_WAIT && s->phase<=EXIT_WAIT;
    if (q && (int32_t)(q-s->seen_seq)>0 && q==s->req_seq) {
        s->seen_seq=q;
        if (active) { s->reject_seq=q; s->reject_error=E_ACTIVE; }
        else {
            u32 error = m!=1u && m!=2u ? E_MODE : gate(s);
            s->error=error;
            if (error) { s->reject_seq=q; s->reject_error=error; s->phase=REJECTED; }
            else {
                s->active_seq=q; s->mode=m; s->n_events=0;
                for (u32 i=0; i<6u; i++) {
                    s->event[i].key=s->event[i].entered_us=s->event[i].returned_us=s->event[i].rc=0;
                }
                s->accepted_us=now(); phase(s,ARM_WAIT);
            }
        }
    }
    u32 elapsed=now()-s->phase_us;
    switch (s->phase) {
    case ARM_WAIT:
        if (elapsed<ARM_US) return;
        s->error=gate(s);                       /* camera could change during the quiet window */
        if (s->error) { s->phase=REJECTED; s->reject_seq=s->active_seq; s->reject_error=s->error; return; }
        key(s,K_PLAY_ON); phase(s,PLAY_HELD); return;
    case PLAY_HELD:
        if (elapsed<GAP_US) return;
        key(s,K_PLAY_OFF); phase(s,PLAY_SETTLE); return;
    case PLAY_SETTLE:
        if (elapsed<SETTLE_US) return;
        if (s->mode==2u) { key(s,K_OK_ON); phase(s,OK_HELD); }
        else phase(s,OBSERVE);
        return;
    case OK_HELD:
        if (elapsed<GAP_US) return;
        key(s,K_OK_OFF); phase(s,OBSERVE); return;
    case OBSERVE:
        if (elapsed<OBSERVE_US) return;
        key(s,K_S1_ON); phase(s,S1_HELD); return;
    case S1_HELD:
        if (elapsed<GAP_US) return;
        key(s,K_S1_OFF); phase(s,EXIT_WAIT); return;
    case EXIT_WAIT:
        if (elapsed<EXIT_US) return;
        s->done_us=now(); s->done_seq=s->active_seq; s->phase=DONE; return;
    default: return;
    }
}
static USED void sltp_task(void)
{
    for (;;) { sltp_step(); ((void (*)(u32))SLEEP_MS)(20u); }
}

USED int sup_entry(void *block, const struct sl_svc *svc, const char *path)
{
    (void)path;
    const struct sl4_header *h=(const struct sl4_header *)block;
    u32 off=(h->file_len+63u)&~63u;
    if (svc->version<5u || h->magic!=SL4_MAGIC || off<h->file_len ||
        h->block_size<off || h->block_size-off<sizeof(struct state)) return SL_RELEASE;
    struct state *s=(struct state *)((uint8_t *)block+off);
    for (u32 i=0; i<sizeof(*s)/4u; i++) ((u32 *)s)[i]=0;
    s->magic=MAGIC; s->version=1u;
    if (svc->provide(svc,ID,s)!=SL_OK) return SL_RELEASE;
    W(context_word())=(u32)(uintptr_t)s;
    svc->publish(svc);
    volatile u32 d[8];
    d[0]=0; d[1]=0x41u; d[2]=(u32)(uintptr_t)sltp_task; d[3]=25u;
    d[4]=0x2000u; d[5]=ID; d[6]=0; d[7]=0;
    int id=((int (*)(volatile u32 *))TASK_CREATE)(d);
    if (id<1) { s->error=E_CREATE; s->task_rc=(u32)id; s->phase=INIT_FAILED; return SL_KEEP; }
    s->task_id=(u32)id;
    int rc=((int (*)(int,u32))TASK_START)(id,0u);
    s->task_rc=(u32)rc;
    if (rc) { s->error=E_START; s->phase=INIT_FAILED; }
    return SL_KEEP;                             /* task/provided state retain their own block */
}
