/* SensorLab's private stock-menu model. Resident, owned by the client sup. */
#ifndef SLM_STATE_H
#define SLM_STATE_H
#define SLM_ROWS 50u
#define SLM_TEXT 32u
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
};
#endif
