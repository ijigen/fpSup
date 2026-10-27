#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <dispatch/dispatch.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <mach/mach.h>
#include <unistd.h>

static id<MTLDevice> device;
static id<MTLCommandQueue> queue;
static id<MTLComputePipelineState> pipeline;
static id<MTLLibrary> library;
static id<MTLComputePipelineState> entropy[7];
static dispatch_once_t entropy_once;
static NSString *entropy_error;
static NSString *initial_error;
static dispatch_once_t once;
// A host callback may execute ordinary Rust work while its histogram command
// runs, but it must not reuse this thread's histogram buffers recursively.
static thread_local bool histogram_work_active=false;

// Per-thread buffers reused across frames. Allocating ~100 MB of shared buffers per
// frame made the kernel zero and fault in fresh pages every time. No kernel reads a
// location it has not written in the same command buffer (the error flags and the
// histogram are cleared explicitly), so stale contents are harmless.
enum { HIST_INPUT, HIST_OUTPUT, HIST_MACROBLOCKS, ENTROPY_FIRST, POOL_SLOTS = ENTROPY_FIRST + 32 };
struct BufferPool {
    id<MTLBuffer> buffer[POOL_SLOTS];
    size_t capacity[POOL_SLOTS];
};
static id<MTLBuffer> pooled(int slot, size_t bytes) {
    static thread_local BufferPool pool;
    if (!pool.buffer[slot] || pool.capacity[slot] < bytes) {
        size_t grow = bytes + bytes / 8; // room for slightly larger frames
        pool.buffer[slot] = [device newBufferWithLength:grow options:MTLResourceStorageModeShared];
        pool.capacity[slot] = pool.buffer[slot] ? grow : 0;
    }
    return pool.buffer[slot];
}

extern "C" uint64_t cdng_ram_budget() {
    uint64_t budget=NSProcessInfo.processInfo.physicalMemory/8;
    vm_statistics64_data_t stats={};mach_msg_type_number_t count=HOST_VM_INFO64_COUNT;vm_size_t page=0;
    mach_port_t host=mach_host_self();
    if(host_page_size(host,&page)==KERN_SUCCESS && host_statistics64(host,HOST_VM_INFO64,(host_info64_t)&stats,&count)==KERN_SUCCESS) {
        uint64_t reclaimable=(uint64_t(stats.free_count)+stats.inactive_count+stats.speculative_count)*page;
        if(reclaimable/4<budget) budget=reclaimable/4;
    }
    mach_port_deallocate(mach_task_self(),host);
    return budget;
}

extern "C" int cdng_gpu_hist(const uint16_t *pixels, uint32_t count,
    uint32_t tiles, uint32_t stride, uint32_t bits, uint32_t mask, uint32_t *hist,
    const char *kernel_path, char *error, uint32_t error_size) {
    @autoreleasepool {
        if(histogram_work_active) {snprintf(error,error_size,"Metal histogram work cannot reenter histogram search");return 5;}
        dispatch_once(&once, ^{
            device=MTLCreateSystemDefaultDevice();
            if(!device) { initial_error=@"No Metal device"; return; }
            NSError *err=nil;
            NSString *source = strncmp(kernel_path,"source:",7)==0
                ? [NSString stringWithUTF8String:kernel_path+7]
                : [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:kernel_path]
                    encoding:NSUTF8StringEncoding error:&err];
            if(!source) { initial_error=[err localizedDescription];return; }
            library=[device newLibraryWithSource:source options:nil error:&err];
            if(!library) { initial_error=[err localizedDescription];return; }
            pipeline=[device newComputePipelineStateWithFunction:[library newFunctionWithName:@"cdng_histogram"] error:&err];
            if(!pipeline) { initial_error=[err localizedDescription];return; }
            queue=[device newCommandQueue];
        });
        if(!pipeline || !queue) {
            snprintf(error,error_size,"%s",[initial_error ?: @"Metal initialization failed" UTF8String]);return 1;
        }
        if(!count || !tiles || uint64_t(count)*tiles>UINT32_MAX || stride<2 || stride%2 || count%stride || bits<8 || bits>16 || !mask || (mask&~127u)) {
            snprintf(error,error_size,"Invalid GPU histogram dimensions");return 2;
        }
        id<MTLBuffer> input=pooled(HIST_INPUT,size_t(count)*tiles*2);
        id<MTLBuffer> output=pooled(HIST_OUTPUT,size_t(tiles)*238*4);
        if(!input || !output) {snprintf(error,error_size,"Metal buffer allocation failed");return 3;}
        memcpy([input contents],pixels,size_t(count)*tiles*2);
        memset([output contents],0,size_t(tiles)*238*4);
        uint32_t params[4]={count,stride,bits,mask};
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        [encoder setComputePipelineState:pipeline];
        [encoder setBuffer:input offset:0 atIndex:0];
        [encoder setBuffer:output offset:0 atIndex:1];
        [encoder setBytes:params length:sizeof(params) atIndex:2];
        NSUInteger group=MIN(256,[pipeline maxTotalThreadsPerThreadgroup]);
        [encoder dispatchThreadgroups:MTLSizeMake(size_t(tiles)*((count+group-1)/group),1,1) threadsPerThreadgroup:MTLSizeMake(group,1,1)];
        [encoder endEncoding];[command commit];[command waitUntilCompleted];
        if(getenv("CDNG_PROFILE_STAGES")) fprintf(stderr,"CDNG_HIST gpu_ms=%.3f\n",(command.GPUEndTime-command.GPUStartTime)*1000.);
        if(command.status==MTLCommandBufferStatusError) {
            snprintf(error,error_size,"%s",[[command.error localizedDescription] UTF8String]);return 4;
        }
        memcpy(hist,[output contents],size_t(tiles)*238*4);return 0;
    }
}

struct HistogramAxis {
    uint64_t full_sum=0,edge_sum=0;
    uint32_t phases=0;
    uint32_t full[32]={},edge[32]={};
};
static HistogramAxis histogram_axis(uint32_t step,uint32_t count) {
    HistogramAxis axis;
    uint32_t divisor=64;
    while(step%divisor) divisor/=2;
    const uint32_t period=64/divisor; // even dimensions give at most 32 phases
    axis.phases=count<period ? count : period;
    for(uint32_t i=0;i<axis.phases;i++) {
        const uint32_t phase=(i*step)%64,leading=(64-phase)%64;
        const uint32_t full=step>leading ? ((step-leading)/64)*64 : 0;
        const uint32_t edge=full && !phase ? 2 : 0;
        const uint64_t occurrences=count/period+(i<count%period ? 1 : 0);
        axis.full[i]=full;axis.edge[i]=edge;
        axis.full_sum+=occurrences*full;axis.edge_sum+=occurrences*edge;
    }
    return axis;
}

// Search multiple tile geometries from one source upload and one command. The
// output for each geometry is exactly the existing tiled histogram layout.
// Gpu::new has already initialized the shared Metal device and queue.
extern "C" int cdng_metal_hist_geometries(const uint16_t *pixels,
    uint32_t width, uint32_t height, uint32_t bits, uint32_t mask,
    const uint32_t *geometries, uint32_t geometry_count,
    uint32_t *hist, uint32_t hist_count, const char *kernel_source,
    void (*host_work)(void *), void *host_context,
    char *error, uint32_t error_size) {
    @autoreleasepool {
        if(histogram_work_active) {snprintf(error,error_size,"Metal histogram work cannot reenter histogram search");return 5;}
        static id<MTLComputePipelineState> batch_pipeline;
        static id<MTLLibrary> batch_library;
        static id<MTLComputePipelineState> shared_histogram[3];
        static NSString *batch_error;
        static dispatch_once_t batch_once;
        static dispatch_once_t shared_once;
        dispatch_once(&batch_once, ^{
            if(!device || !queue) {batch_error=@"Metal device not initialized";return;}
            NSError *err=nil;
            NSString *source=[NSString stringWithUTF8String:kernel_source];
            batch_library=[device newLibraryWithSource:source options:nil error:&err];
            if(!batch_library) {batch_error=[err localizedDescription];return;}
            batch_pipeline=[device newComputePipelineStateWithFunction:[batch_library newFunctionWithName:@"cdng_histogram_geometry"] error:&err];
            if(!batch_pipeline) batch_error=[err localizedDescription];
        });
        if(!batch_pipeline || !queue) {
            snprintf(error,error_size,"%s",[batch_error ?: @"Metal batch initialization failed" UTF8String]);return 1;
        }
        if(width<2 || height<2 || (width|height)&1u || uint64_t(width)*height>UINT32_MAX
            || bits<8 || bits>16 || !mask || (mask&~127u) || !geometry_count || geometry_count>16) {
            snprintf(error,error_size,"Invalid Metal geometry batch dimensions");return 2;
        }
        uint64_t total_hist=0,old_work=0,padded_width=0,padded_height=0;
        uint32_t tiles_x[16],tiles_y[16],patch_groups[16]={};
        for(uint32_t i=0;i<geometry_count;i++) {
            uint32_t tw=geometries[i*2],th=geometries[i*2+1];
            if(!tw || !th || (tw|th)&1u || tw>65520 || th>65520 || uint64_t(tw)*th>UINT32_MAX) {
                snprintf(error,error_size,"Invalid Metal tile geometry");return 2;
            }
            const uint64_t nx=(uint64_t(width)+tw-1)/tw,ny=(uint64_t(height)+th-1)/th;
            tiles_x[i]=uint32_t(nx);tiles_y[i]=uint32_t(ny);
            total_hist+=nx*ny*238;
            old_work+=nx*ny*tw*th;
            if(nx*tw>padded_width) padded_width=nx*tw;
            if(ny*th>padded_height) padded_height=ny*th;
        }
        if(total_hist!=hist_count || total_hist>UINT32_MAX) {
            snprintf(error,error_size,"Metal geometry histogram length mismatch");return 2;
        }
        const uint64_t base_width=(padded_width+63)/64*64,base_height=(padded_height+63)/64*64;
        const uint64_t base_pixels=base_width*base_height;
        const uint64_t base_bytes=base_pixels/4096*238*4;
        uint64_t shared_work=0;
        const char *shared_setting=getenv("CDNG_METAL_SHARED_HISTOGRAM");
        bool use_shared=!(shared_setting && strcmp(shared_setting,"0")==0);
        const char *shared_reason=use_shared ? "shared" : "disabled";
        if(use_shared && geometry_count<2) {use_shared=false;shared_reason="single_geometry";}
        // The optional accelerator must never turn a supported small input with
        // extreme candidate aspect ratios into an enormous shared allocation.
        // Include the pool's growth allowance in the 64 MiB per-worker limit.
        if(use_shared && (base_width>UINT32_MAX || base_height>UINT32_MAX || base_pixels>UINT32_MAX
            || base_bytes+base_bytes/8>64ull*1024*1024
            || base_bytes+base_bytes/8>device.maxBufferLength)) {
            use_shared=false;shared_reason="padded_domain_limit";
        }
        if(use_shared) {
            shared_work=base_pixels;
            for(uint32_t i=0;i<geometry_count;i++) {
                const uint32_t tw=geometries[i*2],th=geometries[i*2+1];
                const HistogramAxis x=histogram_axis(tw,tiles_x[i]),y=histogram_axis(th,tiles_y[i]);
                const uint64_t full=x.full_sum*y.full_sum;
                const uint64_t corrections=x.edge_sum*y.full_sum+x.full_sum*y.edge_sum-x.edge_sum*y.edge_sum;
                shared_work+=uint64_t(tiles_x[i])*tiles_y[i]*tw*th-full+2*corrections;
                uint64_t max_patch=0;
                for(uint32_t px=0;px<x.phases;px++) for(uint32_t py=0;py<y.phases;py++) {
                    const uint64_t fw=x.full[px],fh=y.full[py],ex=x.edge[px],ey=y.edge[py];
                    const uint64_t patch=uint64_t(tw)*th-fw*fh+ex*fh+fw*ey-ex*ey;
                    if(patch>max_patch) max_patch=patch;
                }
                patch_groups[i]=uint32_t((max_patch+4095)/4096);
            }
            // Keep the legacy path when reuse cannot save at least a quarter of
            // predictor/category work; this changes scheduling, never search.
            if(shared_work>old_work-old_work/4) {use_shared=false;shared_reason="insufficient_reuse";}
        }
        if(use_shared) {
            dispatch_once(&shared_once, ^{
                const char *names[]={"cdng_histogram_macroblocks","cdng_histogram_aggregate","cdng_histogram_patch"};
                for(uint32_t i=0;i<3;i++) {
                    NSError *err=nil;
                    id<MTLFunction> function=[batch_library newFunctionWithName:[NSString stringWithUTF8String:names[i]]];
                    if(!function) return;
                    shared_histogram[i]=[device newComputePipelineStateWithFunction:function error:&err];
                    if(!shared_histogram[i] || shared_histogram[i].maxTotalThreadsPerThreadgroup<256) return;
                }
            });
            for(uint32_t i=0;i<3;i++) if(!shared_histogram[i] || shared_histogram[i].maxTotalThreadsPerThreadgroup<256) {
                use_shared=false;shared_reason="pipeline_unavailable";
            }
        }
        id<MTLBuffer> base_hist=nil;
        if(use_shared) {
            base_hist=pooled(HIST_MACROBLOCKS,size_t(base_bytes));
            if(!base_hist) {use_shared=false;shared_reason="optional_allocation_failed";}
        }
        if(getenv("CDNG_PROFILE_SHARED_HISTOGRAM") || getenv("CDNG_PROFILE_STAGES"))
            fprintf(stderr,"CDNG_SHARED_HISTOGRAM path=%s reason=%s geometries=%u base_width=%llu base_height=%llu base_bytes=%llu old_work=%llu shared_work=%llu\n",
                use_shared ? "shared" : "legacy",shared_reason,geometry_count,
                (unsigned long long)base_width,(unsigned long long)base_height,
                (unsigned long long)base_bytes,(unsigned long long)old_work,(unsigned long long)shared_work);
        const size_t input_bytes=size_t(width)*height*2,output_bytes=size_t(hist_count)*4;
        id<MTLBuffer> input=pooled(HIST_INPUT,input_bytes);
        id<MTLBuffer> output=pooled(HIST_OUTPUT,output_bytes);
        if(!input || !output) {snprintf(error,error_size,"Metal batch buffer allocation failed");return 3;}
        memcpy(input.contents,pixels,input_bytes);
        if(!use_shared) memset(output.contents,0,output_bytes);
        id<MTLCommandBuffer> command=[queue commandBuffer];
        const uint32_t image[4]={width,height,bits,mask};
        uint32_t offset=0;
        const NSUInteger group=MIN(256,batch_pipeline.maxTotalThreadsPerThreadgroup);
        // Match histogram_batch.metal: amortize counter initialization and
        // global reduction across 16 pixels per lane while keeping 256 lanes.
        constexpr uint32_t histogram_pixels_per_group=4096;
        if(use_shared) {
            const uint32_t base[2]={uint32_t(base_width),uint32_t(base_height)};
            id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
            [encoder setComputePipelineState:shared_histogram[0]];
            [encoder setBuffer:input offset:0 atIndex:0];[encoder setBuffer:base_hist offset:0 atIndex:1];
            [encoder setBytes:image length:sizeof(image) atIndex:2];[encoder setBytes:base length:sizeof(base) atIndex:3];
            [encoder dispatchThreadgroups:MTLSizeMake(size_t(base_pixels/4096),1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];
            [encoder endEncoding];
            // Separate encoders establish base -> aggregate -> patch visibility.
            // Geometry outputs within either latter stage occupy disjoint ranges.
            encoder=[command computeCommandEncoder];
            [encoder setComputePipelineState:shared_histogram[1]];
            [encoder setBuffer:base_hist offset:0 atIndex:0];[encoder setBuffer:output offset:0 atIndex:1];
            [encoder setBytes:base length:sizeof(base) atIndex:3];
            for(uint32_t i=0;i<geometry_count;i++) {
                const uint32_t geometry[4]={geometries[i*2],geometries[i*2+1],tiles_x[i],offset};
                [encoder setBytes:geometry length:sizeof(geometry) atIndex:2];
                [encoder dispatchThreadgroups:MTLSizeMake(size_t(tiles_x[i])*tiles_y[i],1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];
                offset+=tiles_x[i]*tiles_y[i]*238;
            }
            [encoder endEncoding];
            offset=0;
            encoder=[command computeCommandEncoder];
            [encoder setComputePipelineState:shared_histogram[2]];
            [encoder setBuffer:input offset:0 atIndex:0];[encoder setBuffer:output offset:0 atIndex:1];
            [encoder setBytes:image length:sizeof(image) atIndex:2];
            for(uint32_t i=0;i<geometry_count;i++) {
                const uint32_t geometry[4]={geometries[i*2],geometries[i*2+1],tiles_x[i],offset};
                const uint32_t patch[2]={uint32_t(base_width),patch_groups[i]};
                [encoder setBytes:geometry length:sizeof(geometry) atIndex:3];[encoder setBytes:patch length:sizeof(patch) atIndex:4];
                [encoder dispatchThreadgroups:MTLSizeMake(size_t(tiles_x[i])*tiles_y[i]*patch_groups[i],1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];
                offset+=tiles_x[i]*tiles_y[i]*238;
            }
            [encoder endEncoding];
        } else for(uint32_t i=0;i<geometry_count;i++) {
            const uint32_t tw=geometries[i*2],th=geometries[i*2+1];
            const uint32_t nx=tiles_x[i],ny=tiles_y[i];
            const uint32_t geometry[4]={tw,th,nx,offset};
            id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
            [encoder setComputePipelineState:batch_pipeline];
            [encoder setBuffer:input offset:0 atIndex:0];[encoder setBuffer:output offset:0 atIndex:1];
            [encoder setBytes:image length:sizeof(image) atIndex:2];
            [encoder setBytes:geometry length:sizeof(geometry) atIndex:3];
            [encoder dispatchThreadgroups:MTLSizeMake(size_t(nx)*ny*((size_t(tw)*th+histogram_pixels_per_group-1)/histogram_pixels_per_group),1,1)
                threadsPerThreadgroup:MTLSizeMake(group,1,1)];
            [encoder endEncoding];
            offset+=nx*ny*238;
        }
        [command commit];
        // Rust catches any host panic inside the callback. Always complete the
        // command before returning, even when host work reports an error.
        histogram_work_active=true;
        if(host_work) host_work(host_context);
        [command waitUntilCompleted];
        histogram_work_active=false;
        if(getenv("CDNG_PROFILE_STAGES")) fprintf(stderr,"CDNG_HIST_BATCH gpu_ms=%.3f\n",(command.GPUEndTime-command.GPUStartTime)*1000.);
        if(command.status==MTLCommandBufferStatusError) {
            snprintf(error,error_size,"%s",[[command.error localizedDescription] UTF8String]);return 4;
        }
        memcpy(hist,output.contents,output_bytes);return 0;
    }
}

// Called after histogram initialization. All per-pixel prediction, Huffman
// writes, bit alignment and JPEG byte stuffing execute on Metal.
// Return a view of the thread-local shared output buffer, valid until the next
// entropy call on this thread. The synchronous Rust caller copies each finished
// tile directly into its JPEG allocation before making another native call.
extern "C" int cdng_metal_entropy_view(const uint16_t *pixels, size_t input_capacity_bytes, uint32_t count,
    uint32_t source_tiles, uint32_t tiles, const uint32_t *source_indices, uint32_t stride, uint32_t bits, const uint32_t *codes,
    const uint32_t *predictors, const uint32_t *decode_lookup, const uint32_t *decode_codes,
    uint32_t damage_for_test, uint32_t max_words, uint32_t body_stride,
    const uint8_t **output, uint32_t *lengths, char *error, uint32_t error_size) {
    @autoreleasepool {
        *output=nullptr;
        CFAbsoluteTime started=CFAbsoluteTimeGetCurrent();
        dispatch_once(&entropy_once, ^{
            const char *names[]={"cdng_entropy_blocks","cdng_entropy_prefix","cdng_entropy_join","cdng_entropy_stuff","cdng_check_unstuff","cdng_check_raw","cdng_check_damage"};
            for(int i=0;i<7;i++) {
                NSError *err=nil;
                id<MTLFunction> fn=[library newFunctionWithName:[NSString stringWithUTF8String:names[i]]];
                if(!fn) {entropy_error=@"Metal entropy function missing";return;}
                entropy[i]=[device newComputePipelineStateWithFunction:fn error:&err];
                if(!entropy[i]) {entropy_error=[err localizedDescription];return;}
                if(entropy[i].threadExecutionWidth!=32 || entropy[i].maxTotalThreadsPerThreadgroup<256) {
                    entropy_error=@"Metal entropy requires 32-lane SIMD and 256-thread groups";return;
                }
            }
        });
        if(entropy_error || !entropy[6] || !queue) {
            snprintf(error,error_size,"%s",[entropy_error ?: @"Metal entropy initialization failed" UTF8String]);return 1;
        }
        if(!count || !source_tiles || !tiles || !source_indices || uint64_t(count)*source_tiles>UINT32_MAX
            || uint64_t(count)*tiles>UINT32_MAX || stride<2 || stride%2 || count%stride || bits<8 || bits>16
            || !max_words || max_words>count || uint64_t(body_stride)<uint64_t(max_words)*8) {
            snprintf(error,error_size,"Invalid Metal entropy dimensions");return 2;
        }
        for(uint32_t t=0;t<tiles;t++) {
            if(source_indices[t]>=source_tiles) {
                snprintf(error,error_size,"Invalid Metal source tile index");return 2;
            }
        }
        const uint32_t blocks=(count+255)/256, word_groups=(max_words+255)/256;
        auto make_buffer = [&](int i, size_t bytes) {return pooled(ENTROPY_FIRST+i,bytes);};
        enum {INPUT,CODES,PRED,PARTS,COUNTS,OFFSETS,TOTALS,WORDS,LOCAL_FF,FF_COUNTS,FF_OFFSETS,FF_TOTALS,OUTPUT,
            DECODE_LOOKUP,DECODE_CODES,RECOVERED_WORDS,ERRORS,SUBOFF,SOURCE_INDEX,BUFFER_COUNT};
        id<MTLBuffer> buffers[BUFFER_COUNT];
        size_t sizes[]={size_t(count)*source_tiles*2,size_t(tiles)*34*4,size_t(tiles)*4,
            size_t(blocks)*tiles*256*4,size_t(blocks)*tiles*4,size_t(blocks)*tiles*4,size_t(tiles)*4,
            size_t(max_words)*tiles*4,size_t(max_words)*tiles*4,size_t(word_groups)*tiles*4,
            size_t(word_groups)*tiles*4,size_t(tiles)*4,size_t(body_stride)*tiles,
            size_t(tiles)*1024*4,size_t(tiles)*34*4,size_t(max_words)*tiles*4,4,size_t(blocks)*tiles*16*4,size_t(tiles)*4};
        const size_t page_size=size_t(getpagesize());
        if(input_capacity_bytes && (input_capacity_bytes<sizes[INPUT] || input_capacity_bytes%page_size
            || uintptr_t(pixels)%page_size)) {
            snprintf(error,error_size,"Invalid shared tile allocation");return 2;
        }
        for(int i=0;i<BUFFER_COUNT;i++) {
            buffers[i]=(i==INPUT && input_capacity_bytes)
                ? [device newBufferWithBytesNoCopy:const_cast<uint16_t *>(pixels) length:input_capacity_bytes
                    options:MTLResourceStorageModeShared deallocator:nil]
                : make_buffer(i,sizes[i]);
            if(!buffers[i]) {snprintf(error,error_size,"Metal entropy buffer allocation failed");return 3;}
        }
        if(!input_capacity_bytes) memcpy(buffers[INPUT].contents,pixels,sizes[INPUT]);
        memcpy(buffers[CODES].contents,codes,sizes[CODES]);
        memcpy(buffers[PRED].contents,predictors,sizes[PRED]);
        memcpy(buffers[DECODE_LOOKUP].contents,decode_lookup,sizes[DECODE_LOOKUP]);
        memcpy(buffers[DECODE_CODES].contents,decode_codes,sizes[DECODE_CODES]);
        memcpy(buffers[SOURCE_INDEX].contents,source_indices,sizes[SOURCE_INDEX]);
        memset(buffers[ERRORS].contents,0,4);
        id<MTLCommandBuffer> command=[queue commandBuffer];
        auto begin = [&](int p) {id<MTLComputeCommandEncoder> e=[command computeCommandEncoder];[e setComputePipelineState:entropy[p]];return e;};
        auto prefix = [&](int counts,int offsets,int totals,uint32_t n) {
            id<MTLComputeCommandEncoder> e=begin(1);
            [e setBuffer:buffers[counts] offset:0 atIndex:0];[e setBuffer:buffers[offsets] offset:0 atIndex:1];
            [e setBuffer:buffers[totals] offset:0 atIndex:2];uint32_t params[2]={n,tiles};
            [e setBytes:params length:sizeof(params) atIndex:3];
            [e dispatchThreadgroups:MTLSizeMake((tiles+63)/64,1,1) threadsPerThreadgroup:MTLSizeMake(64,1,1)];[e endEncoding];
        };
        id<MTLComputeCommandEncoder> e=begin(0);
        int first[]={INPUT,CODES,PRED,PARTS,COUNTS};
        for(int i=0;i<5;i++) [e setBuffer:buffers[first[i]] offset:0 atIndex:i];
        uint32_t params[4]={count,stride,bits,max_words};[e setBytes:params length:sizeof(params) atIndex:5];
        [e setBuffer:buffers[SUBOFF] offset:0 atIndex:6];
        [e setBuffer:buffers[SOURCE_INDEX] offset:0 atIndex:7];
        [e dispatchThreadgroups:MTLSizeMake(blocks,tiles,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];[e endEncoding];
        prefix(COUNTS,OFFSETS,TOTALS,blocks);
        e=begin(2);int join[]={PARTS,COUNTS,OFFSETS,TOTALS,WORDS,LOCAL_FF,FF_COUNTS};
        for(int i=0;i<7;i++) [e setBuffer:buffers[join[i]] offset:0 atIndex:i];
        uint32_t join_params[2]={count,max_words};[e setBytes:join_params length:sizeof(join_params) atIndex:7];
        [e dispatchThreadgroups:MTLSizeMake(word_groups,tiles,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];[e endEncoding];
        prefix(FF_COUNTS,FF_OFFSETS,FF_TOTALS,word_groups);
        e=begin(3);int stuff[]={WORDS,LOCAL_FF,FF_OFFSETS,TOTALS,OUTPUT};
        for(int i=0;i<5;i++) [e setBuffer:buffers[stuff[i]] offset:0 atIndex:i];
        uint32_t stuff_params[2]={max_words,body_stride};[e setBytes:stuff_params length:sizeof(stuff_params) atIndex:5];
        [e dispatchThreadgroups:MTLSizeMake(word_groups,tiles,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];[e endEncoding];
        if(damage_for_test) {
            if(damage_for_test>3 || (damage_for_test==2 && blocks<2)) {snprintf(error,error_size,"Invalid test damage mode");return 7;}
            e=begin(6);[e setBuffer:buffers[OUTPUT] offset:0 atIndex:0];[e setBuffer:buffers[OFFSETS] offset:0 atIndex:1];
            [e setBuffer:buffers[SUBOFF] offset:0 atIndex:3];
            [e setBytes:&damage_for_test length:4 atIndex:2];
            [e dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];[e endEncoding];
        }
        static const bool skip_verify_timing=getenv("CDNG_TIMING_SKIP_GPU_VERIFY")!=nullptr; // timing experiments only
        if(!skip_verify_timing) {
        e=begin(4);int unstuff[]={OUTPUT,LOCAL_FF,FF_OFFSETS,TOTALS,FF_TOTALS,RECOVERED_WORDS,ERRORS};
        for(int i=0;i<7;i++) [e setBuffer:buffers[unstuff[i]] offset:0 atIndex:i];
        [e setBytes:stuff_params length:sizeof(stuff_params) atIndex:7];
        [e dispatchThreadgroups:MTLSizeMake(word_groups,tiles,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];[e endEncoding];
        static const bool skip_raw_timing=getenv("CDNG_TIMING_SKIP_RAW_CHECK")!=nullptr; // timing experiments only
        if(!skip_raw_timing) {
        e=begin(5);int verify[]={INPUT,RECOVERED_WORDS,COUNTS,OFFSETS,TOTALS,DECODE_LOOKUP,DECODE_CODES,PRED,ERRORS};
        for(int i=0;i<9;i++) [e setBuffer:buffers[verify[i]] offset:0 atIndex:i];
        [e setBytes:params length:sizeof(params) atIndex:9];
        [e setBuffer:buffers[SUBOFF] offset:0 atIndex:10];
        [e setBuffer:buffers[SOURCE_INDEX] offset:0 atIndex:11];
        [e dispatchThreadgroups:MTLSizeMake((blocks*16+255)/256,tiles,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];[e endEncoding];
        }
        }
        [command commit];[command waitUntilCompleted];
        if(getenv("CDNG_PROFILE_STAGES")) fprintf(stderr,"CDNG_METAL gpu_ms=%.3f wall_ms=%.3f\n",(command.GPUEndTime-command.GPUStartTime)*1000.,(CFAbsoluteTimeGetCurrent()-started)*1000.);
        if(command.status==MTLCommandBufferStatusError) {
            snprintf(error,error_size,"%s",[[command.error localizedDescription] UTF8String]);return 4;
        }
        uint32_t check_errors=*(const uint32_t *)buffers[ERRORS].contents;
        if(check_errors) {snprintf(error,error_size,"Metal RAW verification failed (flags %u)",check_errors);return 6;}
        const uint32_t *totals=(const uint32_t *)buffers[TOTALS].contents;
        const uint32_t *ffs=(const uint32_t *)buffers[FF_TOTALS].contents;
        for(uint32_t t=0;t<tiles;t++) {
            uint64_t bytes=(uint64_t(totals[t])+7)/8+ffs[t];
            if(totals[t]>uint64_t(max_words)*32 || bytes>body_stride) {snprintf(error,error_size,"Metal entropy output overflow");return 5;}
            lengths[t]=(uint32_t)bytes;
        }
        *output=(const uint8_t *)buffers[OUTPUT].contents;
        return 0;
    }
}

extern "C" const char *cdng_gpu_name() {
    static char name[256];
    @autoreleasepool { snprintf(name,sizeof(name),"%s",[MTLCreateSystemDefaultDevice().name UTF8String] ?: "No Metal device"); }
    return name;
}
