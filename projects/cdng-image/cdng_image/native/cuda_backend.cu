#include <cuda_runtime.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#define EXPORT extern "C" __declspec(dllexport)
#else
#define EXPORT extern "C" __attribute__((visibility("default")))
#endif

__global__ void cdng_histogram(const uint16_t *pixels,uint32_t count,
    uint32_t stride,uint32_t bits,uint32_t mask,uint32_t *hist) {
    __shared__ uint32_t local_hist[238];
    uint32_t lid=threadIdx.x,groups_per_tile=(count+blockDim.x-1)/blockDim.x;
    uint32_t tile=blockIdx.x/groups_per_tile;
    uint32_t gid=(blockIdx.x%groups_per_tile)*blockDim.x+lid;
    pixels+=size_t(tile)*count;
    hist+=size_t(tile)*238;
    for(uint32_t i=lid;i<238;i+=blockDim.x)local_hist[i]=0;
    __syncthreads();
    if(gid<count) {
        uint32_t col=gid%stride,row=gid/stride,component=gid%2;
        int sample=pixels[gid];
        int a=col>=2 ? pixels[gid-2] : 0;
        int b=row ? pixels[gid-stride] : 0;
        int c=(row && col>=2) ? pixels[gid-stride-2] : 0;
        for(uint32_t p=1;p<=7;p++) {
            if(!(mask & (1u<<(p-1))))continue;
            int prediction;
            if(!row && col<2)prediction=1<<(bits-1);
            else if(!row)prediction=a;
            else if(col<2)prediction=b;
            else switch(p) {
                case 1:prediction=a;break;
                case 2:prediction=b;break;
                case 3:prediction=c;break;
                case 4:prediction=a+b-c;break;
                case 5:prediction=a+((b-c)>>1);break;
                case 6:prediction=b+((a-c)>>1);break;
                default:prediction=(a+b)>>1;break;
            }
            int diff=int(int16_t(sample-prediction));
            unsigned magnitude=unsigned(diff<0 ? -diff : diff);
            unsigned category=magnitude ? 32u-__clz(magnitude) : 0;
            atomicAdd(&local_hist[((p-1)*2+component)*17+category],1u);
        }
    }
    __syncthreads();
    for(uint32_t i=lid;i<238;i+=blockDim.x)if(local_hist[i])atomicAdd(&hist[i],local_hist[i]);
}

struct Buffers {
    uint16_t *pixels=nullptr;
    uint32_t *hist=nullptr;
    size_t capacity=0;
    size_t hist_capacity=0;
    cudaStream_t stream=nullptr;
    ~Buffers(){if(pixels)cudaFree(pixels);if(hist)cudaFree(hist);if(stream)cudaStreamDestroy(stream);}
};
static thread_local Buffers buffers;

EXPORT int cdng_gpu_hist(const uint16_t *pixels,uint32_t count,uint32_t tiles,uint32_t stride,
    uint32_t bits,uint32_t mask,uint32_t *hist,const char *,char *error,uint32_t error_size) {
    if(!count || !tiles || uint64_t(count)*tiles>UINT32_MAX || stride<2 || stride%2 || count%stride || bits<8 || bits>16 || !mask || (mask&~127u)) {
        snprintf(error,error_size,"Invalid GPU histogram dimensions");return 2;
    }
    cudaError_t status=cudaSetDevice(0);
#define CHECK(call) do {status=(call);if(status!=cudaSuccess){snprintf(error,error_size,"%s: %s",#call,cudaGetErrorString(status));return 1;}}while(0)
    CHECK(status);
    if(!buffers.stream)CHECK(cudaStreamCreateWithFlags(&buffers.stream,cudaStreamNonBlocking));
    size_t total=size_t(count)*tiles,hist_count=size_t(tiles)*238;
    if(buffers.hist_capacity<hist_count) {
        if(buffers.hist){CHECK(cudaFree(buffers.hist));buffers.hist=nullptr;buffers.hist_capacity=0;}
        CHECK(cudaMalloc((void**)&buffers.hist,hist_count*4));buffers.hist_capacity=hist_count;
    }
    if(buffers.capacity<total) {
        if(buffers.pixels){CHECK(cudaFree(buffers.pixels));buffers.pixels=nullptr;buffers.capacity=0;}
        CHECK(cudaMalloc((void**)&buffers.pixels,total*2));buffers.capacity=total;
    }
    CHECK(cudaMemcpyAsync(buffers.pixels,pixels,total*2,cudaMemcpyHostToDevice,buffers.stream));
    CHECK(cudaMemsetAsync(buffers.hist,0,hist_count*4,buffers.stream));
    cdng_histogram<<<tiles*((count+255)/256),256,0,buffers.stream>>>(buffers.pixels,count,stride,bits,mask,buffers.hist);
    CHECK(cudaGetLastError());
    CHECK(cudaMemcpyAsync(hist,buffers.hist,hist_count*4,cudaMemcpyDeviceToHost,buffers.stream));
    CHECK(cudaStreamSynchronize(buffers.stream));return 0;
#undef CHECK
}

EXPORT const char *cdng_gpu_name() {
    static thread_local char name[256];cudaDeviceProp info;
    cudaError_t s=cudaGetDeviceProperties(&info,0);
    snprintf(name,sizeof(name),"%s",s==cudaSuccess ? info.name : cudaGetErrorString(s));return name;
}
