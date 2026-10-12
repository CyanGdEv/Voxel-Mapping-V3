"""Isolated bounded Overture reader, invoked only by automatic acquisition."""
import json
import sys


def record_to_feature(row):
    """The selected building partition supplies fields omitted from Parquet rows."""
    import shapely
    row = dict(row)
    geometry = json.loads(shapely.to_geojson(shapely.from_wkb(row.pop('geometry'))))
    row.pop('bbox',None)
    for key,value in [('theme','buildings'),('type','building')]:
        if row.get(key,value) != value:
            raise ValueError('Conflicting building partition metadata')
        row[key] = value
    return {'type':'Feature','id':row.get('id'),'geometry':geometry,'properties':row}


def main():
    from overturemaps import record_batch_reader

    release, bounds_json, destination, count_limit, byte_limit = sys.argv[1:]
    limit = int(byte_limit); count_limit = int(count_limit)
    if min(limit, count_limit) <= 0:
        raise ValueError('Positive Overture output budgets required')
    try:
        import resource
    except ImportError:
        resource = None
    if resource is not None:
        resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit))
    reader = record_batch_reader('building',bbox=json.loads(bounds_json),release=release,
                                 connect_timeout=10,request_timeout=30,stac=True)
    count = 0; size = 0
    # Count the exact bytes before writing on every platform. The Unix process
    # limit remains a second guard; Windows has no resource module.
    with open(destination,'wb') as stream:
        if reader is not None:
            for batch in reader:
                for row in batch.to_pylist():
                    count += 1
                    if count > count_limit:
                        raise ValueError('Overture feature budget exceeded')
                    feature = record_to_feature(row)
                    data = (json.dumps(feature,default=lambda x:x.isoformat(),allow_nan=False)+'\n').encode('utf-8')
                    size += len(data)
                    if size > limit:
                        raise ValueError('Overture byte budget exceeded')
                    stream.write(data)


if __name__ == '__main__':
    main()
