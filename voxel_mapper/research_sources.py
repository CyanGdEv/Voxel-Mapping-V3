"""Public research-site routing and bounded, cited structured-data views."""
import json
import math
import re
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

VERSION='public-research-sources-v1'
FAMILIES={
    'knowledge':{'hosts':['www.wikidata.org','en.wikipedia.org','commons.wikimedia.org','upload.wikimedia.org'],
        'hint':'ride history former names'},
    'rides':{'hosts':['rcdb.com','coasterpedia.net'],'hint':'ride layout manufacturer'},
    'archives':{'hosts':['www.loc.gov','historicengland.org.uk','discovery.nationalarchives.gov.uk'],
        'hint':'plans drawings photographs'},
    'planning_data':{'hosts':['www.planning.data.gov.uk'],'hint':'planning location records'},
    'geospatial':{'hosts':['www.arcgis.com','environment.data.gov.uk','maps.nls.uk'],
        'hint':'map survey lidar'}
}


def families(values):
    if not isinstance(values,list) or len(values)>5 or any(not isinstance(v,str) or v not in FAMILIES for v in values):
        raise ValueError('Known public source families required')
    if len(set(values))!=len(values):raise ValueError('Distinct public source families required')
    return values


def search_queries(query,scope,selected):
    families(selected)
    subject=(' '.join([scope['site'],scope['location'],*scope['tags'][:2]]) if scope else
        re.sub(r'(?<!\S)site:[^\s]+','',query)).strip()[:150]
    if not subject:return []
    return [{'family':family,'query':(subject+' '+FAMILIES[family]['hint']+' ('+
        ' OR '.join('site:'+host for host in FAMILIES[family]['hosts'] if host!='upload.wikimedia.org')+')')[:300]}
        for family in selected]


def related_urls(value,selected):
    """Documented public API views of exact identifiers already in offered URLs."""
    families(selected);p=urlsplit(value);host=p.hostname;targets=[]
    if 'knowledge' in selected:
        match=re.fullmatch(r'/wiki/(?:Special:EntityData/)?(Q[1-9][0-9]*)(?:\.json)?',p.path)
        if host=='www.wikidata.org' and match:
            targets.append('https://www.wikidata.org/wiki/Special:EntityData/'+match[1]+'.json')
        if host=='commons.wikimedia.org' and p.path.startswith('/wiki/File:'):
            from urllib.parse import unquote
            targets.append('https://commons.wikimedia.org/w/api.php?'+urlencode({'action':'query','format':'json',
                'prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':1600,'titles':unquote(p.path[6:])}))
    if 'geospatial' in selected and host=='www.arcgis.com':
        identifier=parse_qs(p.query).get('id',[''])[0]
        if re.fullmatch('[0-9a-f]{32}',identifier) and p.path in ('/home/item.html','/apps/mapviewer/index.html'):
            targets.append('https://www.arcgis.com/sharing/rest/content/items/'+identifier+'?f=json')
    if 'geospatial' in selected and host and host.endswith('.arcgis.com') and re.search(r'/rest/services/.+/(?:FeatureServer|MapServer)(?:/[0-9]+)?$',p.path) and 'f' not in parse_qs(p.query):
        args=parse_qs(p.query);args['f']=['json'];targets.append(urlunsplit((p.scheme,p.netloc,p.path,urlencode(args,doseq=True),'')))
    if 'archives' in selected and host=='www.loc.gov' and ('/item/' in p.path):
        args=parse_qs(p.query);args['fo']=['json']
        targets.append(urlunsplit((p.scheme,p.netloc,p.path,urlencode(args,doseq=True),'')))
    return [t for t in targets if t!=value]


def bounded_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate structured-data field')
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Finite JSON required')))
    pending=[(value,0)];count=0
    while pending:
        item,depth=pending.pop();count+=1
        if isinstance(item,float) and not math.isfinite(item):raise ValueError('Finite JSON required')
        if depth>32 or count>100000:raise ValueError('Structured-data nesting/item budget exceeded')
        if isinstance(item,dict):pending.extend((v,depth+1) for v in item.values())
        elif isinstance(item,list):pending.extend((v,depth+1) for v in item)
    return value


def _view(data,source_url):
    from .web_evidence import url
    from bs4 import BeautifulSoup
    facts=[];links=[];seen=set()
    def fact(field,value):
        if value is None:return
        if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False,separators=(',',':'))
        value=str(value)
        text=(BeautifulSoup(value,'html.parser').get_text(' ',strip=True) if '<' in value and '>' in value else value)[:1024]
        if text and len(facts)<96:facts.append({'field':field,'value':text})
    def link(value,title,role='reference'):
        if not isinstance(value,str):return
        if value.startswith('//'):value='https:'+value
        try:value=url(value)
        except ValueError:return
        if value not in seen and len(links)<64:
            links.append({'url':value,'title':str(title)[:160],'role':role});seen.add(value)
    if not isinstance(data,dict):raise ValueError('Structured source object required')
    if data.get('error') or data.get('errors'):raise ValueError('Source API returned an error object')
    schema=None
    if isinstance(data.get('entities'),dict):
        schema='wikidata_entities'
        for identifier,entity in list(data['entities'].items())[:8]:
            if not isinstance(entity,dict) or not re.fullmatch('Q[1-9][0-9]*',identifier):continue
            if entity.get('missing') is not None:continue
            fact('entity',identifier)
            for field in ['labels','descriptions']:
                english=entity.get(field,{}).get('en',{})
                fact(field,english.get('value'))
            fact('aliases',[v.get('value') for v in entity.get('aliases',{}).get('en',[])[:16]])
            claims=entity.get('claims',{})
            for prop in ['P31','P17','P131','P361','P176','P625','P18','P373','P856','P571','P1619','P2048','P2043']:
                for claim in claims.get(prop,[])[:4]:
                    snak=claim.get('mainsnak',{});dv=snak.get('datavalue',{})
                    if snak.get('snaktype')!='value' or 'value' not in dv:continue
                    value=dv['value'];fact(prop,{'value':value,'rank':claim.get('rank','normal')})
                    if prop=='P856':link(value,'Official website from '+identifier)
                    if prop=='P18' and isinstance(value,str):
                        page='https://commons.wikimedia.org/wiki/File:'+quote(value.replace(' ','_'),safe='')
                        link(page,'Image '+value,'image_metadata')
                        for api in related_urls(page,['knowledge']):link(api,'Image metadata '+value,'structured_api')
            for sitelink in list(entity.get('sitelinks',{}).values())[:32]:link(sitelink.get('url'),sitelink.get('title','Reference'))
    elif isinstance(data.get('query'),dict) and isinstance(data['query'].get('pages'),(dict,list)):
        schema='mediawiki_pages';pages=data['query']['pages'];pages=list(pages.values()) if isinstance(pages,dict) else pages
        for page in pages[:16]:
            fact('title',page.get('title'));fact('description',page.get('description'))
            for info in page.get('imageinfo',[])[:2]:
                link(info.get('thumburl') or info.get('url'),page.get('title','Image'),'image')
                link(info.get('descriptionurl'),page.get('title','Image description'),'image_metadata')
                fact('original_image_url',info.get('url'))
                meta=info.get('extmetadata',{})
                for key in ['LicenseShortName','LicenseUrl','UsageTerms','AttributionRequired','Artist','Credit','ImageDescription']:
                    value=meta.get(key,{})
                    if isinstance(value,dict):fact(key,value.get('value'))
    elif data.get('type')=='FeatureCollection' or isinstance(data.get('features'),list):
        schema='geojson_features' if data.get('type')=='FeatureCollection' else 'arcgis_features'
        fact('source_record_count',len(data['features']))
        for feature in data['features'][:32]:
            properties=feature.get('properties',feature.get('attributes',{}))
            if not isinstance(properties,dict):continue
            for key,value in list(properties.items())[:32]:
                fact(str(key)[:80],value)
                if isinstance(value,str):link(value,str(key))
        fact('geometry_usage','Research context only; map geometry is not registered or accepted into a world')
    elif isinstance(data.get('entities'),list):
        schema='planning_data_entities';fact('record_count',len(data['entities']))
        for entity in data['entities'][:32]:
            for key in ['entity','dataset','name','reference','organisation-entity','start-date','end-date','point','document-url','documentation-url','entry-date']:
                fact(key,entity.get(key));link(entity.get(key),str(entity.get('name',key)))
    elif isinstance(data.get('results'),list):
        schema='loc_catalogue' if urlsplit(source_url).hostname=='www.loc.gov' else 'public_catalogue'
        fact('record_count',len(data['results']))
        for item in data['results'][:32]:
            for key in ['title','description','date','type','snippet','subject']:fact(key,item.get(key))
            for key in ['url','id','link','links']:
                value=item.get(key)
                if isinstance(value,dict):
                    for v in list(value.values())[:8]:link(v,item.get('title','Catalogue item'))
                elif isinstance(value,list):
                    for v in value[:8]:link(v,item.get('title','Catalogue item'))
                else:link(value,item.get('title','Catalogue item'))
            if re.fullmatch('[0-9a-f]{32}',str(item.get('id',''))) and urlsplit(source_url).hostname=='www.arcgis.com':
                link('https://www.arcgis.com/home/item.html?id='+item['id'],item.get('title','GIS item'))
            for image in item.get('image_url',[])[:2]:link(image,item.get('title','Image'),'image')
    elif isinstance(data.get('item'),dict) or isinstance(data.get('resources'),list):
        schema='loc_item'
        for key in ['title','description','date','subject','rights_information','rights_advisory']:fact(key,data.get('item',data).get(key))
        for resource in data.get('resources',[])[:16]:
            for key in ['pdf','url','image']:link(resource.get(key),'Archive '+key,'document' if key=='pdf' else 'reference')
    elif 'title' in data and ('content_urls' in data or data.get('type')=='standard'):
        schema='wikipedia_summary'
        for key in ['title','description','extract']:fact(key,data.get(key))
        for key in ['thumbnail','originalimage']:
            if isinstance(data.get(key),dict):link(data[key].get('source'),data['title'],'image')
    elif isinstance(data.get('href'),str) and 'extent' in data and 'width' in data and 'height' in data:
        schema='arcgis_image_export'
        for key in ['width','height','extent','scale']:fact(key,data.get(key))
        link(data['href'],'Georeferenced aerial RGB image','image')
    elif 'id' in data and 'title' in data and ('type' in data or 'url' in data):
        schema='arcgis_item'
        for key in ['id','title','type','description','snippet','tags','extent','licenseInfo','accessInformation']:fact(key,data.get(key))
        link(data.get('url'),data['title'],'map_service')
    elif isinstance(data.get('layers'),list) or isinstance(data.get('fields'),list):
        schema='arcgis_service'
        for key in ['name','description','serviceDescription','copyrightText','capabilities','geometryType','extent','maxRecordCount']:fact(key,data.get(key))
        for layer in data.get('layers',[])[:32]:
            fact('layer',layer)
            if type(layer.get('id')) is int and 0<=layer['id']<=1000000:
                p=urlsplit(source_url);link(urlunsplit((p.scheme,p.netloc,p.path.rstrip('/')+'/'+str(layer['id']),'f=json','')),layer.get('name','Map layer'),'structured_api')
        for field in data.get('fields',[])[:32]:fact('field',field)
    elif data.get('@context') or data.get('@type') or data.get('@graph'):
        schema='json_ld';pending=list(data.get('@graph',[])) if isinstance(data.get('@graph'),list) else [data]
        for item in pending[:16]:
            if not isinstance(item,dict):continue
            for key in ['@type','name','alternateName','description','keywords','datePublished','address','geo','license']:fact(key,item.get(key))
            for key in ['url','contentUrl','image','associatedMedia','subjectOf']:
                values=item.get(key,[]);values=values if isinstance(values,list) else [values]
                for value in values[:8]:
                    if isinstance(value,dict):value=value.get('contentUrl') or value.get('url') or value.get('@id')
                    link(value,str(item.get('name',key)),'image' if key=='image' else 'reference')
    else:raise ValueError('Unsupported public JSON schema')
    text='\n'.join(f['field']+': '+f['value'] for f in facts)
    title=next((f['value'] for f in facts if f['field'] in ('title','labels','name')),schema)
    return {'format':'json','title':title[:200],'text':text[:12000],'text_truncated':len(text)>12000,
        'pages':None,'links':links,'text_status':'structured_public_metadata_unverified',
        'structured_schema':schema,'structured_view_version':VERSION,'structured_facts':facts}


def extract_json(raw,source_url):
    return _view(bounded_json(raw),source_url)


def html_views(soup,source_url):
    """Literal embedded JSON-LD/feed/document links; never execute page scripts."""
    from .web_evidence import url,urljoin
    views=[];links=[]
    for script in soup.find_all('script',attrs={'type':'application/ld+json'},limit=8):
        raw=script.string or script.get_text()
        if len(raw)>128000:continue
        try:
            data=bounded_json(raw);items=data if isinstance(data,list) else [data]
            for item in items[:8]:
                view=_view(item,source_url);views.append(view);links.extend(view['links'])
        except (ValueError,TypeError,AttributeError,RecursionError):continue
    for element in soup.find_all(['iframe','object','embed','link'],limit=128):
        value=None
        if element.name=='link' and element.get('type') in ('application/json','application/geo+json','application/ld+json'):
            value=element.get('href')
        elif element.name in ('iframe','embed'):value=element.get('src')
        elif element.name=='object':value=element.get('data')
        if not value:continue
        try:target=url(urljoin(source_url,value))
        except ValueError:continue
        links.append({'url':target,'title':str(element.get('title') or 'Embedded document / structured data')[:160],'role':'embedded_document'})
    return views,links[:64]
