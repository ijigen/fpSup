/* Any .cube copied to \fpSup\LUT\ (user 2026-10-28: "用戶能任意安裝 .cube").
 *
 * imp_scan lists the folder (the firmware's dir API: research/firmware/notes/
 * DIR_ENUM_API.md, camera-verified), adds a library entry for each new file
 * (its author comments fill the author layer; the user's choices are kept apart), and marks
 * entries whose file went -- hidden then, kept for its return (2026-11-06: the
 * list is the folder; library4.c library_partition).  Every entry is "camera" (lib_entry.origin):
 * its settings live in LUT.BIN only and its asset is built from the file when
 * it is picked -- imp_asset parses the text with integers alone (no float
 * runtime here) into build_sup.asset()'s exact layout, the cube-independent
 * matrices and curves copied from LUT.BIN (import_ui.constants()).
 * imp_icon draws each entry's COLOR tile from import_ui's glyph atlas and packs
 * it as an XCI with a literal-only LZ4 block (import_ui.xci_literal). */
#define IMP_MAGIC     0x31504D49u            /* "IMP1": import_ui.section() */
#define IMP_W 86u
#define IMP_H 74u
#define IMP_BASELINE 47u
#define IMP_CENTER 42
#define IMP_MARGIN 3u
#define IMP_ATLAS_H 32u
#define IMP_BASE_ROW 26u
#define IMP_FIRST 0x20u
#define IMP_LAST 0x7Eu
#define IMP_LABEL 8u
#define IMP_MAX_BYTES 0x1000000u             /* cube.MAX_SOURCE_BYTES */
#define DIR_CTOR 0xC0366918u
#define DIR_OPEN 0xC0366990u
#define DIR_NEXT 0xC03669F8u
#define DIR_DTOR 0xC0366940u

struct imp_section {
    u32 magic, const_off, const_len, atlas_off, caps, cap_table[3];
    u32 icon_bytes, icon_slot, folder_off, n_caps_px[3];
};

static const struct imp_section *imp_sec(struct lut4_state *s) {
    if(!s->cfg->import_off)return 0;
    const struct imp_section *c=(const struct imp_section *)((const u8 *)s->block+s->cfg->import_off);
    return c->magic==IMP_MAGIC?c:0;
}
static u32 imp_tile(struct lut4_state *s,const char *name,u8 *xci);
/* Entry i's COLOR tile {u32 length, XCI}, drawn now into one slot (2026-11-07: was a resident slot per
 * entry, 32 x 12.8 KB, drawn at every scan).  2026-11-10 (Bei: "沒用掉的東西不要佔用記憶體"): the slot is
 * borrowed (borrow.c) for a COL-Share sync and returned when it says the tiles are copied (icon(COLS_NONE),
 * imp_icon_done) or when our own sync returns.  The only reader copies it before it asks for the next. */
static void imp_icon_done(struct lut4_state *s) { lut_return(s,&s->b_icon); }
static u8 *imp_icon_slot(struct lut4_state *s,u32 i) {
    const struct imp_section *c=imp_sec(s);
    if(!c || !s->library || i>=s->library->h.count)return 0;
    u8 *slot=lut_borrow(s,&s->b_icon,c->icon_slot);
    if(!slot)return 0;                                    /* recording or no memory: COL-Share's placeholder */
    u32 n=imp_tile(s,s->library->entries[i].name,slot+4);
    slot[0]=(u8)n;slot[1]=(u8)(n>>8);slot[2]=(u8)(n>>16);slot[3]=(u8)(n>>24);
    return slot;
}

/* ---- the COLOR tile ---------------------------------------------------- */
static void imp_label(const char *name,char *out) {
    u32 n=0,len=0;while(name[len])len++;
    if(len>=5u){const char *e=name+len-5u;
        if(e[0]=='.' && (e[1]|32)=='c' && (e[2]|32)=='u' && (e[3]|32)=='b' && (e[4]|32)=='e')len-=5u;}
    for(u32 i=0;i<len && n<IMP_LABEL;i++){u8 c=(u8)name[i];out[n++]=(char)(c>=IMP_FIRST && c<=IMP_LAST?c:'?');}
    if(!n)out[n++]='?';
    out[n]=0;
}
static u32 imp_tile(struct lut4_state *s,const char *name,u8 *xci) {
    const struct imp_section *c=imp_sec(s);if(!c)return 0;
    char text[IMP_LABEL+1u];imp_label(name,text);
    const u8 *atlas=(const u8 *)s->block+c->atlas_off,*table=0;
    u32 width=0;
    for(u32 k=0;k<c->caps;k++) {
        table=atlas+c->cap_table[k];width=0;
        for(u32 i=0;text[i];i++)width+=table[8u*((u8)text[i]-IMP_FIRST)+1u];
        if(width<=IMP_W-2u*IMP_MARGIN)break;
    }
    /* header: xci_literal's, then a literal-only sequence */
    u32 raw=IMP_W*IMP_H*2u,rest=raw-15u,lenbytes=rest/255u+1u,blk=1u+lenbytes+raw;
    for(u32 i=0;i<0x33u;i++)xci[i]=0;
    xci[0]='X';xci[1]='C';
    *(u32 *)(xci+4)=0;
    u32 v=blk+23u;xci[4]=(u8)v;xci[5]=(u8)(v>>8);xci[6]=(u8)(v>>16);xci[7]=(u8)(v>>24);
    xci[8]=(u8)IMP_W;xci[9]=0;xci[10]=(u8)IMP_H;xci[11]=0;
    xci[0xC]=0;xci[0xD]=4;xci[0x10]=2;xci[0x11]=2;
    xci[0x20]=0x04;xci[0x21]=0x22;xci[0x22]=0x4D;xci[0x23]=0x18;xci[0x24]=0x88;xci[0x25]=0x10;
    v=blk+19u;xci[0x26]=(u8)v;xci[0x27]=(u8)(v>>8);xci[0x28]=(u8)(v>>16);xci[0x29]=(u8)(v>>24);
    xci[0x2F]=(u8)blk;xci[0x30]=(u8)(blk>>8);xci[0x31]=(u8)(blk>>16);xci[0x32]=(u8)(blk>>24);
    u8 *p=xci+0x33u;*p++=0xF0;
    for(u32 r=rest;r>=255u;r-=255u)*p++=255;
    *p++=(u8)(rest%255u);
    u8 *pix=p;
    for(u32 i=0;i<raw;i++)pix[i]=0;
    int x=IMP_CENTER-(int)(width/2u);
    u32 top=IMP_BASELINE-IMP_BASE_ROW;
    for(u32 i=0;text[i];i++) {
        const u8 *g=table+8u*((u8)text[i]-IMP_FIRST);
        u32 w=g[0],adv=g[1],off=g[4]|(u32)g[5]<<8|(u32)g[6]<<16|(u32)g[7]<<24;
        const u8 *bits=atlas+off;
        int x0=x-2;
        for(u32 r=0;r<IMP_ATLAS_H;r++) {
            u32 y=top+r;if(y>=IMP_H)continue;
            for(u32 cc=0;cc<w;cc++) {
                int xx=x0+(int)cc;if(xx<0 || xx>=(int)IMP_W)continue;
                u8 *q=pix+2u*(y*IMP_W+(u32)xx);u32 sum=*q+bits[r*w+cc];if(sum>255u)sum=255u;
                q[0]=(u8)sum;q[1]=(u8)sum;
            }
        }
        x+=(int)adv;
    }
    p=pix+raw;p[0]=p[1]=p[2]=p[3]=0;
    return (u32)(p+4-xci);
}

/* ---- the folder -------------------------------------------------------- */
static int imp_is_cube(const u16 *w,char *name) {
    u32 n=0;
    if(w[0]=='.' && w[1]=='_')return 0;                  /* macOS AppleDouble */
    for(;w[n] && n<63u;n++)name[n]=(char)(w[n]<0x80u?w[n]:'?');
    /* all 64 bytes: the caller's buffer is stack, copied whole into the entry,
     * and library_init refuses a name whose byte 63 is not 0 (2026-11-03 camera:
     * leftover stack after the NUL made every camera-written LUT.BIN unloadable) */
    for(u32 i=n;i<64u;i++)name[i]=0;
    if(w[n] || n<6u)return 0;
    const char *e=name+n-5u;
    return e[0]=='.' && (e[1]|32)=='c' && (e[2]|32)=='u' && (e[3]|32)=='b' && (e[4]|32)=='e';
}
static int imp_same_name(const char *a,const char *b) {
    u32 i=0;while(a[i] && a[i]==b[i])i++;
    return a[i]==b[i];
}
static void imp_identity(u8 *sha,u32 size,const u8 *dates,const char *name) {
    for(u32 i=0;i<32u;i++)sha[i]=0;
    u32 h=2166136261u;for(u32 i=0;name[i];i++)h=(h^(u8)name[i])*16777619u;   /* two files, same size and time */
    sha[20]=(u8)h;sha[21]=(u8)(h>>8);sha[22]=(u8)(h>>16);sha[23]=(u8)(h>>24);
    sha[0]='C';sha[1]='A';sha[2]='M';sha[3]='1';
    sha[4]=(u8)size;sha[5]=(u8)(size>>8);sha[6]=(u8)(size>>16);sha[7]=(u8)(size>>24);
    for(u32 i=0;i<12u;i++)sha[8u+i]=dates[i];
}
static const char *imp_path(struct lut4_state *s,const char *name) {
    const struct imp_section *c=imp_sec(s);
    char *p=s->library_path;const char *f=(const char *)s->block+c->folder_off;
    while(*f)*p++=*f++;
    *p++='\\';
    while(*name)*p++=*name++;
    *p=0;return s->library_path;
}
static int imp_q20(const u8 **pp,const u8 *end,u32 limit,i32 *out);
static const u8 *imp_skip(const u8 *p,const u8 *end);
/* A line that starts with key k; its value after it, else 0. */
static const u8 *imp_key(const u8 *buf,u32 i,const char *k) {
    u32 j=0;while(k[j] && buf[i+j]==(u8)k[j])j++;
    return k[j]?0:buf+i+j;
}
static int imp_is(const u8 *v,const char *want) {
    u32 q=0;while(want[q] && v[q]==(u8)want[q])q++;
    return !want[q] && (v[q]=='\r' || v[q]=='\n' || v[q]==0 || v[q]==' ');
}
/* The author's layer from the file's first 4 KiB: # FPSUP_INPUT_COLOR_SPACE /
 * GAMMA, # FPSUP_COLOR_MATRIX standard|off|custom and its # FPSUP_COLOR_MATRIX1 / 2
 * (nine numbers each; one given = both).  The user's layer is kept; an override
 * equal to the new author value goes (library.refresh). */
static void imp_author(struct lut4_state *s,struct lib_entry *e) {
    e->author_flags=e->author_color=e->author_gamma=e->author_matrix=0;
    for(u32 j=0;j<18u;j++)(&e->cm[0][0])[j]=0;
    lib_resolve(e);
    u8 *io=s->svc->uncached(s->svc,(u8 *)s->block+s->cfg->io_off),*buf=io+4096;
    u32 got=0;
    FW(0xC0365E90u,void (*)(void *,u32))(io,1);
    if(!FW(0xC0365FB0u,u32 (*)(void *,const char *,u32))(io,imp_path(s,e->name),1)){FW(0xC0365ED0u,void (*)(void *,u32))(io,2);return;}
    FW(0xC0366060u,u32 (*)(void *,void *,u32,u32 *))(io,buf,4095u,&got);
    FW(0xC0366020u,void (*)(void *))(io);FW(0xC0365ED0u,void (*)(void *,u32))(io,2);
    if(got>4095u)got=4095u;
    buf[got]=0;
    u32 from=got>=3u && buf[0]==0xEF && buf[1]==0xBB && buf[2]==0xBF?3u:0u,rows=0,bad=0,mode=MAT_N;   /* a UTF-8 BOM first */
    i32 m[2][9];
    for(u32 i=from;i<got;i++)if(i==from || buf[i-1u]=='\n') {
        const u8 *v;
        if((v=imp_key(buf,i,string(s,73))))
            for(u32 k=0;k<8u;k++){if(imp_is(v,string(s,77u+k))){e->author_color=k;e->author_flags|=LIB_SPACE;}}
        else if((v=imp_key(buf,i,string(s,74))))
            for(u32 k=0;k<8u;k++){if(imp_is(v,string(s,85u+k))){e->author_gamma=k;e->author_flags|=LIB_GAMMA;}}
        else if((v=imp_key(buf,i,string(s,108))))
            for(u32 k=0;k<MAT_N;k++){if(imp_is(v,string(s,111u+k)))mode=k;}
        else if((v=imp_key(buf,i,string(s,109))) || (v=imp_key(buf,i,string(s,110)))) {
            u32 two=buf[i+20u]=='2';const u8 *q=v,*end=buf+got;
            for(u32 k=0;k<9u && !bad;k++){q=imp_skip(q,end);if(!imp_q20(&q,end,16u,&m[two][k]))bad=1;}
            q=imp_skip(q,end);
            if(q<end && *q!='\r' && *q!='\n')bad=1;
            rows|=two?2u:1u;
        }
    }
    if(rows && !bad) {
        for(u32 k=0;k<9u;k++){e->cm[0][k]=m[rows&1u?0:1][k];e->cm[1][k]=m[rows&2u?1:0][k];}
        e->author_flags|=AUTH_CUSTOM;
    }
    if(mode==MAT_N && rows)mode=MAT_CUSTOM;          /* matrices alone: custom */
    if(mode!=MAT_N){e->author_matrix=mode;e->author_flags|=LIB_MATRIX;}
    if(e->user_flags&LIB_SPACE && e->author_flags&LIB_SPACE && e->user_color==e->author_color)e->user_flags&=~LIB_SPACE;
    if(e->user_flags&LIB_GAMMA && e->author_flags&LIB_GAMMA && e->user_gamma==e->author_gamma)e->user_flags&=~LIB_GAMMA;
    if(e->user_flags&LIB_MATRIX && ((e->author_flags&LIB_MATRIX && e->user_matrix==e->author_matrix) ||
       (e->user_matrix==MAT_CUSTOM && !(e->author_flags&AUTH_CUSTOM))))e->user_flags&=~LIB_MATRIX;
    lib_resolve(e);
}
/* One listing of the folder.  pass 0: a cube with an entry (by name) is seen again
 * (its identity changed: its author lines again); a new one gets a free entry, else
 * is counted.  pass 1 (the catalog was full): each cube still without an entry takes
 * the place of one whose file is not there (user 2026-11-06: reuse those first).
 * Sub-folders (an older card's SOURCES\, JFIT\, DATA\) and other files are passed over. */
static u32 imp_list(struct lut4_state *s,u32 pass,u32 *changed) {
    const struct imp_section *c=imp_sec(s);
    struct lib_catalog *l=s->library;
    u8 *io=s->svc->uncached(s->svc,(u8 *)s->block+s->cfg->io_off),*entry=io+4096;
    u32 holder=0,full=0;
    FW(DIR_CTOR,u32 (*)(u32 *,u32))(&holder,1);
    if(FW(DIR_OPEN,u32 (*)(u32 *,const char *))(&holder,(const char *)s->block+c->folder_off)) {
        for(;;) {
            for(u32 i=0;i<0x238u;i++)entry[i]=0;
            if(!FW(DIR_NEXT,u32 (*)(u32 *,void *))(&holder,entry))break;
            char name[64];
            if(entry[0x218]&0x10u || !imp_is_cube((const u16 *)entry,name))continue;
            u32 size=*(const u32 *)(entry+0x210);
            if(*(const u32 *)(entry+0x214) || size>IMP_MAX_BYTES)continue;
            u8 sha[32];imp_identity(sha,size,entry+0x21A,name);
            u32 k=l->h.count;
            for(u32 i=0;i<l->h.count;i++)if(imp_same_name(l->entries[i].name,name))k=i;
            if(pass) {
                if(k<l->h.count)continue;                     /* has one (pass 0, or taken just now) */
                for(u32 i=0;i<l->h.count && k==l->h.count;i++)if(l->entries[i].origin&0x80000000u)k=i;
                if(k==l->h.count)break;                       /* none left to reuse */
                if(l->h.active==k){l->h.active=LIB_NONE;library_off(s);}
            } else if(k<l->h.count) {
                struct lib_entry *e=&l->entries[k];
                if(e->origin&ORIGIN_GONE)*changed=1;          /* back: its settings with it */
                e->origin&=~(0x80000000u|ORIGIN_GONE);
                if(!library_same(e->sha,sha,32)){copy(e->sha,sha,32);e->source_len=size;e->origin|=0x40000000u;*changed=1;}   /* its author lines again */
                continue;
            } else if(l->h.count<LIB_MAX)k=l->h.count++;
            else {full++;continue;}
            struct lib_entry *e=&l->entries[k];
            for(u32 i=0;i<sizeof *e;i++)((u8 *)e)[i]=0;
            copy(e->sha,sha,32);copy(e->name,name,64);
            e->amount=100u;e->source_len=size;e->origin=ORIGIN_CAMERA|0x40000000u;lib_resolve(e);
            *changed=1;
        }
    }
    FW(DIR_DTOR,void (*)(u32 *,u32))(&holder,2);
    return full;
}
/* List the folder; add new cubes, note changed and missing ones; 1 = the library changed.
 * Works on every entry, the hidden ones too, then partitions them again. */
static int imp_scan(struct lut4_state *s) {
    const struct imp_section *c=imp_sec(s);
    if(!c || !s->library || library_busy() || conv_running(s))return 0;   /* conv.index is an index */
    struct lib_catalog *l=s->library;
    u32 changed=0;
    l->h.count+=s->library_hidden;s->library_hidden=0;
    for(u32 i=0;i<l->h.count;i++)l->entries[i].origin|=0x80000000u;
    if(imp_list(s,0,&changed))imp_list(s,1,&changed);
    for(u32 i=0;i<l->h.count;i++) {
        struct lib_entry *e=&l->entries[i];
        if(e->origin&0x80000000u) {
            e->origin&=~0x80000000u;
            if(!(e->origin&ORIGIN_GONE)){e->origin|=ORIGIN_GONE;changed=1;}
            if(l->h.active==i){l->h.active=LIB_NONE;library_off(s);}
        }
        if(e->origin&0x40000000u){e->origin&=~0x40000000u;imp_author(s,e);}
    }
    if(library_partition(s))changed=1;
    if(changed)library_save(s);
    return (int)changed;
}

/* ---- the asset --------------------------------------------------------- */
/* q = n / d, 64-bit, by shifts (no EABI division helper here) */
static u64 imp_div(u64 n,u64 d,u64 *rem) {
    u64 q=0,r=0;
    for(u32 b=0;b<64u;b++){r=(r<<1)|(n>>63);n<<=1;q<<=1;if(r>=d){r-=d;q|=1u;}}
    *rem=r;return q;
}
/* A decimal number -> round(value * 2^20), ties to even (np.rint); 0 = bad or past `limit`. */
static int imp_q20(const u8 **pp,const u8 *end,u32 limit,i32 *out) {
    const u8 *p=*pp;int neg=0,exp10=0,digits=0,any=0;u64 m=0;
    if(p<end && (*p=='-' || *p=='+')){neg=*p=='-';p++;}
    while(p<end && *p>='0' && *p<='9'){any=1;if(digits<18){m=m*10u+(*p-'0');if(m)digits++;}else exp10++;p++;}
    if(p<end && *p=='.'){p++;while(p<end && *p>='0' && *p<='9'){any=1;if(digits<18){m=m*10u+(*p-'0');if(m)digits++;exp10--;}p++;}}
    if(!any)return 0;
    if(p<end && (*p=='e' || *p=='E')) {
        p++;int en=0,e=0;if(p<end && (*p=='-' || *p=='+')){en=*p=='-';p++;}
        if(p>=end || *p<'0' || *p>'9')return 0;
        while(p<end && *p>='0' && *p<='9'){if(e<1000)e=e*10+(*p-'0');p++;}
        exp10+=en?-e:e;
    }
    *pp=p;
    u64 lim=(u64)limit<<20,q;
    if(!m){*out=0;return 1;}
    if(exp10>=0) {
        q=m;for(int i=0;i<exp10;i++){if(q>lim)return 0;q*=10u;}
        if(q>((u64)limit))return 0;
        q<<=20;
    } else {
        int k=-exp10;u64 r,d=1;
        /* keep m << 20 in 64 bits, and 10^k too: dropped digits are far below a Q20 step */
        while((m>>43) || k>19){m=imp_div(m,10u,&r);k--;if(!m){*out=0;return 1;}}
        if(k<0){for(;k<0;k++){if(m>(u64)limit)return 0;m*=10u;}k=0;}
        for(int i=0;i<k;i++)d*=10u;
        q=imp_div(m<<20,d,&r);
        u64 twice=r<<1;
        if(twice>d || (twice==d && (q&1u)))q++;
    }
    if(q>lim)return 0;
    *out=neg?-(i32)q:(i32)q;return 1;
}
static int imp_word(const u8 *p,const u8 *end,const char *w) {
    u32 i=0;while(w[i]){if(p+i>=end || p[i]!=(u8)w[i])return 0;i++;}
    return p+i>=end || p[i]==' ' || p[i]=='\t' || p[i]=='\r' || p[i]=='\n';
}
static const u8 *imp_skip(const u8 *p,const u8 *end) { while(p<end && (*p==' ' || *p=='\t'))p++; return p; }

/* Build the asset for entry i from its file, into the borrowed asset area (borrow.c). */
static int imp_asset(struct lut4_state *s,unsigned index) {
    const struct imp_section *c=imp_sec(s);
    struct lib_entry *e=&s->library->entries[index];
    if(!c || (e->origin&ORIGIN_GONE))return NO_FILE;
    u8 *a=s->b_asset.p;u32 cap=s->cfg->asset_cap;         /* borrowed by the caller (library_load_index) */
    if(!a)return NO_MEMORY;
    u32 header=256u,body=header+c->const_len;
    if(body>cap)return BAD_ASSET;
    for(u32 i=0;i<header;i++)a[i]=0;
    copy(a+header,(const u8 *)s->block+c->const_off,c->const_len);
    u8 *io=s->svc->uncached(s->svc,(u8 *)s->block+s->cfg->io_off),*buf=io+4096;
    FW(0xC0365E90u,void (*)(void *,u32))(io,1);
    if(!FW(0xC0365FB0u,u32 (*)(void *,const char *,u32))(io,imp_path(s,e->name),1)){FW(0xC0365ED0u,void (*)(void *,u32))(io,2);return NO_FILE;}
    u32 n1=0,n3=0,rows=0,want=0,at=body,dom=0,r1=0,r3=0,bad=0,first=1,title_n=0;
    i32 dmin[3]={0,0,0},dmax[3]={1<<20,1<<20,1<<20},rng[2][2]={{0,1<<20},{0,1<<20}};
    char line[256];u32 ln=0;u32 got=0,eof=0;
    while(!bad) {
        FW(0xC0366060u,u32 (*)(void *,void *,u32,u32 *))(io,buf,4096u,&got);
        if(got>4096u)got=4096u;
        if(!got)eof=1;
        for(u32 i=0;i<=got && !bad;i++) {
            u8 ch=i<got?buf[i]:'\n';
            if(i==got && !eof)break;
            if(ch!='\n' && ch!='\r'){if(ln<255u)line[ln++]=(char)ch;else bad=1;continue;}
            const u8 *p=(const u8 *)line,*end=p+ln;ln=0;
            if(first && end-p>=3 && p[0]==0xEF && p[1]==0xBB && p[2]==0xBF)p+=3;
            first=0;
            p=imp_skip(p,end);
            if(p>=end || *p=='#')continue;
            if(imp_word(p,end,string(s,96))) {
                if(rows)bad=1;
                const u8 *q=imp_skip(p+5,end);
                if(q<end && *q=='"'){q++;while(q<end && *q!='"' && title_n<63u)a[168u+title_n++]=*q++;}
                continue;
            }
            if(imp_word(p,end,string(s,97)) || imp_word(p,end,string(s,98))) {
                int three=p[4]=='3';const u8 *q=imp_skip(p+11,end);u32 v=0;
                while(q<end && *q>='0' && *q<='9')v=v*10u+(*q++-'0');
                if(rows || v<2u || v>(three?65u:4096u))bad=1;
                if(three)n3=v;else n1=v;
                want=n1+n3*n3*n3;continue;
            }
            if(imp_word(p,end,string(s,99)) || imp_word(p,end,string(s,100))) {
                i32 *t=p[8]=='I'?dmin:dmax;const u8 *q=p+10;
                for(u32 k=0;k<3u;k++){q=imp_skip(q,end);if(!imp_q20(&q,end,128u,&t[k]))bad=1;}
                dom=1;continue;
            }
            if(imp_word(p,end,string(s,101)) || imp_word(p,end,string(s,102))) {
                int three=p[4]=='3';const u8 *q=p+18;i32 *t=rng[three];
                for(u32 k=0;k<2u;k++){q=imp_skip(q,end);if(!imp_q20(&q,end,128u,&t[k]))bad=1;}
                if(three)r3=1;else r1=1;continue;
            }
            /* a row */
            if(!want || rows>=want){bad=1;break;}
            if(rows==0) {                               /* the layout, now the sizes are known */
                if(at+4u*3u*want>cap){bad=1;break;}
            }
            const u8 *q=p;
            for(u32 k=0;k<3u;k++) {
                q=imp_skip(q,end);i32 v;
                if(!imp_q20(&q,end,1024u,&v)){bad=1;break;}
                u8 *o=a+at+12u*rows+4u*k;o[0]=(u8)v;o[1]=(u8)(v>>8);o[2]=(u8)(v>>16);o[3]=(u8)(v>>24);
            }
            if(imp_skip(q,end)!=end)bad=1;
            rows++;
        }
        if(eof)break;
    }
    FW(0xC0366020u,void (*)(void *))(io);FW(0xC0365ED0u,void (*)(void *,u32))(io,2);
    if(bad || !want || rows!=want || (n1 && n3 && dom) || (dom && (r1 || r3)) || (!n1 && r1) || (!n3 && r3))
        return BAD_ASSET;
    u32 total=at+12u*want;
    /* header (build_sup.asset) */
    u32 *h=(u32 *)a;
    h[0]=0x31554c46u;h[1]=1;h[2]=header;h[3]=total;h[4]=0;h[5]=n1;h[6]=n3;h[7]=27u*256u+1u;
    h[8]=header;h[9]=header+8u*9u*4u;h[10]=n1?at:0;h[11]=n3?at+12u*n1:0;
    h[12]=e->color;h[13]=e->gamma;h[14]=e->amount;h[15]=1;
    for(u32 k=0;k<2u;k++) {
        i32 *t=(i32 *)(a+(k?100u:64u));
        for(u32 ch=0;ch<3u;ch++) {
            int has=k?r3:r1;
            t[ch]=has?rng[k][0]:dmin[ch];t[3u+ch]=has?rng[k][1]:dmax[ch];
            if(t[3u+ch]<=t[ch])return BAD_ASSET;
        }
        t[6]=t[7]=t[8]=0;
    }
    copy(a+136u,e->sha,32);
    if(!title_n){const char *d=string(s,103);while(d[title_n]){a[168u+title_n]=(u8)d[title_n];title_n++;}}
    h[4]=0;h[4]=cube_fnv(2166136261u,a,total);
    int r=validate((struct asset *)a,cap);
    if(r==OK){s->asset=(struct asset *)a;s->color=e->color;s->gamma=e->gamma;s->amount=e->amount;}
    return r;
}
