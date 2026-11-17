/* SensorLab's private stock-menu model. Resident, owned by the client sup. */
#ifndef SLM_STATE_H
#define SLM_STATE_H
#define SLM_ROWS 50u
#define SLM_TEXT 32u
#define SLM_LVTEXT 192u       /* seven images, at most 25 characters each ("<!font_S_kigou_01,BOTTOM>") */
struct slm_row {
    uint32_t a, b, enabled, custom;
    char text[SLM_TEXT];
};
struct slm_state {
    uint32_t ready, attempted, result, updates, picks, rejected, opened, go;
    uint32_t count[3], current[3], sent[3], sending, bank;
    uintptr_t desc[3], reader;
    struct slm_row row[3][SLM_ROWS];
    char summary[2][3][SLM_TEXT];
    uint32_t owed;            /* v0.7.1test: picks recorded in a change event, applied at the next leave() */
    /* 0.0.7test: the live view's frame rate (slm_lv_page.py), SLM_LvFpsS / SLM_LvFpsM -- the rate as the stock digit
     * images.  lv_result is fpui_stock_apply's; lv_on is 1 once both variables exist and the two pages are ours. */
    uint32_t lv_result, lv_on, lv_bank, lv_posts;
    char lvfps[2][2][SLM_LVTEXT];
};
#endif
