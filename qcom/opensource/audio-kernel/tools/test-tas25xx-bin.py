#!/usr/bin/env python3
"""Compile the production preflight validator with ASan/UBSan; optional stock bin."""
import os, pathlib, struct, subprocess, tempfile, sys
root=pathlib.Path(__file__).resolve().parents[1]
u32=lambda n:struct.pack('<I',n)
block=lambda name,data:name.encode()+u32(len(data))+data
cmd=lambda data=b'':u32(len(data))+data
name=lambda s:s.encode().ljust(64,b'\0')
head=u32(7)+name('test')+u32(0)+u32(0)+u32(2)+bytes([0,0x4a,0,0x48,16,0])+u32(0)+bytes(8)+bytes(20)
assert len(head)==118
image=block('HEADR',head)
for channel in range(2):
 image+=block('INITP',bytes([0])+u32(3)+bytes([0]))
 image+=block('HWPRM',u32(26)+cmd()*26)
 image+=block('PROFP',bytes([1])+name('normal')+u32(0)+cmd()*4)
 image+=block('INTRP',bytes([0])+cmd()*3+bytes(24))
 formats=block('RXFMT',u32(1)+b'16BIT'+cmd())+block('TXFMT',u32(1)+b'16_I2S_02_16_0'+cmd())
 image+=block('BLKOP',u32(2)+formats)
image+=block('KCNTR',u32(0))
source=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
typedef uint8_t u8;
typedef uint32_t u32;
#include "tas25xx-bin-validate.h"
int main(int argc,char **argv) {
 FILE *f=fopen(argv[1],"rb");assert(f);fseek(f,0,SEEK_END);size_t n=ftell(f);rewind(f);
 u8 *buf=malloc(n);assert(buf);assert(fread(buf,1,n,f)==n);fclose(f);
 const u8 *selected;size_t len;
 assert(tas_bin_select(buf,n,argc>2?strtoul(argv[2],0,0):0,&selected,&len));
 assert(tas_bin_validate(selected,len,2));
 assert(!tas_bin_validate(selected,len,1));
 assert(!tas_bin_validate(selected,len,3));
 /* Every truncation of a complete image must fail, without reading beyond it. */
 for(size_t i=0;i<len;i++) {
  u8 *p=malloc(i?i:1);assert(p);memcpy(p,selected,i);
  assert(!tas_bin_validate(p,i,2));free(p);
 }
 u8 *mut=malloc(n);assert(mut);unsigned seed=0x256281;
 for(unsigned i=0;i<20000;i++) {
  memcpy(mut,buf,n);seed=seed*1664525+1013904223;
  size_t pos=seed%n;mut[pos]^=(seed>>24)|1;
  const u8 *p;size_t z;
  if(tas_bin_select(mut,n,0,&p,&z)) (void)tas_bin_validate(p,z,2);
 }
 free(mut);free(buf);puts("PASS: image, channel mismatch, every truncation and 20000 mutations (ASan/UBSan)");
}
'''
with tempfile.TemporaryDirectory(prefix='tas25xx-test-') as tmp:
 t=pathlib.Path(tmp);(t/'test.c').write_text(source);(t/'valid.bin').write_bytes(image)
 subprocess.run([os.getenv('CC','cc'),'-std=c11','-g','-Wall','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(root/'asoc/codecs/tas25xx/inc'),str(t/'test.c'),'-o',str(t/'test')],check=True)
 env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0')
 subprocess.run([str(t/'test'),str(t/'valid.bin')],env=env,check=True)
 # Metadata selection, including duplicate revisions and truncation coverage.
 (t/'meta.bin').write_bytes(b'MDATA'+u32(1)+u32(0)+u32(len(image))+bytes(12)+image)
 subprocess.run([str(t/'test'),str(t/'meta.bin')],env=env,check=True)
 if len(sys.argv)>1:subprocess.run([str(t/'test'),*sys.argv[1:]],env=env,check=True)
