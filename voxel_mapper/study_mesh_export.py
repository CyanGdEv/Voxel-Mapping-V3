"""Export study component solids as a portable, coloured Y-up GLB."""
import json
import struct
import numpy as np


def write_glb(model,path):
    data=bytearray();views=[];accessors=[];meshes=[];nodes=[];materials=[]
    def buffer(array,kind):
        array=array.astype('<f4')
        while len(data)%4:data.append(0)
        offset=len(data);raw=array.tobytes();data.extend(raw)
        views.append({'buffer':0,'byteOffset':offset,'byteLength':len(raw),'target':34962})
        accessors.append({'bufferView':len(views)-1,'componentType':5126,'count':len(array),
                          'type':kind,'min':array.min(axis=0).tolist(),'max':array.max(axis=0).tolist()})
        return len(accessors)-1
    for c in model['components']:
        # Source XYZ = frontage, depth, height; GLTF XYZ = frontage, height, -depth.
        mesh=c['mesh'];v=np.asarray(mesh['vertices'],dtype=np.float64)
        v=np.column_stack((v[:,0],v[:,2],-v[:,1]));tri=v[np.asarray(mesh['triangles'])]
        n=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);norm=np.linalg.norm(n,axis=1)
        if np.any(norm==0):raise ValueError('Degenerate mesh triangle cannot be exported')
        n/=norm[:,None]
        positions=buffer(tri.reshape(-1,3),'VEC3');normals=buffer(np.repeat(n,3,axis=0),'VEC3')
        colour=c.get('colour','775338' if c.get('role')=='roof' else '67947b' if c['id'].startswith('interior_partition_') else '859caf' if c['id']=='courtyard_wall' else 'c99a5c')
        materials.append({'name':c['id'],'doubleSided':False,'pbrMetallicRoughness':{
            'baseColorFactor':[int(colour[i:i+2],16)/255 for i in (0,2,4)]+[1],
            'metallicFactor':0,'roughnessFactor':.9}})
        meshes.append({'name':c['id'],'primitives':[{'attributes':{'POSITION':positions,'NORMAL':normals},'material':len(materials)-1,'mode':4}]})
        nodes.append({'name':c['id'],'mesh':len(meshes)-1,'extras':{'role':c.get('role'),'evidence':c.get('evidence')}})
    obj={'asset':{'version':'2.0','generator':'Voxel Mapper source-pinned courtyard study'},
         'scene':0,'scenes':[{'nodes':list(range(len(nodes)))}],'nodes':nodes,'meshes':meshes,
         'materials':materials,'buffers':[{'byteLength':len(data)}],'bufferViews':views,'accessors':accessors,
         'extras':{'units':'metres','status':model['status'],'assumptions':model['assumptions'],
                   'surveyed_complete_structure':False}}
    encoded=json.dumps(obj,separators=(',',':')).encode()
    while len(encoded)%4:encoded+=b' '
    while len(data)%4:data.append(0)
    total=12+8+len(encoded)+8+len(data)
    from pathlib import Path
    Path(path).write_bytes(struct.pack('<4sII',b'glTF',2,total)+struct.pack('<I4s',len(encoded),b'JSON')+encoded+struct.pack('<I4s',len(data),b'BIN\0')+data)
    return {'component_meshes':len(meshes),'byte_length':total,'coordinate_frame':'Y-up, metres; source depth maps to negative Z'}
