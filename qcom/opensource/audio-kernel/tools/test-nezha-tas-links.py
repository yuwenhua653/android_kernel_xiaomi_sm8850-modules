#!/usr/bin/env python3
"""Test the actual Nezha sound-card link selection, with OF/devres host stubs."""
import os,subprocess,tempfile
from pathlib import Path
s=(Path(__file__).resolve().parents[1]/'asoc/audio_machine.c').read_text();a=s.index('static int nezha_tas25xx_configure_links(');b=s.index('static int msm_populate_dai_link_component_of_node',a)
code=r'''
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
#define GFP_KERNEL 0
#define LPASS_BE_PRI_TDM_RX_0 "PRI_RX"
#define LPASS_BE_PRI_TDM_TX_0 "PRI_TX"
static bool nezha=true;
#define IS_ENABLED(x) (nezha)
struct device_node {int enabled,refs;};
struct snd_soc_dai_link_component {struct device_node *of_node;const char *dai_name;};
struct snd_soc_dai_link {const char *name;struct snd_soc_dai_link_component *codecs;int num_codecs;};
struct snd_soc_card {void *dev;int num_links;struct snd_soc_dai_link *dai_link;};
static struct device_node nodes[2],*managed;
static int count,fail_action,fail_alloc;
static void *allocated;
static void of_node_put(void *v){struct device_node *n=v;if(n){assert(n->refs>0);n->refs--;}}
static void *of_node_get(struct device_node *n){n->refs++;return n;}
static bool of_device_is_available(struct device_node *n){return n->enabled;}
static struct device_node *next_node(struct device_node *prev){int i=prev?prev-nodes+1:0;of_node_put(prev);return i<count?of_node_get(&nodes[i]):NULL;}
#define for_each_compatible_node(n,t,c) for(n=next_node(NULL);n;n=next_node(n))
static void myron_tfa_put_node(void *n){of_node_put(n);}
static int devm_add_action_or_reset(void *dev,void(*f)(void *),void *n){if(fail_action){f(n);return -ENOMEM;}managed=n;return 0;}
static void *devm_kzalloc(void *d,size_t n,int flags){if(fail_alloc)return NULL;allocated=calloc(1,n);assert(allocated);return allocated;}
'''
test=r'''
int main(void){
 for(int scenario=0;scenario<9;scenario++){
  struct snd_soc_dai_link_component original;
  struct snd_soc_dai_link links[2]={{"PRI_RX",&original,1},{"PRI_TX",&original,1}};
  struct snd_soc_card card={.num_links=2,.dai_link=links};
  memset(nodes,0,sizeof(nodes));nodes[0].enabled=nodes[1].enabled=1;
  count=1;managed=NULL;allocated=NULL;fail_action=fail_alloc=0;nezha=true;
  int expected=0;
  switch(scenario){
  case 1:nezha=false;break;
  case 2:count=0;break;
  case 3:nodes[0].enabled=0;break;
  case 4:count=2;expected=-EINVAL;break;
  case 5:links[1].name="OTHER";expected=-EINVAL;break;
  case 6:links[1].name="PRI_RX";expected=-EINVAL;break;
  case 7:fail_action=1;expected=-ENOMEM;break;
  case 8:fail_alloc=1;expected=-ENOMEM;break;
  }
  assert(nezha_tas25xx_configure_links(&card)==expected);
  if(!scenario){assert(links[0].codecs==links[1].codecs);assert(links[0].codecs->of_node==&nodes[0]);assert(!strcmp(links[0].codecs->dai_name,"tas25xx ASI1"));}
  else assert(links[0].codecs==&original && links[1].codecs==&original);
  if(managed)of_node_put(managed);free(allocated);assert(!nodes[0].refs && !nodes[1].refs);
 }
 puts("PASS: actual Nezha primary TDM RX/TX selection; absent/disabled/duplicate nodes, malformed links and allocation failure; OF refs balanced");
}
'''
with tempfile.TemporaryDirectory(prefix='tas-links-') as d:
 p=Path(d);(p/'test.c').write_text(code+s[a:b]+test)
 subprocess.run([os.getenv('CC','cc'),'-g','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'),check=True)
