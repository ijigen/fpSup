#ifndef FPLOSSLESS_UI_CONTROL_H
#define FPLOSSLESS_UI_CONTROL_H
#include "control.h"
#define FPL_UI_MAGIC 0x4c535549u
#define FPL_PAGE_MAINB2 10u

struct fpl_ui {
    uint32_t magic, session, owner, generation, attached;
};
struct fpl_view {
    uint32_t visible, value, off_enabled, on_enabled, reason;
};

/* This is lifecycle policy, not native widget creation. The native adapter
 * must create a private named variable and row before setting binding_present.
 * It must call the stock attach/detach functions with unchanged arguments.
 * Events carry the generation captured on registration, never a freshly read
 * generation. A nonzero session token must not be reused while old callbacks
 * can survive (including warm resets); within it, generation tokens must not
 * be reused. The adapter must detach/drain callbacks before freeing their code.
 * Neither tokens nor event-queue draining are implemented by this policy core. */
void fpl_ui_boot(struct fpl_ui *ui, uint32_t session);
uint32_t fpl_ui_attach(struct fpl_ui *ui, uint32_t session, uint32_t page, uint32_t owner,
                       uint32_t generation, uint32_t cine, uint32_t binding_present);
uint32_t fpl_ui_detach(struct fpl_ui *ui, uint32_t session, uint32_t owner, uint32_t generation);
uint32_t fpl_ui_select(struct fpl_ui *ui, uint32_t session, uint32_t owner, uint32_t generation,
                       struct fpl_state *state, const struct fpl_context *context,
                       uint32_t confirmed_value);
/* Explicit output pointer: ui/state/context/view use r0/r1/r2/r3 on ARM. */
void fpl_ui_view(const struct fpl_ui *ui, const struct fpl_state *state,
                 const struct fpl_context *context, struct fpl_view *view);
#endif
