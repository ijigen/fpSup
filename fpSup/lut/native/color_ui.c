/* The LUT manager and a cube's settings: one FT4S file, two pages (color_ui.py).
 *
 * FT_LUTMGR is v4 SupManager's page, driven the way RES-Custom drives its file
 * list (ogc_files.c rv_*; user 2026-10-25: "完全參考 RES-Custom"): every cube
 * with the stock On / Off, the title "LUT (on/cap)", the footer fixed, and a
 * text or flag posted only when it changes -- every post is another GUI update
 * pass (the earlier private page posted all six slots' twelve words on every
 * focus move and lagged).  AEL on Root's CommonSystemKeyEvent sets LC_Key = 80
 * and opens the focused cube's FT_LUTSET by the firmware's own transition
 * (LC_Go's change event, fp-native-ui 8j).  MENU there comes back to that cube.
 *
 * Variable numbers are color_ui.variables()'s order: supmgr.c's (MV_* below,
 * RC_VISIBLE 5 rows a page), then the settings page's. */
#define MV_ROWS         5u
#define MV_SLOTS        (MV_ROWS + 1u)
#define MV_TABS         7u
enum { MP_RED, MP_GREEN, MP_NAME, MP_GREY, MP_VER };
#define MV_KEY          0u
#define MV_OK           1u
#define MV_PART(p, k)   (2u + (p) * MV_ROWS + (k) - 1u)
#define MV_PAGE         (2u + 5u * MV_ROWS)
#define MV_VERSION      (MV_PAGE + 1u)
#define MV_VISIBLE      (MV_VERSION + 1u)
#define MV_LOCK         (MV_VISIBLE + MV_ROWS)
#define MV_SELECTED     (MV_LOCK + MV_ROWS)
#define MV_MORE         (MV_SELECTED + MV_ROWS)
#define MV_DEFAULT      (MV_MORE + MV_ROWS)
#define MV_CHOICE       (MV_DEFAULT + MV_ROWS)
#define MV_FOCUS        (MV_CHOICE + MV_ROWS)
#define MV_RIGHT_FOOTER (MV_FOCUS + 3u)
#define MV_VERSION_X    (MV_RIGHT_FOOTER + 1u)
#define MV_TABS_AT      (MV_VERSION_X + MV_ROWS)
#define MV_X0           (MV_TABS_AT + 4u * MV_TABS)
#define MV_TITLE        (MV_X0 + 12u)
#define MV_ROW0         (MV_X0 + 13u)
#define MV_HEAD         (MV_X0 + 14u)
#define MV_TOFF         (MV_X0 + 15u)
#define MV_TON          (MV_TOFF + MV_SLOTS)
#define MV_GSHOW        (MV_TON + MV_SLOTS)
#define MV_RSHOW        (MV_GSHOW + MV_SLOTS)
#define MV_HEADER       (MV_RSHOW + MV_SLOTS)
/* color_ui.variables(): the settings page's */
enum { MV_PAGE_TITLE = MV_HEADER + 1u, MV_SROW0, MV_SPACE_V, MV_SPACE_SUB, MV_BACK, MV_GAMMA_V,
       MV_GAMMA_SUB, MV_GAMMA_X, MV_ZERO, MV_GAMMA_M, MV_SPACE_T, MV_GAMMA_T, MV_ROWID0,
       MV_GO = MV_ROWID0 + 6u, MV_MATRIX_V, MV_MATRIX_X, MV_MATRIX_M, MV_MATRIX_T,
       MV_BUSY, MV_CLOCK0, MV_CHART = MV_CLOCK0 + 3u,      /* conv.c: the converting overlay, its hourglass */
       MV_BAR, MV_MATCH, MV_PATCH0,                        /* conv.c conv_chart: the ColorChecker (manager_page.checker_chart) */
       MV_CHART_T = MV_PATCH0 + 48u,                       /* the settings page's "Color chart" row: its text (conv_view) */
       MV_COUNT };
_Static_assert(MV_COUNT <= sizeof(((struct lut4_state *)0)->ui_cache) / sizeof(u32),
               "ui_cache too small for MV_COUNT: mv_int/mv_str/mv_forget would write past it into struct lut_cols");
/* color_ui.TEXTS */
enum { T_BLANK, T_FOOTER, T_POPUP, T_PAGE_HINT, T_FULL, T_WRITE, T_BUSY, T_NONE, T_PAGE, T_AEL,
       T_SETUP, T_GO, T_TITLE, T_BACK, T_AGAIN, T_NOCOLS, T_NOROW, T_COUNT };
#define MV_HEADER_FOCUS 3451u
#define MV_TAB_FOCUS    55u
#define AEL_KEY         80u
#define MENU_NOTICE     70u
#define CHART_KEY       81u                /* the settings page's "Color chart" row: OK / Right (settings_y51.CHART_KEY) */
/* How many LUTs may be on (Bei 2026-11-10): COL-Share's room for us -- 12 minus the other clients' rows
 * (RAW-View's one: 11) -- cols.c lut_room.  "LUT (on/room)" in the title; On past it says "List full". */
static u32 lut_room(struct lut4_state *s);
static u32 lc_row_of(struct lut4_state *s, u32 i);
#define SETTINGS_PAGE   "FT_LUTSET"
enum { R_NONE, R_FULL, R_WRITE, R_BUSY, R_SETUP, R_CONV, R_CONVERTED, R_CONVFAIL };   /* conv.c: running, its result */
/* conv.c (included after this file) */
#define CONV_DONE_KEY 90u                  /* LC_Key from the conversion worker: its job is done */
static int conv_ok(struct lut4_state *s,u32 i);
static int conv_start(struct lut4_state *s,u32 i);
static int conv_finish(struct lut4_state *s);
static u32 conv_row(struct lut4_state *s,u32 i,u32 slot);
static const char *conv_vtext(struct lut4_state *s,u32 slot);
static const char *conv_title(struct lut4_state *s,u32 i,const char *name);
static u32 conv_view(struct lut4_state *s,u32 i);
static int conv_chart_up(struct lut4_state *s);

/* The firmware calls UI callbacks with sp = 4 mod 8 (fp-firmware-call; the
 * harness does too): every entry runs its body on an 8-aligned stack, so the
 * firmware's file / dir functions it reaches see what AAPCS promises. */
static u32 aligned_call(u32 (*fn)(uintptr_t),uintptr_t arg) {
    u32 r;
    __asm__ volatile("mov r4, sp\n\tbic r5, r4, #7\n\tmov sp, r5\n\tmov r0, %2\n\tblx %1\n\tmov sp, r4\n\tmov %0, r0"
                     : "=r"(r) : "r"(fn), "r"(arg) : "r0","r1","r2","r3","r4","r5","r12","lr","cc","memory");
    return r;
}
static void cols_sync(struct lut4_state *s);   /* cols.c / COL-Share: the COLOR list's rows to the cubes on */
/* The callbacks get only a descriptor: the state is a word in the code (writable at
 * the cached alias), next to the one function that reaches it (ogc_files.c rc_ctx). */
__attribute__((noinline)) static u32 color_ctx_at(void) {
    u32 at;
    __asm__ volatile("adr %0, 1f\n\tb 2f\n\t.balign 4\n1:\t.word 0\n2:" : "=r"(at));
    return at;
}
static struct lut4_state *color_ctx(void) { return (struct lut4_state *)(uintptr_t)*(volatile u32 *)(uintptr_t)color_ctx_at(); }
static const char *ctext(struct lut4_state *s,u32 i) { return fpui_text(s->ui,i); }

static u32 mv_n(struct lut4_state *s) { return s->library?s->library->h.count:0; }
static int mv_paged(struct lut4_state *s) { return mv_n(s)>MV_SLOTS; }
static u32 mv_pages(struct lut4_state *s) { return mv_paged(s)?1u+(mv_n(s)-1u)/MV_ROWS:1u; }
/* the cube in slot k, or -1: six or fewer fill slots 0..5, more page five at a time in 1..5 */
static int mv_cube(struct lut4_state *s,u32 k) {
    u32 i=k;
    if(k>=MV_SLOTS)return -1;
    if(mv_paged(s)){if(!k)return -1;i=s->ui_page*MV_ROWS+k-1u;}
    return i<mv_n(s)?(int)i:-1;
}
static u32 mv_slot_of(struct lut4_state *s,u32 i) {
    if(!mv_paged(s))return i;
    s->ui_page=i/MV_ROWS;return i%MV_ROWS+1u;
}
static u32 mv_vpart(u32 p,u32 k) { return k?MV_PART(p,k):MV_X0+p; }
static u32 mv_vslot(u32 group,u32 k) {
    if(group==MV_VERSION_X)return k?MV_VERSION_X+k-1u:MV_X0+11u;
    return k?group+k-1u:MV_X0+5u+(group-MV_VISIBLE)/MV_ROWS;
}
static int mv_ready(const struct lib_entry *e) { return (e->flags&LIB_READY)==LIB_READY && supported(e->color,e->gamma); }
/* On as the manager shows it: enabled, set up and converted (user 11-05: "如果.cube沒有轉譯過，他應該就要是off");
 * an enabled cube whose .JFT is gone (or whose settings changed) shows Off, and On converts it again.  Display
 * only: the library's flag is left as it is (nothing written at open), the COLOR list already skips it. */
static int mv_on(struct lut4_state *s,u32 i) {
    const struct lib_entry *e=&s->library->entries[i];
    return (e->flags&1u) && mv_ready(e) && conv_ok(s,i);
}
static u32 mv_used(struct lut4_state *s) {
    u32 used=0;for(u32 i=0;i<mv_n(s);i++)if(mv_on(s,i))used++;
    return used;
}
/* On, but no COLOR row for it: a client came later and took rows (list order: the last ones wait) */
static int mv_norow(struct lut4_state *s,u32 i) { return s->cols.attached && mv_on(s,i) && !lc_row_of(s,i); }

/* Post only what changed: a cache word per variable we post often (+1, 0 = never posted). */
static void mv_int(struct lut4_state *s,u32 i,u32 v) {
    if(i<MV_COUNT && s->ui_cache[i]==v+1u)return;
    if(i<MV_COUNT)s->ui_cache[i]=v+1u;
    fpui_set(s->ui,i,v);
}
static void mv_str(struct lut4_state *s,u32 i,const char *t) {
    u32 key=(u32)(uintptr_t)t;
    if(i<MV_COUNT && s->ui_cache[i]==key)return;
    if(i<MV_COUNT)s->ui_cache[i]=key;
    fpui_set_text(s->ui,i,t);
}
static void mv_forget(struct lut4_state *s) { for(u32 i=0;i<MV_COUNT;i++)s->ui_cache[i]=0; }

static u32 mv_num(char *p,u32 v) {
    char t[10];u32 n=0;do{t[n++]=(char)('0'+v%10u);v/=10u;}while(v);
    for(u32 i=0;i<n;i++)p[i]=t[n-1u-i];
    return n;
}
static u32 mv_tab(struct lut4_state *s,u32 i) {
    u32 n=mv_pages(s);if(n>MV_TABS)n=MV_TABS;
    u32 width=n==2u?512u:n==3u?341u:n==4u?256u:n==5u?204u:n==6u?170u:146u;
    u32 group=(i-MV_TABS_AT)/MV_TABS,k=(i-MV_TABS_AT)%MV_TABS;
    return group==0u?mv_paged(s)&&k<n:group==1u?k==s->ui_page:group==2u?width*k
         :k+1u==n?1024u-width*k:width;
}
static int conv_running(struct lut4_state *s);
static void conv_busy(struct lut4_state *s,int on);
static void conv_chart_close(struct lut4_state *s);
static const char *conv_hint(struct lut4_state *s);
static void mv_hint(struct lut4_state *s) {
    const char *c=conv_hint(s);
    if(c){fpui_set_text(s->ui,MV_OK,c);s->ui_cache[MV_OK]=0;return;}   /* progress / match / failed: always posted */
    u32 t=s->ui_result==R_FULL?T_FULL:s->ui_result==R_BUSY?T_BUSY:s->ui_result==R_WRITE?T_WRITE
         :s->ui_result==R_SETUP?T_SETUP:s->ui_popup?T_POPUP:!s->cols.attached?T_NOCOLS   /* no COLOR rows: why (Bei 11-07 #2) */
         :mv_paged(s)?T_PAGE_HINT:T_FOOTER;
    mv_str(s,MV_OK,ctext(s,t));
}

/* The manager: everything it shows (rv_refresh's words on v4's slots). */
static void manager_refresh(struct lut4_state *s) {
    u32 n=mv_n(s),used=mv_used(s);
    if(s->ui_page>=mv_pages(s))s->ui_page=0;
    const char *head=ctext(s,T_TITLE);u32 at=0;                    /* "LUT (on/cap)" */
    while(head[at] && at<12u){s->ui_title[at]=head[at];at++;}
    at+=mv_num(s->ui_title+at,used);s->ui_title[at++]='/';at+=mv_num(s->ui_title+at,lut_room(s));
    s->ui_title[at++]=')';s->ui_title[at]=0;
    fpui_set_text(s->ui,MV_HEADER,s->ui_title);s->ui_cache[MV_HEADER]=0;   /* same buffer, new words */
    char *p=s->ui_pager;
    if(mv_pages(s)<=1u){p[0]=' ';p[1]=0;}
    else {at=mv_num(p,s->ui_page+1u);p[at++]=' ';p[at++]='/';p[at++]=' ';at+=mv_num(p+at,mv_pages(s));p[at]=0;}
    fpui_set_text(s->ui,MV_PAGE,p);s->ui_cache[MV_PAGE]=0;
    mv_str(s,MV_VERSION,ctext(s,T_BLANK));
    mv_str(s,MV_RIGHT_FOOTER,ctext(s,n?T_AEL:T_BLANK));
    for(u32 i=MV_TABS_AT;i<MV_X0;i++)mv_int(s,i,mv_tab(s,i));
    mv_int(s,MV_TITLE,(u32)mv_paged(s));
    /* send order (sigmafp-re-33 11-10, as loader-v4/supmgr.c refresh): rows to show get MV_VISIBLE=1 before
     * their texts; rows to hide get MV_VISIBLE=0 last -- otherwise a row hidden on one page does not come back. */
    for(u32 k=0;k<MV_SLOTS;k++)
        if(mv_cube(s,k)>=0||(!n&&!k))mv_int(s,mv_vslot(MV_VISIBLE,k),1u);
    for(u32 k=0;k<MV_SLOTS;k++) {
        int f=mv_cube(s,k);u32 none=!n&&!k;
        const struct lib_entry *e=f>=0?&s->library->entries[f]:0;
        u32 on=e && mv_on(s,(u32)f),ready=e && mv_ready(e),norow=on && mv_norow(s,(u32)f);
        u32 score=on?conv_row(s,(u32)f,k):1u;                  /* match % + 1 (on: converted) */
        for(u32 pp=MP_RED;pp<=MP_VER;pp++) {
            const char *t=!e?(none&&pp==MP_GREY?ctext(s,T_NONE):ctext(s,T_BLANK))
                :pp==MP_NAME?(on?e->name:ctext(s,T_BLANK)):pp==MP_GREY?(on?ctext(s,T_BLANK):e->name)
                :pp==MP_RED?(!ready?string(s,53):norow?ctext(s,T_NOROW):ctext(s,T_BLANK))   /* "Setup required" (not converted: plain Off) */
                :pp==MP_VER && score>1u && k<6u?conv_vtext(s,k):ctext(s,T_BLANK);
            mv_str(s,mv_vpart(pp,k),t);
        }
        mv_int(s,MV_TOFF+k,e && !on);mv_int(s,MV_TON+k,!!on);
        mv_int(s,MV_GSHOW+k,(e && !on)||none);mv_int(s,MV_RSHOW+k,e && (!ready || norow));
        mv_int(s,mv_vslot(MV_LOCK,k),!e);
        mv_int(s,mv_vslot(MV_MORE,k),0);
        mv_int(s,mv_vslot(MV_DEFAULT,k),e && !on);
        mv_int(s,mv_vslot(MV_SELECTED,k),e && !on);
        mv_int(s,mv_vslot(MV_VERSION_X,k),49u);
    }
    for(u32 k=0;k<MV_SLOTS;k++)
        if(!(mv_cube(s,k)>=0||(!n&&!k)))mv_int(s,mv_vslot(MV_VISIBLE,k),0u);
    mv_hint(s);
}

/* The settings page: its title, the values, the Gamma list's variant (Blackmagic)
 * and last row, the value texts ("Setup required" until the cube has one). */
static void settings_refresh(struct lut4_state *s) {
    struct lib_entry *e=edited(s);if(!e)return;
    u32 bmd=e->color==2u;
    const char *title=conv_title(s,s->edit_index,e->name);   /* + "75% match" when converted */
    if(title!=e->name)s->ui_cache[MV_PAGE_TITLE]=0;           /* one buffer for every cube: post it again */
    mv_str(s,MV_PAGE_TITLE,title);
    mv_int(s,MV_SPACE_V,e->color);mv_int(s,MV_GAMMA_V,e->gamma);
    mv_int(s,MV_GAMMA_X,bmd);mv_int(s,MV_GAMMA_M,bmd?1u:5u);
    mv_str(s,MV_SPACE_T,e->flags&LIB_SPACE?s->colors[e->color<8u?e->color:0u]:string(s,53));
    mv_str(s,MV_GAMMA_T,e->flags&LIB_GAMMA?(bmd?s->blackmagic[e->gamma&1u]:s->common[e->gamma<6u?e->gamma:0u])
           :string(s,53));
    /* the matrix row: Custom listed only with the author's matrices (LC_MATRIX_C) */
    u32 custom=!!(e->author_flags&AUTH_CUSTOM);
    mv_int(s,MV_MATRIX_V,e->matrix<MAT_N?e->matrix:MAT_STANDARD);
    mv_int(s,MV_MATRIX_X,custom);mv_int(s,MV_MATRIX_M,custom?2u:1u);
    mv_str(s,MV_MATRIX_T,e->flags&LIB_MATRIX?string(s,115u+(e->matrix<MAT_N?e->matrix:0u)):string(s,53));
}

/* The author's choice in each list gets a mark (user 2026-11-03: a star, else *), written into
 * the list models before the settings page is built: the stock in-place model
 * update Sensor Lab runs on the camera (projects/open-gate/build/sl_menu/sl_modes.c),
 * the cell writes only -- the rows stay.  Each step is checked; a model whose
 * interface is not modelCSV's, or whose rows differ, is left as the pack has it. */
#define M_GUI_OBJECT 0xC37B7048u
#define M_W_ROWS     0xC05F4861u
#define M_W_CURRENT  0xC05F4879u
#define M_W_STRING   0xC05F4929u
#define M_W_INSERT   0xC05F4941u
#define M_W_DELETE   0xC05F4959u
typedef u32 (*m_fn1)(uintptr_t);
typedef u32 (*m_fn2)(uintptr_t,uintptr_t);
typedef u32 (*m_fn3)(uintptr_t,uintptr_t,uintptr_t);
#define M_PEEK(a) (*(volatile const u32 *)(uintptr_t)(a))
/* the model's name as words on the stack: a string literal's address would be a
 * .text relocation (this build has no linker), as Sensor Lab's SL_MODE */
static u32 model_texts(u32 w0,u32 w1,u32 w2,const char *const *labels,u32 n,u32 mark) {
    uintptr_t app=M_PEEK(M_GUI_OBJECT),res=0,inst=0,iface=0;u32 have=0,rows=0,arg[1];
    char text[64];volatile u32 nw[4];nw[0]=w0;nw[1]=w1;nw[2]=w2;nw[3]=0;
    const char *name=(const char *)nw;
    if(!app || ((m_fn3)0xC05E0321u)(app,(uintptr_t)name,(uintptr_t)&res) || !res)return 1;
    if(((m_fn2)0xC05D8BD9u)(res,(uintptr_t)&have))return 2;
    if(!have && ((m_fn1)0xC05D8B79u)(res))return 3;
    if(((m_fn2)0xC05D8BF9u)(res,(uintptr_t)&inst) || !inst)return 4;
    if(((m_fn2)0xC05D8359u)(inst,(uintptr_t)&iface) || !iface || (iface&3u))return 5;
    if(M_PEEK(iface+0x14u)!=M_W_ROWS || M_PEEK(iface+0x18u)!=M_W_CURRENT || M_PEEK(iface+0x30u)!=M_W_STRING ||
       M_PEEK(iface+0x34u)!=M_W_INSERT || M_PEEK(iface+0x38u)!=M_W_DELETE)return 6;
    if(((m_fn2)(uintptr_t)M_PEEK(iface+0x14u))(inst,(uintptr_t)&rows) || rows!=n)return 7;
    for(u32 r=0;r<n;r++) {
        u32 k=0;const char *l=labels[r];
        while(l && l[k] && k<56u){text[k]=l[k];k++;}
        /* '*': the menu font has no U+2605 (2026-11-03 camera: "Rec.709 ?"); the
         * user's fallback when the star cannot be drawn */
        if(r==mark){text[k++]=' ';text[k++]='*';}
        text[k]=0;
        ((m_fn2)(uintptr_t)M_PEEK(iface+0x18u))(inst,r);
        if(((m_fn3)(uintptr_t)M_PEEK(iface+0x30u))(inst,1u,(uintptr_t)text))return 8;   /* column 1: TEXT */
    }
    arg[0]=1u;
    return ((m_fn2)0xC05D83A9u)(inst,(uintptr_t)arg)?9u:0u;
}
static void mark_lists(struct lut4_state *s) {
    struct lib_entry *e=edited(s);if(!e)return;
    u32 a=e->author_flags,ac=a&LIB_SPACE?e->author_color:LIB_NONE,ag=a&LIB_GAMMA?e->author_gamma:LIB_NONE;
    u32 am=a&LIB_MATRIX?e->author_matrix:LIB_NONE;
    const char *mats[3]={string(s,115),string(s,116),string(s,117)};
    s->ui_marks=model_texts(0x535F434Cu,0x45434150u,0u,s->colors,8,ac);
    s->ui_marks|=model_texts(0x475F434Cu,0x414D4D41u,0u,s->common,6,ag<6u?ag:LIB_NONE)<<4;
    s->ui_marks|=model_texts(0x475F434Cu,0x414D4D41u,0x444D425Fu,s->blackmagic,2,ag!=LIB_NONE && ag>=6u?ag-6u:LIB_NONE)<<8;
    s->ui_marks|=model_texts(0x4D5F434Cu,0x49525441u,0x58u,mats,2,am)<<12;
    s->ui_marks|=model_texts(0x4D5F434Cu,0x49525441u,0x435F58u,mats,3,am)<<16;
}

static void color_ui_refresh(struct lut4_state *s) {
    if(!s->ui)return;
    if(s->ui_view==VIEW_SETTINGS)settings_refresh(s);else manager_refresh(s);
}

static void mv_focus(struct lut4_state *s,u32 focus) {
    s->ui_focus=focus;s->ui_header=focus==MV_HEADER_FOCUS && mv_paged(s);
    fpui_set(s->ui,MV_FOCUS,focus);s->ui_cache[MV_FOCUS]=0;
}

/* T_BACK: the request LC_Back's change event sends.  Empty except between
 * MENU and the return, so the event's first run, when the settings page is
 * built, asks for nothing (it made the page leave at once, diagL). */
static void back_request(struct lut4_state *s,const char *req) {
    char *t=(char *)fpui_text(s->ui,T_BACK);if(!t)return;
    for(u32 j=0;;j++){t[j]=req[j];if(!req[j])break;}
}

/* AEL: the focused cube's settings -- its variables, then its name, then LC_Go. */
static void open_settings(struct lut4_state *s,u32 index) {
    s->edit_index=index;s->ui_back_page=s->ui_page;s->ui_view=VIEW_SETTINGS;s->ui_popup=0;s->ui_result=R_NONE;
    choices(s);
    mv_int(s,MV_TITLE,0);mv_str(s,MV_PAGE,ctext(s,T_BLANK));mv_str(s,MV_RIGHT_FOOTER,ctext(s,T_BLANK));
    for(u32 i=MV_TABS_AT;i<MV_TABS_AT+MV_TABS;i++)mv_int(s,i,0);
    mv_str(s,MV_OK,ctext(s,T_FOOTER));
    mv_str(s,MV_CHART_T,ctext(s,T_BLANK));
    settings_refresh(s);
    mv_focus(s,fpui_first(s->ui,MV_SROW0));
    back_request(s,"");
    mark_lists(s);
    char *go=(char *)fpui_text(s->ui,T_GO);const char *page=SETTINGS_PAGE;
    if(!go)return;
    for(u32 j=0;;j++){go[j]=page[j];if(!page[j])break;}
    fpui_set(s->ui,MV_GO,++s->ui_goseq);
}

static u32 color_key_body(uintptr_t desc) {
    struct lut4_state *s=color_ctx();if(!s || !s->ui)return 0;u32 key=fpui_value(desc);
    if(!key)return 0;
    if(conv_finish(s) || key==CONV_DONE_KEY){fpui_set(s->ui,MV_KEY,0);return 0;}   /* conv.c: the worker's done */
    int chart=conv_chart_up(s);
    conv_chart_close(s);                 /* the result stayed up until now (conv.c); any key takes it down */
    if(s->ui_view==VIEW_SETTINGS) {
        if(key==CHART_KEY && !chart) {     /* Bei 11-07: the cube's chart again, from its .JFT (conv_view) */
            u32 rc=conv_view(s,s->edit_index);
            mv_str(s,MV_CHART_T,ctext(s,rc==0u?T_BLANK:rc==1u?T_BUSY:T_AGAIN));   /* CVV_SHOWN / CVV_BUSY / "Convert again" */
        } else if(key==MENU_NOTICE && !chart) {   /* back on the cube that was edited, not the title (MENU on the chart: just closes it) */
            s->ui_view=VIEW_MANAGER;
            u32 slot=mv_slot_of(s,s->edit_index);
            manager_refresh(s);
            mv_focus(s,fpui_first(s->ui,MV_ROWID0+(slot<MV_SLOTS?slot:0u)));
            /* last: the settings page's change event on LC_Back sends the stock
             * Return, so the manager is rebuilt with these values (and its focus)
             * already in place -- MENU's own Return arrived first and left the
             * manager without focus (2026-11-03 camera, diagK3) */
            {volatile u32 ret[2];ret[0]=0x75746552u;ret[1]=0x6E72u;   /* "Return" as words: a literal's address would be a
                                                                     * .text relocation (no linker), once this body grew */
             back_request(s,(const char *)ret);}
            fpui_set(s->ui,MV_BACK,++s->ui_goseq);
        }
    } else if(key==30u || key==31u) {
        s->ui_header=key==31u && mv_paged(s);s->ui_popup=0;mv_hint(s);
    } else if(key>=20u && key<=20u+MV_SLOTS) {               /* 20 + slot + 1; 20 = closed */
        s->ui_popup=key-20u;if(key>20u)s->ui_result=R_NONE;mv_hint(s);
    } else if(key==10u || key==11u) {
        if(key==10u && s->ui_page)s->ui_page--;
        if(key==11u && s->ui_page+1u<mv_pages(s))s->ui_page++;
        manager_refresh(s);
    } else if(key==AEL_KEY) {
        u32 slot=MV_SLOTS;
        for(u32 k=0;k<MV_SLOTS;k++)if(fpui_first(s->ui,MV_ROWID0+k)==s->ui_focus)slot=k;
        int f=slot<MV_SLOTS?mv_cube(s,slot):-1;
        if(f>=0 && conv_running(s)){s->ui_result=R_CONV;mv_hint(s);}   /* the cube's settings wait for the conversion */
        else if(f>=0)open_settings(s,(u32)f);
    }
    fpui_set(s->ui,MV_KEY,0);return 0;
}
static u32 color_focus_body(uintptr_t desc) {
    struct lut4_state *s=color_ctx();if(!s || !s->ui)return 0;
    u32 v=fpui_value(desc);
    if(v!=s->ui_focus)conv_chart_close(s);
    s->ui_focus=v;s->ui_header=v==MV_HEADER_FOCUS && mv_paged(s);
    if(s->ui_view==VIEW_MANAGER){mv_int(s,MV_HEAD,v==MV_TAB_FOCUS);mv_hint(s);}
    return 0;
}
/* the stock On / Off popup: 0 Enable, 1 Disable (SupManager's order) */
static u32 color_choice(uintptr_t desc,u32 k) {
    struct lut4_state *s=color_ctx();if(!s || !s->ui)return 0;
    u32 v=fpui_value(desc);if(v==255u)return 0;
    int f=mv_cube(s,k);
    conv_finish(s);
    if(s->ui_view==VIEW_MANAGER && f>=0 && v<=1u) {
        struct lib_entry *e=&s->library->entries[f];u32 on=v==0u;
        if(conv_running(s))s->ui_result=R_CONV;                      /* one at a time; nothing moves meanwhile */
        else if(on && !mv_ready(e))s->ui_result=R_SETUP;
        else if(on && !mv_on(s,(u32)f) && mv_used(s)>=lut_room(s))s->ui_result=R_FULL;   /* no COLOR row free */
        else if(on && !conv_ok(s,(u32)f))                            /* On: converted first (user 2026-11-04) */
            s->ui_result=conv_start(s,(u32)f)?R_CONVFAIL:R_CONV;
        else {
            int rc=library_enabled(s,(u32)f,on);
            s->ui_result=rc==RECORD_BUSY?R_BUSY:rc!=OK?R_WRITE:R_NONE;
            if(rc==OK)cols_sync(s);
        }
    }
    manager_refresh(s);
    fpui_set(s->ui,mv_vslot(MV_CHOICE,k),255u);s->ui_cache[mv_vslot(MV_CHOICE,k)]=0;
    return 0;
}
static u32 settings_choice(uintptr_t desc,u32 row) {
    struct lut4_state *s=color_ctx();if(!s || !s->ui || s->ui_view!=VIEW_SETTINGS)return 0;
    struct lib_entry *e=edited(s);u32 v=fpui_value(desc);
    if(conv_running(s)){settings_refresh(s);return 0;}
    if(row==2u) {                      /* the matrix: the library refuses Custom without the author's */
        if(e && (v!=e->matrix || !(e->flags&LIB_MATRIX)) && !library_set_matrix(s,s->edit_index,v))cols_sync(s);
        s->ui_cache[MV_MATRIX_V]=0;
        settings_refresh(s);return 0;
    }
    if(e && (row?v!=e->gamma || !(e->flags&LIB_GAMMA):v!=e->color || !(e->flags&LIB_SPACE)))
        {s->set_rows[row].set(s,(int)v);cols_sync(s);}   /* set up or not: a row or not */
    s->ui_cache[row?MV_GAMMA_V:MV_SPACE_V]=0;
    settings_refresh(s);return 0;      /* a refused write repaints the saved value */
}
/* LC_Go back to 0: the settings page wrote it as it entered.  Forget the name,
 * so the manager's change event, firing again when MENU rebuilds it, asks for nothing. */
static u32 color_go_back_body(uintptr_t desc) {
    struct lut4_state *s=color_ctx();
    if(s && s->ui && !fpui_value(desc)){char *go=(char *)fpui_text(s->ui,T_GO);if(go)*go=0;}
    return 0;
}
static u32 settings_space_body(uintptr_t d){return settings_choice(d,0);}
static u32 settings_gamma_body(uintptr_t d){return settings_choice(d,1);}
static u32 settings_space(uintptr_t d){return aligned_call(settings_space_body,d);}
static u32 settings_gamma(uintptr_t d){return aligned_call(settings_gamma_body,d);}
static u32 settings_matrix_body(uintptr_t d){return settings_choice(d,2);}
static u32 settings_matrix(uintptr_t d){return aligned_call(settings_matrix_body,d);}
static u32 color_key(uintptr_t d){return aligned_call(color_key_body,d);}
static u32 color_focus(uintptr_t d){return aligned_call(color_focus_body,d);}
static u32 color_go_back(uintptr_t d){return aligned_call(color_go_back_body,d);}
static u32 color_choice0_body(uintptr_t d){return color_choice(d,0);}
static u32 color_choice0(uintptr_t d){return aligned_call(color_choice0_body,d);}
static u32 color_choice1_body(uintptr_t d){return color_choice(d,1);}
static u32 color_choice1(uintptr_t d){return aligned_call(color_choice1_body,d);}
static u32 color_choice2_body(uintptr_t d){return color_choice(d,2);}
static u32 color_choice2(uintptr_t d){return aligned_call(color_choice2_body,d);}
static u32 color_choice3_body(uintptr_t d){return color_choice(d,3);}
static u32 color_choice3(uintptr_t d){return aligned_call(color_choice3_body,d);}
static u32 color_choice4_body(uintptr_t d){return color_choice(d,4);}
static u32 color_choice4(uintptr_t d){return aligned_call(color_choice4_body,d);}
static u32 color_choice5_body(uintptr_t d){return color_choice(d,5);}
static u32 color_choice5(uintptr_t d){return aligned_call(color_choice5_body,d);}

/* The fpSup row's open (the UI thread): the page with its focus -- the title row
 * when it pages, else slot 0 -- then the firmware's transition. */
static u32 color_open_body(uintptr_t a) {
    void *arg=(void *)a;
    struct lut4_state *s=arg;if(!s->ui)return (u32)SL_BADARG;
    conv_finish(s);                            /* a conversion that ended while we were away */
    conv_chart_close(s);                       /* a finished one's chart: not again (a running one's: conv_busy below) */
    if(imp_scan(s))cols_sync(s);              /* .cube files copied since: rows now, no restart */
    s->ui_view=VIEW_MANAGER;s->ui_page=0;s->ui_popup=0;s->ui_result=R_NONE;mv_forget(s);
    manager_refresh(s);mv_int(s,MV_HEAD,0);       /* known from here: focus moves post only changes */
    u32 row0=fpui_first(s->ui,MV_ROW0);
    mv_focus(s,mv_paged(s)||!row0?MV_HEADER_FOCUS:row0);
    u32 r=(u32)fpui_open(s->svc,ctext(s,T_PAGE));
    if(conv_running(s))conv_busy(s,1);   /* back while it runs (finished ones went above): the overlay and its focus again */
    return r;
}
static int color_open(void *arg) { return (int)aligned_call(color_open_body,(uintptr_t)arg); }
static void color_ui_init(struct lut4_state *s) {
    const void *ui=fpui_read(s->svc,string(s,43));if(!ui)return;
    const struct fpui_file *f=ui;
    if(f->n_vars!=MV_COUNT || f->n_texts!=T_COUNT || fpui_install(s->svc,ui))return;
    s->ui=ui;*(volatile u32 *)(uintptr_t)color_ctx_at()=(u32)(uintptr_t)s;
    s->ui_view=VIEW_MANAGER;
    fpui_watch(ui,MV_KEY,color_key);fpui_watch(ui,MV_FOCUS,color_focus);
    fpui_watch(ui,mv_vslot(MV_CHOICE,0),color_choice0);fpui_watch(ui,mv_vslot(MV_CHOICE,1),color_choice1);
    fpui_watch(ui,mv_vslot(MV_CHOICE,2),color_choice2);fpui_watch(ui,mv_vslot(MV_CHOICE,3),color_choice3);
    fpui_watch(ui,mv_vslot(MV_CHOICE,4),color_choice4);fpui_watch(ui,mv_vslot(MV_CHOICE,5),color_choice5);
    fpui_watch(ui,MV_SPACE_V,settings_space);fpui_watch(ui,MV_GAMMA_V,settings_gamma);
    fpui_watch(ui,MV_MATRIX_V,settings_matrix);
    fpui_watch(ui,MV_GO,color_go_back);
    {char *go=(char *)fpui_text(ui,T_GO);if(go)*go=0;}   /* no request until AEL names one */
    {char *b=(char *)fpui_text(ui,T_BACK);if(b)*b=0;}   /* nor a Return until MENU */
    manager_refresh(s);
}
