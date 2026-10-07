"""Isolated bounded Overture reader, invoked only by automatic acquisition."""
import json
import sys


def main():
    import resource
    import shapely
    from overturemaps import record_batch_reader

    release, bounds_json, destination, count_limit, byte_limit = sys.argv[1:]
    limit = int(byte_limit)
    resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit))
    reader = record_batch_reader('building',bbox=json.loads(bounds_json),release=release,
                                 connect_timeout=10,request_timeout=30,stac=True)
    count = 0
    with open(destination,'w',encoding='utf-8') as stream:
        if reader is not None:
            for batch in reader:
                for row in batch.to_pylist():
                    count += 1
                    if count > int(count_limit):
                        raise ValueError('Overture feature budget exceeded')
                    geometry = json.loads(shapely.to_geojson(shapely.from_wkb(row.pop('geometry'))))
                    row.pop('bbox',None)
                    feature = {'type':'Feature','id':row.get('id'),'geometry':geometry,'properties':row}
                    stream.write(json.dumps(feature,default=lambda x:x.isoformat(),allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
