/* Per-cube settings and inclusion list, following res-custom's own-file
 * writeback: refuse recording, confirm the existing file, seek, write, read
 * back.  Every entry is a .cube in \fpSup\LUT\ (import.c) and its settings live
 * here only (2026-11-06, Bei: the list is the folder; no built-in LUTs).
 *
 * In RAM, entries[0..h.count) are the cubes whose file is there -- all that any
 * list, the COLOR rows or an index ever sees -- and the next s->library_hidden
 * entries are those whose file went: kept, settings and all, for when the same
 * file comes back (import.c imp_scan, library_partition).  On the card the
 * header counts both (library_disk). */
static int library_busy(void) {
    u32 selector=*(volatile u32 *)(uintptr_t)0xC347D1D4u;
    uintptr_t rec=selector==0x21u?0xC3476609u:0xC347E08Fu;
    return *(volatile u8 *)rec || *(volatile u32 *)(uintptr_t)0xC358E140u ||
           *(volatile u8 *)(uintptr_t)0xC35A952Cu;
}
static u32 library_bytes(const struct lib_catalog *l) { return 64u+(u32)sizeof(struct lib_entry)*l->h.count; }
static u32 library_hash(const struct lib_catalog *l) {
    const u8 *p=(const u8 *)l;u32 h=2166136261u,n=library_bytes(l);
    for(u32 i=0;i<n;i++) h=(h^((i>=24u && i<28u)?0u:p[i]))*16777619u;
    return h;
}
static int library_same(const void *a,const void *b,u32 n) {
    const u8 *x=a,*y=b;for(u32 i=0;i<n;i++)if(x[i]!=y[i])return 0;return 1;
}
/* The effective values from the two layers (library.resolved). */
static int lib_fits(u32 color,u32 g) { return (color==2u)==(g>=6u); }
static void lib_resolve(struct lib_entry *e) {
    u32 a=e->author_flags,u=e->user_flags;
    u32 ug=u&LIB_GAMMA?e->user_gamma:G_NONE,ag=a&LIB_GAMMA?e->author_gamma:G_NONE;
    u32 first=ug!=G_NONE?ug:ag;
    e->color=u&LIB_SPACE?e->user_color:a&LIB_SPACE?e->author_color:first!=G_NONE && first>=6u?2u:6u;
    u32 g=ug!=G_NONE && lib_fits(e->color,ug)?ug:ag!=G_NONE && lib_fits(e->color,ag)?ag:G_NONE;
    e->gamma=g==G_NONE?0u:g>=6u?g-6u:g;
    u32 m=MAT_N;
    if(u&LIB_MATRIX && (e->user_matrix!=MAT_CUSTOM || a&AUTH_CUSTOM))m=e->user_matrix;
    else if(a&LIB_MATRIX)m=e->author_matrix==MAT_CUSTOM && !(a&AUTH_CUSTOM)?MAT_N:e->author_matrix;
    else m=MAT_OFF;                                     /* the author gave none: Off (user 11-05; library.resolved) */
    e->matrix=m==MAT_N?MAT_STANDARD:m;
    e->flags=(e->flags&LIB_ENABLED)|(u&LIB_SPACE || a&LIB_SPACE?LIB_SPACE:0u)|(g!=G_NONE?LIB_GAMMA:0u)|(m!=MAT_N?LIB_MATRIX:0u);
}
/* The user's choice of one field: the author's own value is no override (it clears one). */
static void lib_choose(struct lib_entry *e,u32 bit,u32 value,u32 author,u32 *user) {
    if(e->author_flags&bit && author==value)e->user_flags&=~bit;
    else {e->user_flags|=bit;*user=value;}
}
#include "cube4.c"
static int library_file_guard(struct lut4_state *s,void *io,u8 *buf) {
    if(!s->self_path || s->svc->file_is(s->svc,s->self_path,s->block,64u)!=SL_OK)return 0;
    u32 got=0,ok=0;
    FW(0xC0365E90u,void (*)(void *,u32))(io,1);
    if(FW(0xC0365FB0u,u32 (*)(void *,const char *,u32))(io,s->self_path,1)) {
        if(FW(0xC03661E0u,u32 (*)(void *,u32,u32))(io,s->cfg->library_off,0)) {
            FW(0xC0366060u,u32 (*)(void *,void *,u32,u32 *))(io,buf,64,&got);
            ok=got==64u && library_same(buf,s->library_guard,64);
        }
        FW(0xC0366020u,void (*)(void *))(io);
    }
    FW(0xC0365ED0u,void (*)(void *,u32))(io,2);return (int)ok;
}
/* The catalog as the card holds it: the header counts the hidden entries too
 * (library_init checks the stored checksum over all of them); -> its bytes. */
static u32 library_disk(const struct lut4_state *s,struct lib_header *d) {
    const struct lib_catalog *l=s->library;
    copy(d,&l->h,sizeof *d);d->count=l->h.count+s->library_hidden;d->reserved=0;
    const u8 *p=(const u8 *)d;u32 h=2166136261u,n=64u+(u32)sizeof(struct lib_entry)*d->count;
    for(u32 i=0;i<64u;i++) h=(h^((i>=24u && i<28u)?0u:p[i]))*16777619u;
    p=(const u8 *)l->entries;
    for(u32 i=64u;i<n;i++) h=(h^p[i-64u])*16777619u;
    d->checksum=h;return n;
}
/* byte pos of the card's image: the header from d, the entries from RAM */
static u8 library_byte(const struct lut4_state *s,const struct lib_header *d,u32 pos) {
    return pos<64u?((const u8 *)d)[pos]:((const u8 *)s->library)[pos];
}
static int library_save(struct lut4_state *s) {
    if(library_busy())return RECORD_BUSY;
    u8 *io=s->svc->uncached(s->svc,(u8 *)s->block+s->cfg->io_off),*buf=io+4096;
    if(!library_file_guard(s,io,buf))return SAVE_FAILED;
    struct lib_header disk;u32 n=library_disk(s,&disk),ok=0;
    FW(0xC0365E90u,void (*)(void *,u32))(io,1);
    if(FW(0xC0365FB0u,u32 (*)(void *,const char *,u32))(io,s->self_path,7)) {
        if(FW(0xC03661E0u,u32 (*)(void *,u32,u32))(io,s->cfg->library_off,0)) {
            u32 pos=0;
            while(pos<n) {
                u32 take=n-pos;if(take>4096u)take=4096u;
                for(u32 i=0;i<take;i++)buf[i]=library_byte(s,&disk,pos+i);
                if(!FW(0xC03660E8u,u32 (*)(void *,const void *,u32))(io,buf,take))break;
                pos+=take;
            }
            if(pos==n && FW(0xC03661E0u,u32 (*)(void *,u32,u32))(io,s->cfg->library_off,0)) {
                pos=0;
                while(pos<n) {
                    u32 take=n-pos,got=0,same=1;if(take>4096u)take=4096u;
                    FW(0xC0366060u,u32 (*)(void *,void *,u32,u32 *))(io,buf,take,&got);
                    for(u32 i=0;i<take && same;i++)same=buf[i]==library_byte(s,&disk,pos+i);
                    if(got!=take || !same)break;
                    pos+=take;
                }
                ok=pos==n;
            }
        }
        FW(0xC0366020u,void (*)(void *))(io);
    }
    FW(0xC0365ED0u,void (*)(void *,u32))(io,2);
    if(ok){copy(s->library_guard,&disk,64);return OK;}
    return SAVE_FAILED;
}
static void library_off(struct lut4_state *s) { s->asset=0;s->file_status=NO_ACTIVE; }
/* Present entries first, in their order, then the hidden ones (origin ORIGIN_GONE);
 * h.count = the present.  The active entry is followed by its identity.  1 = moved. */
static int library_partition(struct lut4_state *s) {
    struct lib_catalog *l=s->library;
    u32 total=l->h.count+s->library_hidden,w=0,moved=0,active=l->h.active;
    u8 key[32];if(active!=LIB_NONE)copy(key,l->entries[active].sha,32);
    for(u32 i=0;i<total;i++) if(!(l->entries[i].origin&ORIGIN_GONE)) {
        if(i!=w) {
            struct lib_entry t;copy(&t,&l->entries[i],sizeof t);
            for(u32 j=i;j>w;j--)copy(&l->entries[j],&l->entries[j-1u],sizeof t);
            copy(&l->entries[w],&t,sizeof t);moved=1;
        }
        w++;
    }
    l->h.count=w;s->library_hidden=total-w;l->h.active=LIB_NONE;
    if(active!=LIB_NONE)for(u32 i=0;i<w;i++)if(library_same(l->entries[i].sha,key,32))l->h.active=i;
    if(active!=LIB_NONE && l->h.active==LIB_NONE)library_off(s);
    l->h.checksum=library_hash(l);
    return (int)moved;
}
static int library_load_index(struct lut4_state *s,u32 index) {
    if(!s->library || index>=s->library->h.count){library_off(s);return NO_ACTIVE;}
    struct lib_entry *e=&s->library->entries[index];
    if(e->origin&ORIGIN_GONE){library_off(s);return BAD_ASSET;}
    if((e->flags&LIB_ALL)!=LIB_ALL){library_off(s);return MODEL_PENDING;}
    /* the cube is parsed into a borrowed area (borrow.c): kept when the caller holds one for
     * its own use (a fit, the render API), returned at once otherwise -- then this is the check
     * that the file still parses as its record says, and s->asset stays 0.  No area: nothing changes. */
    int own=!s->b_asset.raw;
    /* 2026-11-10 (Bei: switching COLOR then MENU is slow): with no area of the caller's this was only a check --
     * parse the whole .cube (65^3 = 6-7 MB of text) and hash it, then throw it away -- on every pick and at boot.
     * The work that needs the cube (a fit, a conversion, the render API) holds its own area and still parses it;
     * the pick / boot path only selects when the entry's .JFT is there (the tables come from it; its name and header
 * carry the cube's byte size + name, not its dates: imp_identity, lvb_jpath, conv_score); without one the old check
 * runs as before.  A cube whose size changed has no .JFT (imp_scan writes the new identity), and a malformed or
 * pending one never gets one (conv_inputs parses it here with an area held).  A same-size edit keeps the old .JFT. */
    if(own && conv_score(s,index)) {                 /* converted (its .JFT for this key): select only */
        s->asset=0;s->file_status=OK;
        s->color=e->color;s->gamma=e->gamma;s->amount=e->amount;
        s->rendered=s->outside1=s->outside3=0;return OK;
    }
    if(own && !lut_borrow(s,&s->b_asset,s->cfg->asset_cap))return library_busy()?RECORD_BUSY:NO_MEMORY;
    int rc=imp_asset(s,index);                     /* the folder's .cube, parsed here */
    if(rc==OK && !library_same(s->asset->source_sha256,e->sha,32))rc=BAD_ASSET;
    if(own){lut_return(s,&s->b_asset);s->asset=0;}
    s->file_status=rc;
    if(rc!=OK){s->asset=0;return rc;}
    s->color=e->color;s->gamma=e->gamma;s->amount=e->amount;
    s->rendered=s->outside1=s->outside3=0;return OK;
}
/* A request in effective terms (the settings rows): it becomes the user's layer.
 * A field set to the author's value clears its override; an unset field
 * (flags without the bit, a family change) clears it too -- the author's value,
 * if it fits, comes back. */
static int library_apply(struct lut4_state *s,u32 index,const struct lib_entry *want) {
    if(library_busy())return s->last_error=RECORD_BUSY;
    struct lib_entry *e=&s->library->entries[index],before;copy(&before,e,sizeof before);
    u32 old_sum=s->library->h.checksum,old_active=s->library->h.active;
    copy(e,want,sizeof *e);lib_resolve(e);
    if(library_same(e,&before,sizeof before))return s->last_error=OK;
    if(s->library->h.active==index && (e->flags&LIB_ALL)!=LIB_ALL)s->library->h.active=LIB_NONE;
    s->library->h.checksum=library_hash(s->library);
    int rc=library_save(s);                        /* the user's layer too: the .cube is never written */
    if(rc!=OK){copy(e,&before,sizeof before);s->library->h.checksum=old_sum;s->library->h.active=old_active;return s->last_error=rc;}
    if(old_active==index && s->library->h.active==LIB_NONE)library_off(s);
    if(s->library->h.active==index){s->color=e->color;s->gamma=e->gamma;s->amount=e->amount;}
    choices(s);refresh(s);return s->last_error=OK;
}
static int library_update(struct lut4_state *s,u32 index,u32 color,u32 gamma,u32 amount,u32 flags) {
    if(!s->library || index>=s->library->h.count || color>=8u || gamma>=(color==2?2u:6u) ||
       amount>100u || (amount%25u && amount%20u) || flags>LIB_ALL)return SL_BADARG;   /* 25 % steps, or the box's 20 % */
    struct lib_entry want;copy(&want,&s->library->entries[index],sizeof want);
    want.flags=(want.flags&~LIB_ENABLED)|(flags&LIB_ENABLED);want.amount=amount;
    if(flags&LIB_SPACE)lib_choose(&want,LIB_SPACE,color,want.author_color,&want.user_color);
    else want.user_flags&=~LIB_SPACE;
    if(flags&LIB_GAMMA)lib_choose(&want,LIB_GAMMA,color==2u?6u+gamma:gamma,want.author_gamma,&want.user_gamma);
    else want.user_flags&=~LIB_GAMMA;
    return library_apply(s,index,&want);
}
static int library_set_matrix(struct lut4_state *s,u32 index,u32 m) {
    if(!s->library || index>=s->library->h.count || m>=MAT_N)return SL_BADARG;
    struct lib_entry want;copy(&want,&s->library->entries[index],sizeof want);
    if(m==MAT_CUSTOM && !(want.author_flags&AUTH_CUSTOM))return s->last_error=SL_BADARG;   /* only the author's matrices */
    lib_choose(&want,LIB_MATRIX,m,want.author_matrix,&want.user_matrix);
    return library_apply(s,index,&want);
}
static int library_enabled(struct lut4_state *s,u32 index,u32 on) {
    if(!s->library || index>=s->library->h.count || on>1u)return SL_BADARG;
    if(library_busy())return s->last_error=RECORD_BUSY;
    u32 active=s->library->h.active;
    if(!on && active==index)s->library->h.active=LIB_NONE;
    struct lib_entry *e=&s->library->entries[index];
    int rc=library_update(s,index,e->color,e->gamma,e->amount,on?e->flags|1u:e->flags&~1u);
    if(rc!=OK)s->library->h.active=active;
    else if(!on && active==index)library_off(s);
    return s->last_error=rc;
}
static int library_pick(struct lut4_state *s,u32 index) {
    if(!s->library || (index!=LIB_NONE && index>=s->library->h.count))return SL_BADARG;
    if(library_busy())return s->last_error=RECORD_BUSY;
    u32 before=s->library->h.active,old_sum=s->library->h.checksum;
    if(index!=LIB_NONE) {
        struct lib_entry *e=&s->library->entries[index];
        if(!(e->flags&1u) || (e->flags&LIB_READY)!=LIB_READY)return s->last_error=MODEL_PENDING;
        int loaded=library_load_index(s,index);
        if(loaded!=OK){library_load_index(s,before);return s->last_error=loaded;}
    }
    s->library->h.active=index;s->library->h.checksum=library_hash(s->library);
    int rc=library_save(s);
    if(rc!=OK) {
        s->library->h.active=before;s->library->h.checksum=old_sum;
        library_load_index(s,before);return s->last_error=rc;
    }
    if(index==LIB_NONE)library_off(s);
    choices(s);return s->last_error=OK;
}
static int item_enabled_get(void *arg) {
    struct lib_entry *e=edited(arg);return e && (e->flags&1u)?1:0;
}
static int item_enabled_set(void *arg,int on) {
    struct lut4_state *s=arg;return on<0?SL_BADARG:library_enabled(s,s->edit_index,(u32)on);
}
/* An older card's LUT.BIN also holds entries prepared on a computer (origin 0: the
 * built-in demo LUTs, SOURCES\ / DATA\ files).  The list is the folder now
 * (2026-11-06): they go from RAM here, the active one with them, and from the card
 * with the next save.  No write for this alone (library_save is the only writer). */
static void library_drop_prepared(struct lut4_state *s) {
    struct lib_catalog *l=s->library;u32 w=0,active=LIB_NONE;
    for(u32 i=0;i<l->h.count;i++) if(l->entries[i].origin&ORIGIN_CAMERA) {
        if(i==l->h.active)active=w;
        if(i!=w)copy(&l->entries[w],&l->entries[i],sizeof l->entries[0]);
        w++;
    }
    l->h.count=w;l->h.active=active;l->h.checksum=library_hash(l);
}
static void library_init(struct lut4_state *s) {
    if(!s->cfg->library_off){s->file_status=read_asset_path(s,string(s,0));return;}
    s->ui_view=VIEW_MANAGER;s->file_status=BAD_ASSET;
    const struct sl4_header *h=s->block;u32 off=s->cfg->library_off;
    if(off<80u || off>h->file_len || h->file_len-off<64u)return;
    struct lib_catalog *l=(struct lib_catalog *)((u8 *)s->block+off);
    if(l->h.magic!=LIB_MAGIC || l->h.version!=3u || l->h.header_len!=64u || l->h.record_len!=sizeof(struct lib_entry) ||
       l->h.count>LIB_MAX || l->h.reserved || library_bytes(l)>h->file_len-off ||
       (l->h.active!=LIB_NONE && l->h.active>=l->h.count) || l->h.checksum!=library_hash(l))return;
    for(u32 i=0;i<l->h.count;i++) {
        struct lib_entry *e=&l->entries[i];
        if(!e->name[0] || e->name[63] || e->color>=8u || e->gamma>=(e->color==2?2u:6u) ||
           e->amount>100u || (e->amount%25u && e->amount%20u) || e->flags>LIB_ALL)return;
        if(e->author_flags&~(LIB_READY|AUTH_CUSTOM) || e->user_flags&~LIB_READY || e->author_color>=8u ||
           e->author_gamma>=8u || e->author_matrix>=MAT_N || e->user_color>=8u || e->user_gamma>=8u ||
           e->user_matrix>=MAT_N || e->reserved0[0] || e->reserved0[1] || e->reserved0[2] ||
           e->reserved1[0] || e->reserved1[1])return;
        {const i32 *c=&e->cm[0][0];for(u32 j=0;j<18u;j++)if(c[j]<-16*(1<<20) || c[j]>16*(1<<20))return;}
        /* the effective values are the layers': resolved again here, not compared -- a rule change (11-05: no
         * author matrix -> Off, was Standard) made every saved record differ and the whole library was refused
         * (camera 11-05: an empty manager).  The checksum above already stands for the bytes. */
        lib_resolve(e);
        if(e->origin>3u || e->source_len>CUBE_MAX || e->source_options>1u)return;
        for(u32 j=0;j<i;j++)if(library_same(e->sha,l->entries[j].sha,32))return;
    }
    s->library=l;copy(s->library_guard,l,64);s->library_hidden=0;
    library_drop_prepared(s);
    imp_scan(s);                                 /* the folder's .cube files */
    library_partition(s);                        /* (scanned: done already; not scanned: the saved GONE marks) */
    if(l->h.active!=LIB_NONE && (l->entries[l->h.active].flags&LIB_ALL)!=LIB_ALL)l->h.active=LIB_NONE;
    l->h.checksum=library_hash(l);
    library_load_index(s,l->h.active);
    s->enabled_row.kind=SL_ROW_TOGGLE;s->enabled_row.title=string(s,47);
    s->enabled_row.get=item_enabled_get;s->enabled_row.set=item_enabled_set;s->enabled_row.arg=s;
}
