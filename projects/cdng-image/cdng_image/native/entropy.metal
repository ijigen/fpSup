// Parallel LJ92 entropy writer. CPU provides only the tiny canonical tables.
// Every stage is ordered in one command buffer, without intermediate readback.
inline uint cdng_scan(uint value, uint lid, threadgroup uint *sums) {
    uint lane=lid&31, simd=lid>>5;
    uint prefix=simd_prefix_exclusive_sum(value);
    uint total=simd_sum(value);
    if(!lane) sums[simd]=total;
    threadgroup_barrier(mem_flags::mem_threadgroup);
    if(!lid) {
        uint carry=0;
        for(uint i=0;i<8;i++) { uint n=sums[i];sums[i]=carry;carry+=n; }
        sums[8]=carry;
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    return sums[simd]+prefix;
}

kernel void cdng_entropy_blocks(
    device const ushort *pixels [[buffer(0)]],
    device const uint *codes [[buffer(1)]],
    device const uint *predictors [[buffer(2)]],
    device uint *parts [[buffer(3)]],
    device uint *counts [[buffer(4)]],
    constant uint4 &params [[buffer(5)]],
    device uint *suboff [[buffer(6)]],
    device const uint *source_indices [[buffer(7)]],
    uint2 group [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]]) {
    threadgroup atomic_uint words[256];
    threadgroup uint sums[9];
    atomic_store_explicit(&words[lid],0,memory_order_relaxed);
    const uint count=params.x,stride=params.y,bits=params.z;
    const uint blocks=(count+255)/256, i=group.x*256+lid;
    // Scratch/output tiles are compact; source pixels may retain the full
    // original batch so a later predictor attempt need not gather/copy tiles.
    pixels+=source_indices[group.y]*count; codes+=group.y*34;
    uint value=0,length=0;
    if(i<count) {
        uint col=i%stride,row=i/stride,p=predictors[group.y];
        int a=col>=2 ? pixels[i-2] : 0;
        int b=row ? pixels[i-stride] : 0;
        int c=(row && col>=2) ? pixels[i-stride-2] : 0;
        int prediction;
        if(!row && col<2) prediction=1<<(bits-1);
        else if(!row) prediction=a;
        else if(col<2) prediction=b;
        else switch(p) {
            case 1:prediction=a;break; case 2:prediction=b;break;
            case 3:prediction=c;break; case 4:prediction=a+b-c;break;
            case 5:prediction=a+((b-c)>>1);break;
            case 6:prediction=b+((a-c)>>1);break;
            default:prediction=(a+b)>>1;break;
        }
        int diff=int(short(int(pixels[i])-prediction));
        uint magnitude=uint(abs(diff)), category=magnitude ? 32u-clz(magnitude) : 0;
        uint code=codes[(i&1)*17+category], extra=category&15;
        length=(code>>16)+extra;
        uint amplitude=uint(diff<0 ? diff-1 : diff)&((1u<<extra)-1);
        value=((code&65535)<<extra)|amplitude;
    }
    uint offset=cdng_scan(length,lid,sums);
    // Every16-pixel checkpoint lets the RAW checker shorten its serial decode
    // chain; contiguous bit-range checks still cover every encoded sample.
    if(!(lid&15)) suboff[(group.y*((count+255)/256)+group.x)*16+lid/16]=offset;
    // cdng_scan's barrier also completes initialization of the local words.
    if(length) {
        uint w=offset>>5, used=offset&31;
        if(used+length<=32)
            atomic_fetch_or_explicit(&words[w],value<<(32-used-length),memory_order_relaxed);
        else {
            atomic_fetch_or_explicit(&words[w],value>>(used+length-32),memory_order_relaxed);
            atomic_fetch_or_explicit(&words[w+1],value<<(64-used-length),memory_order_relaxed);
        }
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    uint block=group.y*blocks+group.x;
    parts[block*256+lid]=atomic_load_explicit(&words[lid],memory_order_relaxed);
    if(!lid) counts[block]=sums[8];
}

kernel void cdng_entropy_prefix(
    device const uint *counts [[buffer(0)]],
    device uint *offsets [[buffer(1)]],
    device uint *totals [[buffer(2)]],
    constant uint2 &params [[buffer(3)]],
    uint tile [[thread_position_in_grid]]) {
    if(tile>=params.y) return;
    uint carry=0;
    for(uint b=0;b<params.x;b++) {
        uint i=tile*params.x+b; offsets[i]=carry;carry+=counts[i];
    }
    totals[tile]=carry;
}

kernel void cdng_entropy_join(
    device const uint *parts [[buffer(0)]],
    device const uint *counts [[buffer(1)]],
    device const uint *offsets [[buffer(2)]],
    device const uint *totals [[buffer(3)]],
    device uint *words [[buffer(4)]],
    device uint *ff_local [[buffer(5)]],
    device uint *ff_counts [[buffer(6)]],
    constant uint2 &params [[buffer(7)]],
    uint2 group [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]]) {
    threadgroup uint sums[9];
    uint blocks=(params.x+255)/256, max_words=params.y;
    uint tile=group.y,w=group.x*256+lid, pos=w*32;
    uint tile_bits=totals[tile], value=0, ffs=0;
    if(w<max_words && pos<tile_bits) {
        uint lo=0,hi=blocks;
        while(lo+1<hi) { uint mid=(lo+hi)/2; if(offsets[tile*blocks+mid]<=pos)lo=mid;else hi=mid; }
        uint block=tile*blocks+lo, local=pos-offsets[block], shift=local&31;
        uint at=block*256+(local>>5);
        value=parts[at]<<shift;
        if(shift) value|=parts[at+1]>>(32-shift);
        uint remaining=counts[block]-local;
        if(remaining<32 && lo+1<blocks) value|=parts[(block+1)*256]>>remaining;
        words[tile*max_words+w]=value;
        uint n=min(4u,(tile_bits+7)/8-w*4);
        for(uint b=0;b<n;b++) ffs+=((value>>(24-b*8))&255)==255;
    }
    uint prefix=cdng_scan(ffs,lid,sums);
    if(w<max_words) ff_local[tile*max_words+w]=prefix;
    if(!lid) ff_counts[tile*((max_words+255)/256)+group.x]=sums[8];
}

kernel void cdng_entropy_stuff(
    device const uint *words [[buffer(0)]],
    device const uint *ff_local [[buffer(1)]],
    device const uint *ff_offsets [[buffer(2)]],
    device const uint *totals [[buffer(3)]],
    device uchar *output [[buffer(4)]],
    constant uint2 &params [[buffer(5)]],
    uint2 group [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]]) {
    uint tile=group.y,w=group.x*256+lid,max_words=params.x;
    uint bytes=(totals[tile]+7)/8;
    if(w>=max_words || w*4>=bytes) return;
    uint value=words[tile*max_words+w];
    uint dst=tile*params.y+w*4+ff_local[tile*max_words+w]
        +ff_offsets[tile*((max_words+255)/256)+group.x];
    uint n=min(4u,bytes-w*4);
    for(uint b=0;b<n;b++) {
        uchar byte=uchar(value>>(24-b*8));output[dst++]=byte;
        if(byte==255) output[dst++]=0;
    }
}
