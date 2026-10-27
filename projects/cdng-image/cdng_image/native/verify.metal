// Verify the actual stuffed output, independently decoding every DC difference.
// Block boundaries are only acceleration metadata, never JPEG restart markers.
// Coverage checks prove contiguous consumption of the whole entropy stream.
kernel void cdng_check_unstuff(
    device const uchar *encoded [[buffer(0)]],
    device const uint *ff_local [[buffer(1)]],
    device const uint *ff_offsets [[buffer(2)]],
    device const uint *totals [[buffer(3)]],
    device const uint *ff_totals [[buffer(4)]],
    device uint *decoded_words [[buffer(5)]],
    device atomic_uint *errors [[buffer(6)]],
    constant uint2 &params [[buffer(7)]],
    uint2 group [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]]) {
    const uint tile=group.y,w=group.x*256+lid,max_words=params.x;
    const uint raw_bytes=(totals[tile]+7)/8,body_bytes=raw_bytes+ff_totals[tile];
    if(w>=max_words || w*4>=raw_bytes) return;
    const uint groups=(max_words+255)/256;
    uint start=w*4+ff_local[tile*max_words+w]+ff_offsets[tile*groups+w/256];
    uint next=w+1;
    uint finish=next*4<raw_bytes ? next*4+ff_local[tile*max_words+next]+ff_offsets[tile*groups+next/256] : body_bytes;
    if((!w && start) || body_bytes>params.y || start>=finish || finish>body_bytes) {
        atomic_fetch_or_explicit(errors,1u,memory_order_relaxed);return;
    }
    uint cursor=start,value=0,n=min(4u,raw_bytes-w*4);
    encoded+=tile*params.y;
    for(uint b=0;b<n;b++) {
        if(cursor>=finish) {atomic_fetch_or_explicit(errors,2u,memory_order_relaxed);return;}
        uint byte=encoded[cursor++];value|=byte<<(24-b*8);
        if(byte==255) {
            if(cursor>=finish || encoded[cursor++]!=0) {atomic_fetch_or_explicit(errors,2u,memory_order_relaxed);return;}
        }
    }
    if(cursor!=finish) atomic_fetch_or_explicit(errors,4u,memory_order_relaxed);
    decoded_words[tile*max_words+w]=value;
}

inline uint cdng_check_read32(device const uint *words,uint bit,uint total_bits) {
    uint at=bit>>5,shift=bit&31;
    uint value=words[at]<<shift;
    if(shift && (at+1)*32<total_bits) value|=words[at+1]>>(32-shift);
    return value;
}

kernel void cdng_check_raw(
    device const ushort *original [[buffer(0)]],
    device const uint *words [[buffer(1)]],
    device const uint *counts [[buffer(2)]],
    device const uint *offsets [[buffer(3)]],
    device const uint *totals [[buffer(4)]],
    device const uint *lookup [[buffer(5)]],
    device const uint *canonical [[buffer(6)]],
    device const uint *predictors [[buffer(7)]],
    device atomic_uint *errors [[buffer(8)]],
    constant uint4 &params [[buffer(9)]],
    device const uint *suboff [[buffer(10)]],
    device const uint *source_indices [[buffer(11)]],
    uint2 gid [[thread_position_in_grid]],
    uint2 lid2 [[thread_position_in_threadgroup]],
    uint2 group2 [[threads_per_threadgroup]]) {
    uint lid=lid2.x,group_size=group2.x; // threadgroups are256x1
    uint count=params.x,stride=params.y,bits=params.z,max_words=params.w;
    // One thread per16-pixel segment. With256 threads per group, table-load
    // workgroup count stays unchanged while four times more threads share it.
    uint blocks=(count+255)/256,tile=gid.y,block=gid.x/16,sub=gid.x%16;
    // A threadgroup checks blocks of one tile: its decode tables are read once into
    // threadgroup memory instead of from device memory for every pixel.
    threadgroup uint table[1024];
    threadgroup uint canon[34];
    for(uint k=lid;k<1024;k+=group_size) table[k]=lookup[tile*1024+k];
    for(uint k=lid;k<34;k+=group_size) canon[k]=canonical[tile*34+k];
    threadgroup_barrier(mem_flags::mem_threadgroup);
    if(block>=blocks) return;
    if(atomic_load_explicit(errors,memory_order_relaxed)) return;
    uint at=tile*blocks+block,start=offsets[at],length=counts[at],end=start+length,total=totals[tile];
    uint first=block*256,last=min(first+256,count);
    if(!sub && (total>max_words*32 || length<last-first || length>31*(last-first) || end<start || end>total
        || (!block && start) || (block+1<blocks ? offsets[at+1]!=end : end!=total) || suboff[at*16])) {
        atomic_fetch_or_explicit(errors,8u,memory_order_relaxed);return;
    }
    // Each segment must end exactly at the next one's start (the last at block
    // end), so the segments together consume the entire block contiguously.
    uint q_first=first+sub*16,q_last=min(q_first+16,last);
    uint q_start=start+suboff[at*16+sub],q_end=sub<15 ? start+suboff[at*16+sub+1] : end;
    if(q_start>q_end || q_end>end) {atomic_fetch_or_explicit(errors,8u,memory_order_relaxed);return;}
    if(q_first>=q_last) {
        if(q_start!=q_end) atomic_fetch_or_explicit(errors,128u,memory_order_relaxed);
        return;
    }
    words+=tile*max_words;original+=source_indices[tile]*count;
    uint cursor=q_start,p=predictors[tile];
    uint row=q_first/stride,col=q_first%stride;
    for(uint i=q_first;i<q_last;i++) {
        if(cursor>=q_end) {atomic_fetch_or_explicit(errors,16u,memory_order_relaxed);return;}
        uint value=cdng_check_read32(words,cursor,total);
        uint entry=table[(i&1)*512+(value>>23)],len=entry>>8,category=entry&255;
        if(!len) {
            for(uint c=0;c<17;c++) {
                uint code=canon[(i&1)*17+c],n=code>>16;
                if(n>9 && (value>>(32-n))==(code&65535)) {len=n;category=c;break;}
            }
        }
        uint symbol_bits=len+(category&15);
        if(!len || symbol_bits>32 || cursor+symbol_bits>q_end) {atomic_fetch_or_explicit(errors,32u,memory_order_relaxed);return;}
        int difference=0;
        if(category==16) difference=-32768;
        else if(category) {
            // A DC symbol has at most 16 Huffman bits plus 15 amplitude bits.
            // The complete symbol fits the window already fetched for lookup;
            // using it also for amplitude avoids another dependent word read.
            uint amplitude=(value>>(32-symbol_bits))&((1u<<category)-1);
            difference=int(amplitude);
            if(!(amplitude&(1u<<(category-1)))) difference-=int((1u<<category)-1);
        }
        cursor+=symbol_bits;
        int prediction;
        // Original neighbors are valid predictor checkpoints: every decoded
        // difference is checked, so equality of the serial reconstruction
        // follows by induction from the initial midpoint prediction.
        if(!row && col<2) prediction=1<<(bits-1);
        else if(!row) prediction=original[i-2];
        else if(col<2) prediction=original[i-stride];
        else {
            int a=original[i-2],b=original[i-stride],c=original[i-stride-2];
            switch(p) {
                case 1:prediction=a;break;case 2:prediction=b;break;
                case 3:prediction=c;break;case 4:prediction=a+b-c;break;
                case 5:prediction=a+((b-c)>>1);break;
                case 6:prediction=b+((a-c)>>1);break;
                default:prediction=(a+b)>>1;break;
            }
        }
        if(ushort(prediction+difference)!=original[i]) atomic_fetch_or_explicit(errors,64u,memory_order_relaxed);
        if(++col==stride) {col=0;row++;}
    }
    if(cursor!=q_end) atomic_fetch_or_explicit(errors,128u,memory_order_relaxed);
}

// Used only by the Rust corruption regression; normal calls pass mode zero.
kernel void cdng_check_damage(device uchar *encoded [[buffer(0)]],
    device uint *offsets [[buffer(1)]],constant uint &mode [[buffer(2)]],device uint *suboff [[buffer(3)]],
    uint gid [[thread_position_in_grid]]) {
    if(gid) return;
    if(mode==1) encoded[0]^=128;
    else if(mode==2) offsets[1]^=1;
    else if(mode==3) suboff[1]^=1; // start of the second16-pixel segment
}
