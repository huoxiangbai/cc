"""The two optional providers' actual Java baseline: owner-scoped local facts.

OpenViking endpoint never performed HTTP in the original implementation. This
module does not advertise a successful remote/vector integration.
"""
from collections import defaultdict


def schema(name,actions):
    props={'action':{'type':'string','enum':actions,'description':' | '.join(actions)}}
    if name=='viking_memory':props['category']={'type':'string','enum':['profile','preference','event'],'description':'Memory category'}
    props['content']={'type':'string','description':'Fact content for add' if name=='fact_store' else 'Content to remember'}
    props['query']={'type':'string','description':'Search query'}
    return {'type':'function','function':{'name':name,'description':'Holographic local fact store: add/list/search deep memory facts' if name=='fact_store' else 'OpenViking-style memory: remember/search/browse by category','parameters':{'type':'object','properties':props,'required':['action']}}}


class Providers:
    def __init__(self,config):
        self.enabled=set(config.get('providers',[]));self.facts=defaultdict(list);self.buckets=defaultdict(lambda:defaultdict(list))
        if self.enabled-{'builtin','holographic','openviking'}:raise ValueError('Unknown memory provider')
        self.endpoint=config.get('openviking_endpoint','')

    @property
    def schemas(self):
        return ([schema('fact_store',['add','list','search'])] if 'holographic' in self.enabled else [])+([schema('viking_memory',['remember','search','browse'])] if 'openviking' in self.enabled else [])

    def write(self,owner,action,target,content):
        if action not in ('add','replace') or not content:return
        if 'holographic' in self.enabled and content not in self.facts[owner]:self.facts[owner].append(content)
        bucket=self.buckets[owner]['preference' if target=='user' else 'profile']
        if 'openviking' in self.enabled and content not in bucket:bucket.append(content)

    def prefetch(self,owner,query,provider=None):
        q=(query or '').lower();blocks=[]
        if not q.strip():return ''
        if 'holographic' in self.enabled and provider in (None,'holographic'):
            facts=self.facts[owner];hits=[f for f in facts if q and q in f.lower()][:5] or facts[-3:]
            if hits:blocks.append('## Holographic Memory\n'+'\n'.join('- '+f for f in hits))
        if 'openviking' in self.enabled and provider in (None,'openviking'):
            hits=[f'- [{cat}] {fact}' for cat,values in self.buckets[owner].items() for fact in values if q and q in fact.lower()][:5]
            if hits:blocks.append('## OpenViking Memory\n'+'\n'.join(hits))
        return '\n'.join(blocks)

    def execute(self,owner,name,args):
        action=str(args.get('action') or '').lower();content=str(args.get('content') or '').strip()
        if name=='fact_store' and 'holographic' in self.enabled:
            if action=='add':
                if not content:return dict(success=False,message='content required')
                if content not in self.facts[owner]:self.facts[owner].append(content)
                return dict(success=True,message='fact added')
            if action=='list':return dict(success=True,facts=list(self.facts[owner]))
            if action=='search':return dict(success=True,result=self.prefetch(owner,args.get('query',''),'holographic'))
        if name=='viking_memory' and 'openviking' in self.enabled:
            if action=='remember':
                if not content:return dict(success=False,message='content required')
                cat=args.get('category') or 'profile'
                cat=str(cat).lower()
                if content not in self.buckets[owner][cat]:self.buckets[owner][cat].append(content)
                return dict(success=True,message='remembered',category=cat)
            if action=='browse':return dict(success=True,buckets={k:list(v) for k,v in self.buckets[owner].items()})
            if action=='search':return dict(success=True,result=self.prefetch(owner,args.get('query',''),'openviking'))
        return dict(success=False,message='unknown action')

    def sync(self,owner,user):
        if 'holographic' in self.enabled and 12<len(user or '')<200 and any(v in user.lower() for v in ('喜欢','偏好','prefer')):
            if user not in self.facts[owner]:self.facts[owner].append(user)
