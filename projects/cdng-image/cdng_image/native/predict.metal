#include <metal_stdlib>
using namespace metal;

// Two components retain raster sample order. row_stride may combine two
// sensor rows, making the preceding JPEG row a same-color CFA neighbor.
kernel void cdng_histogram(
    device const ushort *pixels [[buffer(0)]],
    device atomic_uint *hist [[buffer(1)]],
    constant uint4 &params [[buffer(2)]],
    uint group_id [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]],
    uint group_size [[threads_per_threadgroup]]) {
    threadgroup atomic_uint local_hist[238]; // 7 predictors x 2 components x 17 categories
    for (uint i=lid;i<238;i+=group_size)
        atomic_store_explicit(&local_hist[i],0,memory_order_relaxed);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    const uint count=params.x,stride=params.y,bits=params.z,mask=params.w;
    const uint groups_per_tile=(count+group_size-1)/group_size;
    const uint tile=group_id/groups_per_tile;
    const uint gid=(group_id%groups_per_tile)*group_size+lid;
    pixels+=tile*count;
    hist+=tile*238;
    if(gid<count) {
        const uint col=gid%stride, row=gid/stride, component=gid%2;
        const int sample=pixels[gid];
        int a=col>=2 ? pixels[gid-2] : 0;
        int b=row ? pixels[gid-stride] : 0;
        int c=(row && col>=2) ? pixels[gid-stride-2] : 0;
        for(uint p=1;p<=7;p++) {
            if(!(mask & (1u<<(p-1)))) continue;
            int prediction;
            if(!row && col<2) prediction=1<<(bits-1);
            else if(!row) prediction=a;
            else if(col<2) prediction=b;
            else switch(p) {
                case 1:prediction=a;break;
                case 2:prediction=b;break;
                case 3:prediction=c;break;
                case 4:prediction=a+b-c;break;
                case 5:prediction=a+((b-c)>>1);break;
                case 6:prediction=b+((a-c)>>1);break;
                default:prediction=(a+b)>>1;break;
            }
            // Lossless JPEG uses signed 16-bit modular differences.
            int diff=int(short(sample-prediction));
            uint magnitude=uint(abs(diff));
            uint category=magnitude ? 32u-clz(magnitude) : 0;
            atomic_fetch_add_explicit(&local_hist[((p-1)*2+component)*17+category],1,memory_order_relaxed);
        }
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for(uint i=lid;i<238;i+=group_size) {
        uint n=atomic_load_explicit(&local_hist[i],memory_order_relaxed);
        if(n) atomic_fetch_add_explicit(&hist[i],n,memory_order_relaxed);
    }
}
