#include <metal_stdlib>
using namespace metal;

// Match fill_tile's same-colour, two-sample edge extension without constructing
// a complete tiled image for every candidate geometry. Sensor dimensions and
// tile dimensions are even, so each padded coordinate selects the last sample
// of the same CFA phase.
static inline ushort cdng_source_xy(device const ushort *pixels,
    uint x, uint y, uint width, uint height) {
    if(x>=width) x=width-2+((x-width)&1u);
    if(y>=height) y=height-2+((y-height)&1u);
    return pixels[y*width+x];
}

kernel void cdng_histogram_geometry(
    device const ushort *pixels [[buffer(0)]],
    device atomic_uint *hist [[buffer(1)]],
    constant uint4 &image [[buffer(2)]],
    constant uint4 &geometry [[buffer(3)]],
    uint group_id [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]],
    uint group_size [[threads_per_threadgroup]]) {
    threadgroup atomic_uint local_hist[238];
    for(uint i=lid;i<238;i+=group_size)
        atomic_store_explicit(&local_hist[i],0,memory_order_relaxed);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    const uint width=image.x,height=image.y,bits=image.z,mask=image.w;
    const uint tw=geometry.x,th=geometry.y,nx=geometry.z;
    const uint count=tw*th,stride=tw*2;
    // Match the native dispatch. Reuse each initialized local histogram for
    // sixteen samples per lane, reducing global atomics without sampling less.
    constexpr uint pixels_per_group=4096;
    const uint groups_per_tile=(count+pixels_per_group-1)/pixels_per_group;
    const uint tile=group_id/groups_per_tile;
    const uint first=(group_id%groups_per_tile)*pixels_per_group;
    hist+=geometry.w+tile*238;
    const uint tx=(tile%nx)*tw,ty=(tile/nx)*th;
    uint sensor_x=(first+lid)%tw,sensor_y=(first+lid)/tw;
    const uint step_x=group_size%tw,step_y=group_size/tw;
    for(uint gid=first+lid;gid<min(first+pixels_per_group,count);gid+=group_size) {
        const uint col=(sensor_y&1u)*tw+sensor_x,row=sensor_y/2,component=gid%2;
        const uint x=tx+sensor_x,y=ty+sensor_y;
        // JPEG rows combine two sensor rows. At the second sensor row's
        // beginning, its left JPEG neighbour is at the first sensor row's end.
        const uint ax=tx+(sensor_x>=2 ? sensor_x-2 : tw-2+sensor_x);
        const uint ay=y-(sensor_x<2 ? 1u : 0u);
        const int sample=cdng_source_xy(pixels,x,y,width,height);
        const int a=col>=2 ? cdng_source_xy(pixels,ax,ay,width,height) : 0;
        const int b=row ? cdng_source_xy(pixels,x,y-2,width,height) : 0;
        const int c=(row && col>=2) ? cdng_source_xy(pixels,ax,ay-2,width,height) : 0;
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
            const int diff=int(short(sample-prediction));
            const uint magnitude=uint(abs(diff));
            const uint category=magnitude ? 32u-clz(magnitude) : 0;
            atomic_fetch_add_explicit(&local_hist[((p-1)*2+component)*17+category],1,memory_order_relaxed);
        }
        // Advancing by one lane stride needs at most one horizontal carry.
        // This preserves exact coordinates without repeating two divisions for
        // every sample in this lane's 16-sample chunk.
        sensor_x+=step_x;sensor_y+=step_y;
        if(sensor_x>=tw) {sensor_x-=tw;sensor_y++;}
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for(uint i=lid;i<238;i+=group_size) {
        const uint n=atomic_load_explicit(&local_hist[i],memory_order_relaxed);
        if(n) atomic_fetch_add_explicit(&hist[i],n,memory_order_relaxed);
    }
}

// Shared base histograms use one virtual JPEG raster over the full CFA-padded
// domain. Tile-local predictions differ only at their first two sensor rows or
// columns. In particular, an odd sensor row's first two samples wrap left to
// the previous sensor row's tile end, rather than to x-2.
static inline void cdng_histogram_delta(device const ushort *pixels,
    constant uint4 &image, uint2 origin, uint tile_width, uint x, uint y,
    threadgroup atomic_int *hist, int delta) {
    const uint sx=x-origin.x,sy=y-origin.y;
    const uint col=(sy&1u)*tile_width+sx,row=sy/2,component=sx&1u;
    const uint ax=origin.x+(sx>=2 ? sx-2 : tile_width-2+sx);
    const uint ay=y-(sx<2 ? 1u : 0u);
    const int sample=cdng_source_xy(pixels,x,y,image.x,image.y);
    const int a=col>=2 ? cdng_source_xy(pixels,ax,ay,image.x,image.y) : 0;
    const int b=row ? cdng_source_xy(pixels,x,y-2,image.x,image.y) : 0;
    const int c=(row && col>=2) ? cdng_source_xy(pixels,ax,ay-2,image.x,image.y) : 0;
    for(uint p=1;p<=7;p++) {
        if(!(image.w & (1u<<(p-1)))) continue;
        int prediction;
        if(!row && col<2) prediction=1<<(image.z-1);
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
        const int diff=int(short(sample-prediction));
        const uint magnitude=uint(abs(diff));
        const uint category=magnitude ? 32u-clz(magnitude) : 0;
        atomic_fetch_add_explicit(&hist[((p-1)*2+component)*17+category],delta,memory_order_relaxed);
    }
}

kernel void cdng_histogram_macroblocks(
    device const ushort *pixels [[buffer(0)]],
    device uint *base_hist [[buffer(1)]],
    constant uint4 &image [[buffer(2)]],
    constant uint2 &base [[buffer(3)]],
    uint cell [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]],
    uint group_size [[threads_per_threadgroup]]) {
    threadgroup atomic_int hist[238];
    for(uint i=lid;i<238;i+=group_size) atomic_store_explicit(&hist[i],0,memory_order_relaxed);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    const uint x0=(cell%(base.x/64))*64,y0=(cell/(base.x/64))*64;
    for(uint i=lid;i<4096;i+=group_size)
        cdng_histogram_delta(pixels,image,uint2(0),base.x,x0+(i&63u),y0+(i>>6),hist,1);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    // Own each output cell, including unused predictor bins from a sparse mask.
    for(uint i=lid;i<238;i+=group_size)
        base_hist[cell*238+i]=uint(atomic_load_explicit(&hist[i],memory_order_relaxed));
}

kernel void cdng_histogram_aggregate(
    device const uint *base_hist [[buffer(0)]],
    device uint *hist [[buffer(1)]],
    constant uint4 &geometry [[buffer(2)]],
    constant uint2 &base [[buffer(3)]],
    uint tile [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]],
    uint group_size [[threads_per_threadgroup]]) {
    const uint tx=(tile%geometry.z)*geometry.x,ty=(tile/geometry.z)*geometry.y;
    const uint x0=(tx+63u)&~63u,y0=(ty+63u)&~63u;
    const uint x1=(tx+geometry.x)&~63u,y1=(ty+geometry.y)&~63u;
    for(uint bin=lid;bin<238;bin+=group_size) {
        uint sum=0;
        if(x0<x1 && y0<y1) {
            for(uint y=y0;y<y1;y+=64) {
                for(uint x=x0;x<x1;x+=64)
                    sum+=base_hist[(y/64*(base.x/64)+x/64)*238+bin];
            }
        }
        // Complete overwrite avoids clearing the TLS buffer and stale bins.
        hist[geometry.w+tile*238+bin]=sum;
    }
}

kernel void cdng_histogram_patch(
    device const ushort *pixels [[buffer(0)]],
    device atomic_uint *hist [[buffer(1)]],
    constant uint4 &image [[buffer(2)]],
    constant uint4 &geometry [[buffer(3)]],
    constant uint2 &patch [[buffer(4)]],
    uint group_id [[threadgroup_position_in_grid]],
    uint lid [[thread_index_in_threadgroup]],
    uint group_size [[threads_per_threadgroup]]) {
    const uint tile=group_id/patch.y,first=(group_id%patch.y)*4096;
    const uint tw=geometry.x,th=geometry.y;
    const uint tx=(tile%geometry.z)*tw,ty=(tile/geometry.z)*th;
    const uint x0=(tx+63u)&~63u,y0=(ty+63u)&~63u;
    const uint x1=(tx+tw)&~63u,y1=(ty+th)&~63u;
    uint4 rectangles[6]; // x, y, width, height; first four are direct fringes.
    uint rectangles_count=1;
    rectangles[0]=uint4(tx,ty,tw,th);
    if(x0<x1 && y0<y1) {
        const uint top=min(y1,ty+2u)>y0 ? min(y1,ty+2u)-y0 : 0;
        const uint left=min(x1,tx+2u)>x0 ? min(x1,tx+2u)-x0 : 0;
        rectangles[0]=uint4(tx,ty,tw,y0-ty);
        rectangles[1]=uint4(tx,y1,tw,ty+th-y1);
        rectangles[2]=uint4(tx,y0,x0-tx,y1-y0);
        rectangles[3]=uint4(x1,y0,tx+tw-x1,y1-y0);
        rectangles[4]=uint4(x0,y0,x1-x0,top);
        rectangles[5]=uint4(x0,y0+top,left,y1-y0-top);
        rectangles_count=6;
    }
    uint work=0;
    for(uint r=0;r<rectangles_count;r++) work+=rectangles[r].z*rectangles[r].w;
    // Uniform early return: native bounds the maximum patch work by origin phase.
    if(first>=work) return;
    threadgroup atomic_int delta[238];
    for(uint i=lid;i<238;i+=group_size) atomic_store_explicit(&delta[i],0,memory_order_relaxed);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for(uint i=first+lid;i<min(first+4096u,work);i+=group_size) {
        uint at=i;
        for(uint r=0;r<rectangles_count;r++) {
            const uint4 rect=rectangles[r];
            const uint n=rect.z*rect.w;
            if(at>=n) {at-=n;continue;}
            const uint x=rect.x+at%rect.z,y=rect.y+at/rect.z;
            if(r>=4) cdng_histogram_delta(pixels,image,uint2(0),patch.x,x,y,delta,-1);
            cdng_histogram_delta(pixels,image,uint2(tx,ty),tw,x,y,delta,1);
            break;
        }
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for(uint i=lid;i<238;i+=group_size) {
        const int n=atomic_load_explicit(&delta[i],memory_order_relaxed);
        // Each correction removes a sample actually included in the base sum.
        // Unsigned modular addition is defined, even if concurrent corrections
        // temporarily wrap; only the completed nonnegative histogram is read.
        if(n) atomic_fetch_add_explicit(&hist[geometry.w+tile*238+i],uint(n),memory_order_relaxed);
    }
}
