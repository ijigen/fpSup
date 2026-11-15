/* Native RES-CUSTOM settings, independent of virtual-RCD producers. */
enum { RC_VISIBLE=5, RC_TABS=4, RC_STRINGS=128,
       RC_KEY=0, RC_FOCUS, RC_FILE, RC_ON, RC_COUNT, RC_STATUS, RC_RESTART,
       RC_ROWS, RC_PARTS=12, RC_N=0, RC_G, RC_V, RC_R, RC_E, RC_VIS, RC_LOCK,
       RC_SELECTED, RC_MORE, RC_DEFAULT, RC_CHOICE, RC_VERSIONX,
       RC_TAB=RC_ROWS+RC_VISIBLE*RC_PARTS, RC_TITLE=RC_TAB+RC_TABS*4, RC_VARS=RC_TITLE+1 };
struct rc_ui {
    u32 magic, state, S, blob, app, index, desc;
    u32 names[RC_VARS][4];
    char file[32], on[32], count[32], status[64], page[12];
    u32 list_page, popup, header, result;
    char row_text[RC_VISIBLE][5][32], restart[32], title[32];
#ifdef OGC_V4
    const void *ui;            /* the FT4S file (rc_files_page.ft4), installed by fpsup-ui */
    struct sl_row row;         /* the fpSup page's JUMP row                         */
    char row_title[32];        /* rc_words writes 28 bytes */
    char pager[12];
    char slot_text[RC_VISIBLE + 1][5][32];   /* slot 0 .. 5 (v4 SupManager's page)  */
    u32 hint_last, head_last;                /* last footer / header light posted, + 1 */
    char menu_name[OGC_MAX_AVAIL][32];       /* each file's resolution-list text (its SEC_UI row) */
    const struct sl_svc *svc;                /* fpui_open: the fpSup row's transition */
#endif
};

#ifdef OGC_V4
/* fpsup-ui reaches variables by number: RC_* is the file's order. */
static void rc_int(struct rc_ui *u,u32 i,u32 value) { fpui_set(u->ui,i,value); }
static void rc_str(struct rc_ui *u,u32 i,const char *text) { fpui_set_text(u->ui,i,text); }
#else
static void rc_int(struct rc_ui *u,u32 i,u32 value)
{ ((fw3)0xC0593F30u)(0,(u32)(uintptr_t)u->names[i],value); }
static void rc_str(struct rc_ui *u,u32 i,const char *text)
{ ((fw3)0xC0593FE0u)(0,(u32)(uintptr_t)u->names[i],(u32)(uintptr_t)text); }
#endif

static u32 rc_mask(u8 *S)
{
    u32 cfg=SW(S,S_CFG),mask=0,n=W(cfg+CFG_NEN);
    u32 explicit_list=W(cfg+CFG_MAGIC)==OGC_CFG_MAGIC && W(cfg+CFG_VERSION)==OGC_CFG_VERSION &&
        W(cfg+CFG_SUM)==fnv(cfg,CFG_SUM) && n && n<=OGC_MAX_ROWS;
    for(u32 i=0;i<SW(S,S_NAVAIL);i++) {
        u32 lab=(u32)(uintptr_t)S+S_AVAIL+8u*i;
        if(explicit_list?enabled(S,lab):row_by_label(S,lab)>=0)mask|=1u<<i;
    }
    return mask;
}

static u32 rc_set(u8 *S,u32 index,u32 on)
{
    if(busy())return 4u;
    u32 n=SW(S,S_NAVAIL),labels[2*OGC_MAX_ROWS],count=0,mask=rc_mask(S);
    u32 capacity=OGC_MAX_ROWS-(SW(S,S_VRC)?1u:0u);
    if(index>=n)return 1u;
    u32 next=on?mask|(1u<<index):mask&~(1u<<index);
    if(next==mask)return 0;
    for(u32 i=0;i<n;i++)if(next&(1u<<i)) {
        if(count==capacity)return 3u;
        labels[2*count]=SW(S,S_AVAIL+8u*i);labels[2*count+1]=SW(S,S_AVAIL+8u*i+4u);count++;
    }
    /* NEN=0 means defaults in RCS1. VRC000 never names a disk row, so this
     * reserved label represents an explicit empty file list without migration. */
    if(!count){labels[0]=0x30435256u;labels[1]=0x00003030u;count=1;}
    u32 cfg=SW(S,S_CFG),before[CFG_BYTES/4u],dirty=SW(S,S_DIRTY);
    copy((u32)(uintptr_t)before,cfg,CFG_BYTES);
    if(!ogc_enable_set(S,count,(u32)(uintptr_t)labels))return 1u;
    if(ogc_save(S))return 0;
    copy(cfg,(u32)(uintptr_t)before,CFG_BYTES);SW(S,S_DIRTY)=dirty;return 5u;
}

/* A refresh has its own file object and one bounded file buffer. It never
 * overwrites a loaded RCD, live table, QS asset or virtual-RCD staging buffer. */
static u32 rc_refresh(u8 *S,struct rc_ui *u)
{
    if(busy())return 4u;
    u32 stage=((u32)(uintptr_t)(u+1)+63u)&~63u,fo=uca(stage+S_BODY);   /* v4: uncached, as S.FOBJ */
    u8 *T=(u8 *)(uintptr_t)stage;
    copy(stage,(u32)(uintptr_t)S,S_BODY);
    SW(T,S_FOBJ)=fo;SW(T,S_DATA)=fo+0x1000u;SW(T,S_DATA_CAP)=RCD_MAX_FILE;SW(T,S_DATA_USED)=0;
    u32 seen=0,n=list_rcd(T,(const char *)(uintptr_t)SW(S,S_PATH),&seen),count=0,labels[2*OGC_MAX_AVAIL];
    for(u32 i=0;i<n;i++) {
        u32 reason=0,f=read_rcd(T,fo+FO_NAMES+16u*i,W(fo+FO_SIZES+4u*i),&reason);
        if(!f||rcd_check(T,f,W(fo+FO_SIZES+4u*i)))continue;
        u32 duplicate=0;
        for(u32 j=0;j<count;j++)if(same_label(f+RH_LABEL,(u32)(uintptr_t)labels+8u*j))duplicate=1;
        if(duplicate)continue;
        labels[2*count]=W(f+RH_LABEL);labels[2*count+1]=W(f+RH_LABEL+4u);
#ifdef OGC_V4
        /* the page shows the name the resolution list does (user 2026-10-24), not the file's */
        /* "OG2K 2000x1334" -> "OG2K (2000x1334)": the size in brackets (user 2026-10-24) */
        {u32 ln=0,ui=sec(f,SEC_UI,&ln),n=0,sp=0,c=0;char *to=u->menu_name[count];
         if(ui)while(n<ln&&n<32u&&u8at(ui+n))n++;
         for(u32 i=0;i<n;i++)if(u8at(ui+i)==' ')sp=i;
         if(sp&&sp+1u<n&&n+3u<=31u) {
             for(;c<sp;c++)to[c]=(char)u8at(ui+c);
             to[c++]=' ';to[c++]='(';
             for(u32 i=sp+1u;i<n;i++)to[c++]=(char)u8at(ui+i);
             to[c++]=')';
         } else for(;c<n&&c<31u;c++)to[c]=(char)u8at(ui+c);
         to[c]=0;}
#endif
        count++;
    }
    /* Preserve the selected filename when the sorted catalogue grows. */
    u32 lab[2]={0,0};
    if(u->index<SW(S,S_NAVAIL)){lab[0]=SW(S,S_AVAIL+8u*u->index);lab[1]=SW(S,S_AVAIL+8u*u->index+4u);}
    copy((u32)(uintptr_t)S+S_AVAIL,(u32)(uintptr_t)labels,8u*count);SW(S,S_NAVAIL)=count;
    u->index=0;
    for(u32 i=0;i<count;i++)if(same_label((u32)(uintptr_t)lab,(u32)(uintptr_t)labels+8u*i))u->index=i;
    return 0;
}

static u32 rc_num(char *p,u32 n)
{
    u32 k=0;if(n>=10u)p[k++]='0'+n/10u;p[k++]='0'+n%10u;p[k]=0;return k;
}

static void rc_words(char *to,u32 a,u32 b,u32 c,u32 d,u32 e,u32 f)
{
    volatile u32 *w=(volatile u32 *)to;w[0]=a;w[1]=b;w[2]=c;w[3]=d;w[4]=e;w[5]=f;w[6]=0;
}

#ifndef OGC_V4
static void rc_hint(struct rc_ui *u)
{
    if(u->result==3u)rc_words(u->status,0x7473694cu,0x6c756620u,0x64203a6cu,0x62617369u,0x6f20656cu,0x0000656eu);
    else if(u->result==6u)rc_words(u->status,0x74736552u,0x20747261u,0x61206f74u,0x796c7070u,0x00000000u,0x00000000u);
    else if(u->result==5u)rc_words(u->status,0x74697257u,0x61662065u,0x64656c69u,0x00000000u,0x00000000u,0x00000000u);
    else if(u->result==4u)rc_words(u->status,0x6f636552u,0x6e696472u,0x75622067u,0x00007973u,0x00000000u,0x00000000u);
    else if(u->popup)rc_words(u->status,0x203a4b4fu,0x666e6f63u,0x006d7269u,0x00000000u,0x00000000u,0x00000000u);
    else if(u->header)rc_words(u->status,0x5446454cu,0x4749522fu,0x203a5448u,0x65676170u,0x00000000u,0x00000000u);
    else rc_words(u->status,0x203a4b4fu,0x656c6573u,0x00007463u,0x00000000u,0x00000000u,0x00000000u);
    rc_str(u,RC_STATUS,u->status);rc_str(u,RC_RESTART,u->restart);
}

static void rc_post(struct rc_ui *u,u32 result)
{
    u8 *S=(u8 *)(uintptr_t)u->S;u32 mask=rc_mask(S),n=SW(S,S_NAVAIL),used=0;
    u->result=result;
    if(u->index>=n)u->index=n?n-1u:0;
    u32 pages=n?(n+RC_VISIBLE-1u)/RC_VISIBLE:1u;
    if(u->list_page>=pages)u->list_page=pages-1u;
    for(u32 i=0;i<sizeof(u->file);i++)u->file[i]=u->on[i]=u->count[i]=0;
    u->file[0]='R';u->file[1]='C';u->file[2]='D';u->file[3]=' ';
    if(n)copy((u32)(uintptr_t)u->file+4u,(u32)(uintptr_t)S+S_AVAIL+8u*u->index,8u);
    else {u->file[4]='N';u->file[5]='o';u->file[6]='n';u->file[7]='e';}
    if(n&&(mask&(1u<<u->index)))rc_words(u->on,0x62616e45u,0x2064656cu,0x00004e4fu,0x00000000u,0x00000000u,0x00000000u);
    else rc_words(u->on,0x62616e45u,0x2064656cu,0x0046464fu,0x00000000u,0x00000000u,0x00000000u);
    for(u32 i=0;i<n;i++)if(mask&(1u<<i))used++;
    u32 at=rc_num(u->count,used);u->count[at++]='/';rc_num(u->count+at,OGC_MAX_ROWS-(SW(S,S_VRC)?1u:0u));
    rc_str(u,RC_FILE,u->file);rc_str(u,RC_ON,u->on);rc_str(u,RC_COUNT,u->count);
    rc_words(u->title,0x2d534552u,0x54535543u,0x28204d4fu,0,0,0);
    at=12u+rc_num(u->title+12u,used);u->title[at++]='/';
    at+=rc_num(u->title+at,OGC_MAX_ROWS-(SW(S,S_VRC)?1u:0u));u->title[at++]=')';u->title[at]=0;
    rc_str(u,RC_TITLE,u->title);
    u32 width=pages==1u?1024u:pages==2u?512u:pages==3u?341u:256u;
    for(u32 k=0;k<RC_TABS;k++) {
        rc_int(u,RC_TAB+k,k<pages);rc_int(u,RC_TAB+RC_TABS+k,k==u->list_page);
        rc_int(u,RC_TAB+2u*RC_TABS+k,width*k);
        rc_int(u,RC_TAB+3u*RC_TABS+k,k+1u==pages?1024u-width*k:width);
    }
    for(u32 k=0;k<RC_VISIBLE;k++) {
        u32 index=u->list_page*RC_VISIBLE+k,valid=index<n,enabled_now=valid&&(mask&(1u<<index));
        u32 base=RC_ROWS+k*RC_PARTS;
        for(u32 j=0;j<5u;j++)for(u32 i=0;i<32u;i++)u->row_text[k][j][i]=0;
        if(valid) {
            char *name=u->row_text[k][enabled_now?RC_N:RC_G];
            copy((u32)(uintptr_t)name,(u32)(uintptr_t)S+S_AVAIL+8u*index,8u);
            u32 len=slen((u32)(uintptr_t)name);name[len++]='.';name[len++]='R';name[len++]='C';name[len]='D';
            if(enabled_now)rc_words(u->row_text[k][RC_E],0x62616e45u,0x0064656cu,0x00000000u,0x00000000u,0x00000000u,0x00000000u);
            else rc_words(u->row_text[k][RC_R],0x61736944u,0x64656c62u,0x00000000u,0x00000000u,0x00000000u,0x00000000u);
        } else if(!n&&!k) {
            rc_words(u->row_text[k][RC_N],0x52206f4eu,0x66204443u,0x73656c69u,0x00000000u,0x00000000u,0x00000000u);
        }
        for(u32 part=0;part<5u;part++)rc_str(u,base+part,u->row_text[k][part]);
        rc_int(u,base+RC_VIS,valid||(!n&&!k));rc_int(u,base+RC_LOCK,!valid);
        rc_int(u,base+RC_SELECTED,!enabled_now);rc_int(u,base+RC_MORE,0);
        rc_int(u,base+RC_DEFAULT,!enabled_now);rc_int(u,base+RC_VERSIONX,49u);
    }
    rc_hint(u);
}
#endif

#ifndef OGC_V4
/* Descriptors borrow the resident name, so every callback checks both its
 * exact variable slot and the consumer-owned context before changing state. */
static struct rc_ui *rc_owner(u32 desc,u32 variable)
{
    struct rc_ui *u=(struct rc_ui *)(uintptr_t)(W(desc+4u)-__builtin_offsetof(struct rc_ui,names)-16u*variable);
    if(u->magic!=0x32464352u||SW((u8 *)(uintptr_t)u->S,S_FILE_UI)!=(u32)(uintptr_t)u)return 0;
    return u;
}

static u32 rc_key(u32 desc)
{
    struct rc_ui *u=rc_owner(desc,RC_KEY);if(!u)return 0;
    u8 *S=(u8 *)(uintptr_t)u->S;u32 key=W(desc+8u),n=SW(S,S_NAVAIL);
    if(!key)return 0;
    if(key==10u||key==11u) {
        u32 last=n?(n-1u)/RC_VISIBLE:0;
        if(key==10u&&u->list_page)u->list_page--;
        if(key==11u&&u->list_page<last)u->list_page++;
        u->index=u->list_page*RC_VISIBLE;u->popup=0;rc_post(u,0);
    } else if(key>=20u&&key<=20u+RC_VISIBLE) {
        if(key>20u&&u->result==6u)u->result=0;
        u->popup=key-20u;
        if(u->popup)u->index=u->list_page*RC_VISIBLE+u->popup-1u;
        rc_hint(u);
    } else if(key==31u||key==30u) {
        u->header=key==31u;u->popup=0;rc_hint(u);
    }
    rc_int(u,RC_KEY,0);return 0;
}

static u32 rc_focus(u32 desc)
{
    struct rc_ui *u=rc_owner(desc,RC_FOCUS);if(!u)return 0;
    u->header=W(desc+8u)==3451u;rc_hint(u);return 0;
}

static u32 rc_choice(u32 desc,u32 row)
{
    u32 variable=RC_ROWS+(row-1u)*RC_PARTS+RC_CHOICE;
    struct rc_ui *u=rc_owner(desc,variable);if(!u)return 0;
    u32 choice=W(desc+8u);if(choice==255u)return 0;
    u8 *S=(u8 *)(uintptr_t)u->S;u32 index=u->list_page*RC_VISIBLE+row-1u;
    /* SupManager's right-to-More choice (2) has no file action. Only explicit
     * Enable/Disable choices act; a hidden row never aliases another file. */
    if(choice<=1u&&index<SW(S,S_NAVAIL)) {
        u32 before=rc_mask(S);
        u->index=index;u32 result=rc_set(S,index,choice==0u);
        rc_post(u,!result&&rc_mask(S)!=before?6u:result);
    }
    rc_int(u,variable,255u);return 0;
}
static u32 rc_choice1(u32 d){return rc_choice(d,1);}
static u32 rc_choice2(u32 d){return rc_choice(d,2);}
static u32 rc_choice3(u32 d){return rc_choice(d,3);}
static u32 rc_choice4(u32 d){return rc_choice(d,4);}
static u32 rc_choice5(u32 d){return rc_choice(d,5);}
#endif

#ifdef OGC_V4
/* ---- loader v4: the file list on v4 SupManager's page ------------------------
 * rc_files_page.ft4(): build_fp4's SupManager page (manage_page v4: slot 0
 * under the title row, six files or fewer do not page, the header lights on the
 * tab bar), its variables SM_ -> RC_, the title our own text (RC_Header).  The
 * numbers below are supmgr.c's, in that file's order. */
#define RV_SLOTS        (RC_VISIBLE + 1u)
#define RV_TABS         7u
enum { RP_RED, RP_GREEN, RP_NAME, RP_GREY, RP_VER };
#define RV_KEY          0u
#define RV_OK           1u
#define RV_PART(p, k)   (2u + (p) * RC_VISIBLE + (k) - 1u)
#define RV_PAGE         (2u + 5u * RC_VISIBLE)
#define RV_VERSION      (RV_PAGE + 1u)
#define RV_VISIBLE      (RV_VERSION + 1u)
#define RV_LOCK         (RV_VISIBLE + RC_VISIBLE)
#define RV_SELECTED     (RV_LOCK + RC_VISIBLE)
#define RV_MORE         (RV_SELECTED + RC_VISIBLE)
#define RV_DEFAULT      (RV_MORE + RC_VISIBLE)
#define RV_CHOICE       (RV_DEFAULT + RC_VISIBLE)
#define RV_FOCUS        (RV_CHOICE + RC_VISIBLE)
#define RV_RIGHT_FOOTER (RV_FOCUS + 3u)
#define RV_VERSION_X    (RV_RIGHT_FOOTER + 1u)
#define RV_TABS_AT      (RV_VERSION_X + RC_VISIBLE)
#define RV_X0           (RV_TABS_AT + 4u * RV_TABS)
#define RV_TITLE        (RV_X0 + 12u)
#define RV_ROW0         (RV_X0 + 13u)
#define RV_HEAD         (RV_X0 + 14u)
/* then RC_TOff0..5, RC_TOn0..5: the right column's stock On / Off (the page's
 * localized texts; user 2026-10-24: no Enabled / Disabled words) */
#define RV_TOFF         (RV_X0 + 15u)
#define RV_TON          (RV_TOFF + RV_SLOTS)
#define RV_GSHOW        (RV_TON + RV_SLOTS)      /* the grey name / red note drawn only when they say something */
#define RV_RSHOW        (RV_GSHOW + RV_SLOTS)
#define RV_HEADER       (RV_RSHOW + RV_SLOTS)
#define RV_VARS         (RV_HEADER + 1u)
#define RV_HEADER_FOCUS 3451u
#define RV_TAB_FOCUS    55u
/* rc_files_page.V4_TEXTS */
enum { RT_BLANK, RT_FOOTER, RT_POPUP, RT_PAGE_HINT, RT_ENABLED, RT_DISABLED, RT_FULL, RT_RESTART,
       RT_WRITE, RT_BUSY, RT_UPDATE, RT_NONE, RT_PAGE, RT_UNLOAD, RT_LOAD, RT_COUNT };

/* The callbacks get only the descriptor: the state is a word in the code
 * (writable at the cached alias), next to the one function that reaches it. */
__attribute__((noinline)) static u32 rc_ctx(void)
{
    u32 at;
    __asm__ volatile("adr %0, 1f\n\tb 2f\n\t.balign 4\n1:\t.word 0\n2:" : "=r"(at));
    return at;
}
static struct rc_ui *rc_me(void)
{
    struct rc_ui *u=(struct rc_ui *)(uintptr_t)W(rc_ctx());
    if(!u||u->magic!=0x32464352u||SW((u8 *)(uintptr_t)u->S,S_FILE_UI)!=(u32)(uintptr_t)u)return 0;
    return u;
}
static const char *rc_text(struct rc_ui *u,u32 i){return fpui_text(u->ui,i);}

static u32 rv_n(struct rc_ui *u){return SW((u8 *)(uintptr_t)u->S,S_NAVAIL);}
static int rv_paged(struct rc_ui *u){return rv_n(u)>RV_SLOTS;}
static u32 rv_pages(struct rc_ui *u){return rv_paged(u)?1u+(rv_n(u)-1u)/RC_VISIBLE:1u;}
/* the file in slot k, or -1: six or fewer fill slots 0..5, more page five at a time in 1..5 */
static int rv_file(struct rc_ui *u,u32 k)
{
    u32 i=k;
    if(k>=RV_SLOTS)return -1;
    if(rv_paged(u)){if(!k)return -1;i=u->list_page*RC_VISIBLE+k-1u;}
    return i<rv_n(u)?(int)i:-1;
}
static u32 rv_vpart(u32 p,u32 k){return k?RV_PART(p,k):RV_X0+p;}
static u32 rv_vslot(u32 group,u32 k)
{
    if(group==RV_VERSION_X)return k?RV_VERSION_X+k-1u:RV_X0+11u;
    return k?group+k-1u:RV_X0+5u+(group-RV_VISIBLE)/RC_VISIBLE;
}
static u32 rv_tab(struct rc_ui *u,u32 i)
{
    u32 n=rv_pages(u);
    if(n>RV_TABS)n=RV_TABS;
    u32 width=n==2u?512u:n==3u?341u:n==4u?256u:n==5u?204u:n==6u?170u:146u;
    u32 group=(i-RV_TABS_AT)/RV_TABS,k=(i-RV_TABS_AT)%RV_TABS;
    return group==0u?rv_paged(u)&&k<n:group==1u?k==u->list_page:group==2u?width*k
         :k+1u==n?1024u-width*k:width;
}
static void rv_hint(struct rc_ui *u)
{
    /* "restart to apply" is the row's own note now (RT_UNLOAD / RT_LOAD, as SupManager's) */
    u32 t=u->result==3u?RT_FULL:u->result==4u?RT_BUSY:u->result==5u?RT_WRITE
         :u->popup?RT_POPUP:rv_paged(u)?RT_PAGE_HINT:RT_FOOTER;   /* paged: fixed, as SupManager's */
    if(u->hint_last==t+1u)return;                         /* every post is another GUI update pass */
    u->hint_last=t+1u;
    rc_str(u,RV_OK,rc_text(u,t));
}

/* Everything the page shows, posted (v3 rc_post's texts on v4's slots). */
static void rv_refresh(struct rc_ui *u)
{
    u8 *S=(u8 *)(uintptr_t)u->S;u32 n=rv_n(u),mask=rc_mask(S),used=0;
    u32 cap=OGC_MAX_ROWS-(SW(S,S_VRC)?1u:0u);
    if(u->list_page>=rv_pages(u))u->list_page=0;
    for(u32 i=0;i<n;i++)if(mask&(1u<<i))used++;
    u32 at=rc_num(u->count,used);u->count[at++]='/';rc_num(u->count+at,cap);
    rc_words(u->title,0x2d534552u,0x54535543u,0x28204d4fu,0,0,0);           /* "RES-CUSTOM (" */
    at=12u+rc_num(u->title+12u,used);u->title[at++]='/';
    at+=rc_num(u->title+at,cap);u->title[at++]=')';u->title[at]=0;
    char *p=u->pager;
    if(rv_pages(u)<=1u){p[0]=' ';p[1]=0;}
    else {at=rc_num(p,u->list_page+1u);p[at++]=' ';p[at++]='/';p[at++]=' ';at+=rc_num(p+at,rv_pages(u));p[at]=0;}
    rc_str(u,RV_HEADER,u->title);rc_str(u,RV_VERSION,rc_text(u,RT_BLANK));rc_str(u,RV_PAGE,u->pager);   /* the count is in the title (user 2026-10-24) */
    rc_str(u,RV_RIGHT_FOOTER,rc_text(u,RT_BLANK));          /* as SupManager's: no footer note */
    for(u32 i=RV_TABS_AT;i<RV_X0;i++)rc_int(u,i,rv_tab(u,i));
    rc_int(u,RV_TITLE,(u32)rv_paged(u));
    for(u32 k=0;k<RV_SLOTS;k++) {
        int f=rv_file(u,k);u32 on=f>=0&&(mask&(1u<<(u32)f)),none=!n&&!k;
        /* loaded this boot (its format is a row now) vs next boot (on): SupManager's notes */
        u32 now=f>=0&&row_by_label(S,(u32)(uintptr_t)S+S_AVAIL+8u*(u32)f)>=0;
        for(u32 j=0;j<5u;j++)for(u32 c=0;c<32u;c++)u->slot_text[k][j][c]=0;
        if(f>=0) {
            char *name=u->slot_text[k][on?RP_NAME:RP_GREY];
            const char *menu=u->menu_name[f];
            if(menu[0]) {for(u32 c=0;c<31u&&menu[c];c++)name[c]=menu[c];}   /* its resolution-list name */
            else {
                copy((u32)(uintptr_t)name,(u32)(uintptr_t)S+S_AVAIL+8u*(u32)f,8u);
                u32 len=slen((u32)(uintptr_t)name);name[len++]='.';name[len++]='R';name[len++]='C';name[len]='D';
            }
        }
        /* shown before its words, hidden after them: a hidden row is not told (supmgr.c refresh, 2026-11-10) */
        if(f>=0||none)rc_int(u,rv_vslot(RV_VISIBLE,k),1);
        for(u32 pp=RP_RED;pp<=RP_VER;pp++) {
            const char *t=f<0?(none&&pp==RP_GREY?rc_text(u,RT_NONE):rc_text(u,RT_BLANK))
                :pp==RP_GREEN?rc_text(u,RT_BLANK)                 /* On / Off says it (RV_TON) */
                :pp==RP_RED?rc_text(u,now&&!on?RT_UNLOAD:!now&&on?RT_LOAD:RT_BLANK)
                :pp==RP_VER?rc_text(u,RT_BLANK)
                :u->slot_text[k][pp][0]?u->slot_text[k][pp]:rc_text(u,RT_BLANK);
            rc_str(u,rv_vpart(pp,k),t);
        }
        rc_int(u,RV_TOFF+k,f>=0&&!on);rc_int(u,RV_TON+k,f>=0&&on);
        rc_int(u,RV_GSHOW+k,(f>=0&&!on)||none);rc_int(u,RV_RSHOW+k,f>=0&&now!=on);
        rc_int(u,rv_vslot(RV_LOCK,k),f<0);
        rc_int(u,rv_vslot(RV_MORE,k),0);
        rc_int(u,rv_vslot(RV_DEFAULT,k),f>=0&&!on);
        rc_int(u,rv_vslot(RV_SELECTED,k),f>=0&&!on);
        rc_int(u,rv_vslot(RV_VERSION_X,k),49u);
        if(!(f>=0||none))rc_int(u,rv_vslot(RV_VISIBLE,k),0);
    }
    rv_hint(u);
}

static u32 rv_key(uintptr_t desc)
{
    struct rc_ui *u=rc_me();if(!u)return 0;
    u32 key=fpui_value(desc);
    if(!key)return 0;
    if(key==30u||key==31u){u->header=key==31u&&rv_paged(u);u->popup=0;rv_hint(u);}
    else if(key>=20u&&key<=20u+RV_SLOTS) {                 /* 20 + slot + 1; 20 = closed */
        if(key>20u&&u->result==6u)u->result=0;
        u->popup=key-20u;rv_hint(u);
    } else if(key==10u||key==11u) {
        if(key==10u&&u->list_page)u->list_page--;
        if(key==11u&&u->list_page+1u<rv_pages(u))u->list_page++;
        rv_refresh(u);
    }
    rc_int(u,RV_KEY,0);return 0;
}

static u32 rv_choice(uintptr_t desc,u32 k)
{
    struct rc_ui *u=rc_me();if(!u)return 0;
    u32 choice=fpui_value(desc);
    if(choice==255u)return 0;
    u8 *S=(u8 *)(uintptr_t)u->S;int f=rv_file(u,k);
    if(f>=0&&choice<=1u) {                                 /* 0 Enable, 1 Disable */
        u32 before=rc_mask(S),result=rc_set(S,(u32)f,choice==0u);
        u->index=(u32)f;u->result=!result&&rc_mask(S)!=before?6u:result;
    }
    rv_refresh(u);
    rc_int(u,rv_vslot(RV_CHOICE,k),255u);return 0;
}
static u32 rv_choice0(uintptr_t d){return rv_choice(d,0);}
static u32 rv_choice1(uintptr_t d){return rv_choice(d,1);}
static u32 rv_choice2(uintptr_t d){return rv_choice(d,2);}
static u32 rv_choice3(uintptr_t d){return rv_choice(d,3);}
static u32 rv_choice4(uintptr_t d){return rv_choice(d,4);}
static u32 rv_choice5(uintptr_t d){return rv_choice(d,5);}

static u32 rv_focus(uintptr_t desc)
{
    struct rc_ui *u=rc_me();if(!u)return 0;
    u32 v=fpui_value(desc);
    u->header=v==RV_HEADER_FOCUS&&rv_paged(u);
    u32 on=v==RV_TAB_FOCUS;                               /* light the header: no other mark there */
    if(u->head_last!=on+1u){u->head_last=on+1u;rc_int(u,RV_HEAD,on);}   /* only when it changes */
    rv_hint(u);return 0;
}

/* The row's open (the UI thread): the card's files again, then the page with
 * its focus: the title row when it pages, else slot 0. */
static int ogc_files_open(void *arg)
{
    u8 *S=(u8 *)arg;struct rc_ui *u=(struct rc_ui *)(uintptr_t)SW(S,S_FILE_UI);
    if(!u||busy())return 4;
    u->result=rc_refresh(S,u);u->list_page=0;u->popup=0;u->header=rv_paged(u);
    rv_refresh(u);
    u32 row0=fpui_first(u->ui,RV_ROW0);
    rc_int(u,RV_FOCUS,rv_paged(u)||!row0?RV_HEADER_FOCUS:row0);
    return fpui_open(u->svc,rc_text(u,RT_PAGE))?9:0;
}

/* The file list page installed, watched and filled; its JUMP row on the fpSup
 * page.  1 = the row is there. */
static u32 ogc_files_init(u8 *S,u32 blob,u32 state,const struct sl_svc *svc)
{
    struct rc_ui *u=(struct rc_ui *)(uintptr_t)state;
    const struct fpui_file *f=(const struct fpui_file *)(uintptr_t)blob;
    if(blob&7u||f->magic!=FPUI_MAGIC||f->n_vars!=RV_VARS||f->n_texts!=RT_COUNT)return 0;
    u->magic=0x32464352u;u->S=(u32)(uintptr_t)S;u->blob=blob;u->ui=(const void *)(uintptr_t)blob;
    u->app=W(0xC37B7048u);
    if(!u->app||fpui_install(svc,u->ui))return 0;
    u->svc=svc;
    SW(S,S_FILE_UI)=state;
    W(rc_ctx())=state;
    fpui_watch(u->ui,RV_KEY,&rv_key);
    fpui_watch(u->ui,RV_FOCUS,&rv_focus);
    for(u32 k=0;k<RV_SLOTS;k++) {
        uintptr_t fn=k==0?(uintptr_t)&rv_choice0:k==1?(uintptr_t)&rv_choice1:k==2?(uintptr_t)&rv_choice2
                    :k==3?(uintptr_t)&rv_choice3:k==4?(uintptr_t)&rv_choice4:(uintptr_t)&rv_choice5;
        fpui_watch(u->ui,rv_vslot(RV_CHOICE,k),(u32 (*)(uintptr_t))fn);
    }
    rv_refresh(u);
    rc_words(u->row_title,0x2d534552u,0x74737543u,0x00006d6fu,0,0,0);   /* "RES-Custom" (user 2026-10-24) */
    u->row.kind=SL_ROW_JUMP;u->row.n_choices=0;u->row.title=u->row_title;u->row.value=0;
    u->row.get=0;u->row.set=0;u->row.choices=0;u->row.open=ogc_files_open;u->row.arg=S;
    return svc->page_add(svc,&u->row)>=0;
}
#else
static u32 ogc_files_init(u8 *S,u32 blob,u32 state)
{
    struct rc_ui *u=(struct rc_ui *)(uintptr_t)state;
    if(W(blob)!=0x32464352u||W(blob+4u)>RC_STRINGS||W(blob+32u)!=RC_VARS||W(blob+36u)!=20u)return 0;
    u->magic=0x32464352u;u->S=(u32)(uintptr_t)S;u->blob=blob;u->app=W(0xC37B7048u);
    if(!u->app||!uis_reader())return 0;
    const char *strings[RC_STRINGS];u32 offsets[RC_STRINGS],at=blob+W(blob+12u),n=W(blob+4u);
    for(u32 i=0;i<n;i++){strings[i]=(const char *)(uintptr_t)at;at+=slen(at)+1u;}
    if(uis_intern_many(strings,n,UIS_NOT_STOCK,offsets)!=UIS_OK)return 0;
    for(u32 i=0;i<W(blob+8u);i++) {
        u32 r=blob+W(blob+16u)+8u*i;
        put_be32(blob+W(blob+24u)+W(r),offsets[W(r+4u)]);
    }
    u->status[0]=' ';u->page[0]='R';u->page[1]='C';u->page[2]='_';u->page[3]='F';u->page[4]='I';u->page[5]='L';u->page[6]='E';u->page[7]='S';
    rc_words(u->restart,0x74736552u,0x20747261u,0x75206f74u,0x74616470u,0x00000065u,0x00000000u);
    for(u32 i=0;i<RC_VARS;i++) {
        u32 entry=blob+W(blob+20u)+20u*i,type=W(entry);
        copy((u32)(uintptr_t)u->names[i],entry+4u,16u);
        u32 d=0,reg=W(u->app+0x888u);
        if(!reg||((u32(*)(u32,u32,u32))0xC05DB419u)(reg+0x60u,(u32)(uintptr_t)u->names[i],(u32)(uintptr_t)&d)||d)return 0;
        u32 value=type==2u?(u32)(uintptr_t)u->status:i==RC_FOCUS?3451u:
            i>=RC_ROWS&&i<RC_TAB&&(i-RC_ROWS)%RC_PARTS==RC_CHOICE?255u:0;
        u32 def[3]={type,(u32)(uintptr_t)u->names[i],value};
        if(((u32(*)(u32,u32,u32))0xC05DB309u)(u->app,1,(u32)(uintptr_t)def))return 0;
    }
    SW(S,S_FILE_UI)=state;
    ((fw3)0xC0560FB0u)(0xC37B7048u,(u32)(uintptr_t)u->names[RC_KEY],(u32)(uintptr_t)&rc_key);
    ((fw3)0xC0560FB0u)(0xC37B7048u,(u32)(uintptr_t)u->names[RC_FOCUS],(u32)(uintptr_t)&rc_focus);
    ((fw3)0xC0560FB0u)(0xC37B7048u,(u32)(uintptr_t)u->names[RC_ROWS+0u*RC_PARTS+RC_CHOICE],(u32)(uintptr_t)&rc_choice1);
    ((fw3)0xC0560FB0u)(0xC37B7048u,(u32)(uintptr_t)u->names[RC_ROWS+1u*RC_PARTS+RC_CHOICE],(u32)(uintptr_t)&rc_choice2);
    ((fw3)0xC0560FB0u)(0xC37B7048u,(u32)(uintptr_t)u->names[RC_ROWS+2u*RC_PARTS+RC_CHOICE],(u32)(uintptr_t)&rc_choice3);
    ((fw3)0xC0560FB0u)(0xC37B7048u,(u32)(uintptr_t)u->names[RC_ROWS+3u*RC_PARTS+RC_CHOICE],(u32)(uintptr_t)&rc_choice4);
    ((fw3)0xC0560FB0u)(0xC37B7048u,(u32)(uintptr_t)u->names[RC_ROWS+4u*RC_PARTS+RC_CHOICE],(u32)(uintptr_t)&rc_choice5);
    rc_post(u,0);return 1;
}

static int ogc_files_button(void *ctx)
{
    u8 *S=(u8 *)ctx;struct rc_ui *u=(struct rc_ui *)(uintptr_t)SW(S,S_FILE_UI);
    if(!u||busy())return 4;
    u32 reader=uis_reader(),rd=0;
    if(!u->state) {
        if(W(u->app+0x80u)>=W(u->app+0x84u)||W(u->app+0xf8u)>=W(u->app+0xfcu))return 9;
        if(((u32(*)(u32,u32,u32,u32))0xC05E84D9u)(u->app,u->blob+W(u->blob+24u),W(u->blob+28u),(u32)(uintptr_t)&rd)||!rd)return 9;
        W(rd+0x10u)=W(reader+0x10u);W(rd+0x14u)=W(reader+0x14u);u->state=1;
    }
    u32 rc=rc_refresh(S,u);u->list_page=u->index/RC_VISIBLE;u->popup=0;u->header=1;rc_post(u,rc);if(rc)return rc;
    ((fw3)0xC0593F30u)(0,(u32)(uintptr_t)u->names[1],3451u);
    u32 gui=((fw0)0xC054DD38u)();if(!gui)return 9;
    if(!((fw2)W(W(gui)+12u))(gui,(u32)(uintptr_t)u->page))return 9;
    return ((u32(*)(u32,u32,u32,u32))0xC05DCB41u)(u->app,(u32)(uintptr_t)u->page,0,0)?9:0;
}
#endif
