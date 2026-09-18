#include "ui_control.h"

static uint32_t current(const struct fpl_ui *ui, uint32_t session, uint32_t owner, uint32_t gen) {
    return ui && ui->magic == FPL_UI_MAGIC && session && ui->session == session &&
           ui->attached == 1 && owner && gen &&
           ui->owner == owner && ui->generation == gen;
}

void fpl_ui_boot(struct fpl_ui *ui, uint32_t session) {
    if (!ui) return;
    ui->magic = session ? FPL_UI_MAGIC : 0;
    ui->session = session;
    ui->owner = 0;
    ui->generation = 0;
    ui->attached = 0;
}

uint32_t fpl_ui_attach(struct fpl_ui *ui, uint32_t session, uint32_t page, uint32_t owner,
                       uint32_t gen, uint32_t cine, uint32_t present) {
    if (!ui || ui->magic != FPL_UI_MAGIC || !session || ui->session != session ||
        !owner || !gen) return FPL_INVALID;
    if (page != FPL_PAGE_MAINB2 || cine != 1 || present != 1) return FPL_UNSUPPORTED;
    if (ui->attached) return current(ui, session, owner, gen) ? FPL_OK : FPL_BUSY;
    ui->owner = owner;
    ui->generation = gen;
    ui->attached = 1;
    return FPL_OK;
}

uint32_t fpl_ui_detach(struct fpl_ui *ui, uint32_t session, uint32_t owner, uint32_t gen) {
    if (!current(ui, session, owner, gen)) return FPL_INVALID;
    ui->attached = 0;
    ui->owner = 0;
    ui->generation = 0;
    return FPL_OK;
}

uint32_t fpl_ui_select(struct fpl_ui *ui, uint32_t session, uint32_t owner, uint32_t gen,
                       struct fpl_state *state, const struct fpl_context *context,
                       uint32_t value) {
    if (!current(ui, session, owner, gen)) return FPL_INVALID;
    if (!context || context->cine != 1) return FPL_UNSUPPORTED;
    /* Only an explicit confirmation reaches this function, not highlight or
     * animation events. This calls no firmware setting setter or codec. */
    return fpl_set(state, value, context);
}

void fpl_ui_view(const struct fpl_ui *ui, const struct fpl_state *s,
                 const struct fpl_context *context, struct fpl_view *out) {
    struct fpl_view view = {0, 0, 0, 0, FPL_INVALID};
    if (!out) return;
    *out = view;
    if (!ui || !current(ui, ui->session, ui->owner, ui->generation) || !context ||
        context->cine != 1 || !s || s->magic != FPL_MAGIC || s->abi != FPL_ABI ||
        s->requested > 1 || s->clip > FPL_STOP || s->reserved0 || s->reserved1)
        return;
    view.visible = 1;
    view.value = fpl_menu_value(s); /* preference, not proof of encoded frames */
    if (s->clip != FPL_IDLE) {
        view.reason = FPL_BUSY;
        *out = view;
        return;
    }
    view.off_enabled = 1;
    view.reason = s->fault ? FPL_FAULT : fpl_can_enable(context);
    view.on_enabled = view.reason == FPL_OK;
    *out = view;
}
