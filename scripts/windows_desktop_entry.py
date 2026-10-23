"""PyInstaller entry: dispatch frozen workers before importing GUI modules."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from voxel_mapper.desktop_app import main
    raise SystemExit(main())
