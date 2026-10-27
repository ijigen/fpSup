// Runtime-loaded libjxl, native integer lossless codec only. BSD headers in rust/vendor.
#include <jxl/encode.h>
#include <jxl/decode.h>
#include <cstring>
#include <cstdint>
#include <cstdio>
#ifdef _WIN32
#include <windows.h>
static void* openlib(const char* p) { wchar_t w[32768]; if(!MultiByteToWideChar(CP_UTF8,0,p,-1,w,32768)) return nullptr; return LoadLibraryW(w); }
static void* symbol(void* p,const char* s){return reinterpret_cast<void*>(GetProcAddress((HMODULE)p,s));}
static void closelib(void* p){FreeLibrary((HMODULE)p);}
#else
#include <dlfcn.h>
static void* openlib(const char* p){return dlopen(p,RTLD_NOW|RTLD_LOCAL);}
static void* symbol(void* p,const char* s){return dlsym(p,s);}
static void closelib(void* p){dlclose(p);}
#endif
#define FUNCS(X) \
X(JxlEncoderVersion) X(JxlEncoderCreate) X(JxlEncoderDestroy) X(JxlEncoderInitBasicInfo) \
X(JxlEncoderSetBasicInfo) X(JxlEncoderSetColorEncoding) X(JxlColorEncodingSetToLinearSRGB) \
X(JxlEncoderFrameSettingsCreate) X(JxlEncoderSetFrameLossless) X(JxlEncoderSetFrameDistance) \
X(JxlEncoderFrameSettingsSetOption) X(JxlEncoderAddImageFrame) X(JxlEncoderCloseInput) X(JxlEncoderProcessOutput) \
X(JxlDecoderCreate) X(JxlDecoderDestroy) X(JxlDecoderSubscribeEvents) X(JxlDecoderSetInput) \
X(JxlDecoderCloseInput) X(JxlDecoderProcessInput) X(JxlDecoderGetBasicInfo) \
X(JxlDecoderImageOutBufferSize) X(JxlDecoderSetImageOutBuffer) \
X(JxlEncoderSetFrameBitDepth) X(JxlDecoderSetImageOutBitDepth)
struct Api {
 void* lib;
 #define MEMBER(f) decltype(&f) f;
 FUNCS(MEMBER)
 #undef MEMBER
};
extern "C" {
void* cdng_jxl_open(const char* path){
 auto a=new Api{};a->lib=openlib(path);if(!a->lib){delete a;return nullptr;}
 #define LOAD(f) a->f=reinterpret_cast<decltype(a->f)>(symbol(a->lib,#f)); if(!a->f){closelib(a->lib);delete a;return nullptr;}
 FUNCS(LOAD)
 #undef LOAD
 if(a->JxlEncoderVersion()<11002){closelib(a->lib);delete a;return nullptr;}
 return a;
}
void cdng_jxl_close(void* ptr){auto a=(Api*)ptr;closelib(a->lib);delete a;}
uint32_t cdng_jxl_version(void* ptr){return ((Api*)ptr)->JxlEncoderVersion();}
// Output grows in Rust; returning 2 requests a larger destination. No C-owned output copy.
// Samples are stored at `bits` (values are used as is, not rescaled from 16 bits).
// buffering / group < 0 keep libjxl's defaults.
int cdng_jxl_encode(void* ptr,const uint16_t* pixels,uint32_t w,uint32_t h,uint32_t bits,int effort,int tier,int buffering,int group,uint8_t* out,size_t cap,size_t* used){
 auto a=(Api*)ptr;auto enc=a->JxlEncoderCreate(nullptr);if(!enc)return 1;
 JxlBasicInfo info;a->JxlEncoderInitBasicInfo(&info);info.xsize=w;info.ysize=h;info.bits_per_sample=bits;info.num_color_channels=1;info.uses_original_profile=JXL_TRUE;
 JxlColorEncoding color;a->JxlColorEncodingSetToLinearSRGB(&color,JXL_TRUE);
 int result=1;
 if(a->JxlEncoderSetBasicInfo(enc,&info)==JXL_ENC_SUCCESS && a->JxlEncoderSetColorEncoding(enc,&color)==JXL_ENC_SUCCESS){
  auto fs=a->JxlEncoderFrameSettingsCreate(enc,nullptr);
  JxlPixelFormat fmt={1,JXL_TYPE_UINT16,JXL_NATIVE_ENDIAN,0};
  JxlBitDepth depth={JXL_BIT_DEPTH_FROM_CODESTREAM,0,0};
  if(fs && a->JxlEncoderSetFrameLossless(fs,JXL_TRUE)==JXL_ENC_SUCCESS &&
    a->JxlEncoderSetFrameBitDepth(fs,&depth)==JXL_ENC_SUCCESS &&
    (buffering<0 || a->JxlEncoderFrameSettingsSetOption(fs,JXL_ENC_FRAME_SETTING_BUFFERING,buffering)==JXL_ENC_SUCCESS) &&
    (group<0 || a->JxlEncoderFrameSettingsSetOption(fs,JXL_ENC_FRAME_SETTING_MODULAR_GROUP_SIZE,group)==JXL_ENC_SUCCESS) &&
    a->JxlEncoderSetFrameDistance(fs,0)==JXL_ENC_SUCCESS &&
    a->JxlEncoderFrameSettingsSetOption(fs,JXL_ENC_FRAME_SETTING_EFFORT,effort)==JXL_ENC_SUCCESS &&
    a->JxlEncoderFrameSettingsSetOption(fs,JXL_ENC_FRAME_SETTING_DECODING_SPEED,tier)==JXL_ENC_SUCCESS &&
    a->JxlEncoderAddImageFrame(fs,&fmt,pixels,size_t(w)*h*2)==JXL_ENC_SUCCESS){
    a->JxlEncoderCloseInput(enc);uint8_t* next=out;size_t avail=cap;
    auto status=a->JxlEncoderProcessOutput(enc,&next,&avail);*used=cap-avail;
    result=status==JXL_ENC_SUCCESS?0:(status==JXL_ENC_NEED_MORE_OUTPUT?2:1);
  }
 }
 a->JxlEncoderDestroy(enc);return result;
}
int cdng_jxl_decode(void* ptr,const uint8_t* data,size_t len,uint32_t w,uint32_t h,uint32_t bits,uint16_t* out,size_t count){
 auto a=(Api*)ptr;auto dec=a->JxlDecoderCreate(nullptr);if(!dec)return 1;
 int result=1;bool saw_info=false,saw_pixels=false;
 JxlPixelFormat fmt={1,JXL_TYPE_UINT16,JXL_NATIVE_ENDIAN,0};
 JxlBitDepth depth={JXL_BIT_DEPTH_FROM_CODESTREAM,0,0};
 if(a->JxlDecoderSubscribeEvents(dec,JXL_DEC_BASIC_INFO|JXL_DEC_FULL_IMAGE)!=JXL_DEC_SUCCESS)goto done;
 if(a->JxlDecoderSetInput(dec,data,len)!=JXL_DEC_SUCCESS)goto done;
 a->JxlDecoderCloseInput(dec);
 for(;;){auto status=a->JxlDecoderProcessInput(dec);
  if(status==JXL_DEC_BASIC_INFO){JxlBasicInfo info;
   if(a->JxlDecoderGetBasicInfo(dec,&info)!=JXL_DEC_SUCCESS || info.xsize!=w || info.ysize!=h || info.bits_per_sample!=bits || info.exponent_bits_per_sample!=0 || info.num_color_channels!=1 || info.num_extra_channels!=0 || info.have_animation || info.orientation!=JXL_ORIENT_IDENTITY)break;
   saw_info=true;
  }else if(status==JXL_DEC_NEED_IMAGE_OUT_BUFFER){size_t bytes=0;
   if(!saw_info || count!=size_t(w)*h || a->JxlDecoderImageOutBufferSize(dec,&fmt,&bytes)!=JXL_DEC_SUCCESS || bytes!=count*2 || a->JxlDecoderSetImageOutBuffer(dec,&fmt,out,bytes)!=JXL_DEC_SUCCESS ||
      a->JxlDecoderSetImageOutBitDepth(dec,&depth)!=JXL_DEC_SUCCESS)break; // only valid after the buffer is set
  }else if(status==JXL_DEC_FULL_IMAGE){saw_pixels=true;}
  else if(status==JXL_DEC_SUCCESS){result=saw_info&&saw_pixels?0:1;break;}
  else break;
 }
done:a->JxlDecoderDestroy(dec);return result;
}
}
